"""Manages Bybit WebSocket connections for all active trading accounts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, Set

from backend.async_persistence import AsyncAnalysisDB
from backend.crypto import decrypt_value
from backend.services.bybit_ws_client import BybitWSClient

logger = logging.getLogger(__name__)

# Cap on concurrent in-flight wallet-listener tasks. Wallet frames are snapshots,
# so under a WS storm it's safe to drop frames once the backlog exceeds this —
# the next frame supersedes the dropped one. Prevents unbounded task growth.
_MAX_INFLIGHT_WALLET_TASKS = 200


class AccountWSManager:
    """Orchestrates one BybitWSClient per active account, broadcasting events to connected frontends."""

    def __init__(self, db: AsyncAnalysisDB):
        self._db = db
        self._clients: Dict[str, BybitWSClient] = {}
        self._frontend_queues: Set[asyncio.Queue] = set()
        self._wallet_listeners: list = []
        self._accounts_service: Any = None
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[None]] = set()

    def set_accounts_service(self, accounts_service: Any) -> None:
        """Inject accounts service for wallet re-fetch on WS reconnect."""
        self._accounts_service = accounts_service

    async def start(self) -> None:
        """Initialize WebSocket connections for all active accounts."""
        async with self._lock:
            accounts = await self._db.list_accounts()
            for acc in accounts:
                if acc["is_active"]:
                    await self._start_account(acc["id"])
        logger.info("AccountWSManager started for %d accounts", len(self._clients))

    async def shutdown(self) -> None:
        """Disconnect all WebSocket clients and clean up."""
        async with self._lock:
            if self._clients:
                await asyncio.gather(
                    *(client.stop() for client in self._clients.values()),
                    return_exceptions=True,
                )
            self._clients.clear()
        # Cancel + drain any in-flight wallet-listener tasks so they don't write
        # during pool teardown ("Task was destroyed but it is pending").
        if self._background_tasks:
            pending = list(self._background_tasks)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self._background_tasks.clear()
        logger.info("AccountWSManager shut down")

    async def start_account(self, account_id: str) -> None:
        """Start WebSocket connection for a single account."""
        async with self._lock:
            await self._start_account(account_id)

    async def stop_account(self, account_id: str) -> None:
        """Stop and remove WebSocket connection for a single account."""
        async with self._lock:
            client = self._clients.pop(account_id, None)
            if client:
                await client.stop()
                logger.info("Stopped WS for account %s", account_id)

    async def _start_account(self, account_id: str) -> None:
        if account_id in self._clients:
            return
        creds = await self._db.get_account_credentials(account_id)
        if not creds:
            return
        try:
            def _decrypt():
                return decrypt_value(creds["api_key_encrypted"]), decrypt_value(creds["api_secret_encrypted"])
            api_key, api_secret = await asyncio.to_thread(_decrypt)
        except Exception as e:
            logger.error("Cannot decrypt credentials for account %s: %s", account_id, type(e).__name__)
            return

        async def on_event(event: dict[str, Any]) -> None:
            """Tag a WS event with its account_id, broadcast it, and notify wallet listeners."""
            event["account_id"] = account_id
            await self._broadcast(event)
            event_type = event.get("type")
            if event_type in ("wallet_update", "position_update") and self._wallet_listeners:
                await self._notify_wallet_listeners(account_id, event)

        async def on_reconnect() -> None:
            """After WS reconnects, fetch current wallet state to catch up on missed events."""
            if not self._accounts_service:
                return
            try:
                wallet = await self._accounts_service.get_wallet(account_id)
                synthetic_event = {
                    "type": "wallet_update",
                    "account_id": account_id,
                    "data": wallet,
                    "_reconnect_sync": True,
                }
                if self._wallet_listeners:
                    await self._notify_wallet_listeners(account_id, synthetic_event)
                logger.debug("WS reconnect: synced wallet for %s", account_id)
            except Exception:
                logger.debug("WS reconnect: wallet sync failed for %s", account_id)

        client = BybitWSClient(api_key, api_secret, creds["account_type"], on_event, account_id=account_id, on_reconnect=on_reconnect)
        try:
            await client.start()
        except Exception:
            logger.exception("Failed to start WS for account %s", account_id)
            return
        self._clients[account_id] = client
        logger.info("Started WS for account %s", account_id)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self._frontend_queues):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time account events; returns a queue to consume from."""
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._frontend_queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe a previously subscribed queue."""
        self._frontend_queues.discard(q)

    def register_wallet_listener(self, callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """Register a coroutine callback for wallet/position events."""
        self._wallet_listeners.append(callback)

    def deregister_wallet_listener(self, callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """Remove a previously registered wallet listener."""
        try:
            self._wallet_listeners.remove(callback)
        except ValueError:
            pass

    async def _notify_wallet_listeners(self, account_id: str, wallet_data: dict[str, Any]) -> None:
        # Bound in-flight listener tasks: a WS storm could otherwise spawn
        # unbounded tasks. Wallet frames are snapshots, so dropping a frame when
        # the backlog is large is safe — the next frame supersedes it.
        if len(self._background_tasks) > _MAX_INFLIGHT_WALLET_TASKS:
            logger.warning(
                "wallet-listener backlog %d > %d for account %s; dropping frame",
                len(self._background_tasks), _MAX_INFLIGHT_WALLET_TASKS, account_id,
            )
            return
        for listener in self._wallet_listeners:
            try:
                task = asyncio.create_task(self._run_wallet_listener(listener, account_id, wallet_data))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except Exception:
                logger.exception("Failed to schedule wallet listener for account %s", account_id)

    async def _run_wallet_listener(self, listener: Any, account_id: str, wallet_data: dict[str, Any]) -> None:
        try:
            await listener(account_id, wallet_data)
        except Exception:
            logger.exception("Wallet listener failed for account %s", account_id)

    async def broadcast_event(self, event: dict[str, Any]) -> None:
        """Broadcast a pre-built event dict to all connected WebSocket clients."""
        await self._broadcast(event)

    async def broadcast_to_account(self, account_id: str, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event of the given type for a specific account to all clients."""
        await self._broadcast({"type": event_type, "account_id": account_id, **payload})
