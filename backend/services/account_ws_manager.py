"""Manages per-account Bybit WebSocket connections and broadcasts to frontend clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.crypto import decrypt_value
from backend.persistence import AnalysisDB
from backend.services.bybit_ws_client import BybitWSClient

logger = logging.getLogger(__name__)

_MAX_FRONTEND_CONNECTIONS = 20


class AccountWSManager:
    """Orchestrates one BybitWSClient per active account, fan-out to frontend queues."""

    def __init__(self, db: AnalysisDB):
        self._db = db
        self._clients: dict[str, BybitWSClient] = {}
        self._frontend_queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        accounts = self._db.list_accounts()
        for acc in accounts:
            if acc.get("is_active", True):
                try:
                    await self.start_account(acc["id"])
                except Exception as e:
                    logger.error(f"Failed to start WS for account {acc['id'][:8]}: {e}")

    async def shutdown(self) -> None:
        for client in list(self._clients.values()):
            await client.stop()
        self._clients.clear()

    async def start_account(self, account_id: str) -> None:
        async with self._lock:
            if account_id in self._clients:
                return
            creds = self._db.get_account_credentials(account_id)
            if not creds:
                logger.warning(f"Cannot start WS for account {account_id}: no credentials")
                return
            api_key = decrypt_value(creds["api_key_encrypted"])
            api_secret = decrypt_value(creds["api_secret_encrypted"])
            account_type = creds.get("account_type", "demo")

            client = BybitWSClient(
                account_id=account_id,
                api_key=api_key,
                api_secret=api_secret,
                account_type=account_type,
                on_event=self._on_event,
            )
            self._clients[account_id] = client
            await client.start()
            logger.info(f"Started Bybit WS for account {account_id[:8]}")

    async def stop_account(self, account_id: str) -> None:
        async with self._lock:
            client = self._clients.pop(account_id, None)
            if client:
                await client.stop()
                logger.info(f"Stopped Bybit WS for account {account_id[:8]}")

    def subscribe(self) -> asyncio.Queue | None:
        if len(self._frontend_queues) >= _MAX_FRONTEND_CONNECTIONS:
            return None
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._frontend_queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._frontend_queues.discard(queue)

    async def _on_event(self, account_id: str, event_type: str, data: dict[str, Any]) -> None:
        msg = {"account_id": account_id, "type": event_type, "data": data}
        for q in list(self._frontend_queues):
            if q.full():
                # Drain oldest to make room rather than killing the subscription
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
