"""Manages Bybit WebSocket connections for all active trading accounts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Set

from backend.crypto import decrypt_value
from backend.async_persistence import AsyncAnalysisDB
from backend.services.bybit_ws_client import BybitWSClient

logger = logging.getLogger(__name__)


class AccountWSManager:
    """Orchestrates one BybitWSClient per active account, broadcasting events to connected frontends."""

    def __init__(self, db: AsyncAnalysisDB):
        self._db = db
        self._clients: Dict[str, BybitWSClient] = {}
        self._frontend_queues: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            accounts = await self._db.list_accounts()
            for acc in accounts:
                if acc["is_active"]:
                    await self._start_account(acc["id"])
        logger.info("AccountWSManager started for %d accounts", len(self._clients))

    async def shutdown(self) -> None:
        async with self._lock:
            if self._clients:
                await asyncio.gather(
                    *(client.stop() for client in self._clients.values()),
                    return_exceptions=True,
                )
            self._clients.clear()
        logger.info("AccountWSManager shut down")

    async def start_account(self, account_id: str) -> None:
        async with self._lock:
            await self._start_account(account_id)

    async def stop_account(self, account_id: str) -> None:
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
            event["account_id"] = account_id
            await self._broadcast(event)

        client = BybitWSClient(api_key, api_secret, creds["account_type"], on_event, account_id=account_id)
        self._clients[account_id] = client
        await client.start()
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
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._frontend_queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._frontend_queues.discard(q)

    async def broadcast_event(self, event: dict[str, Any]) -> None:
        await self._broadcast(event)

    async def broadcast_to_account(self, account_id: str, event_type: str, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": event_type, "account_id": account_id, **payload})
