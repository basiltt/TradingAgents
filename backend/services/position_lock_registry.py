"""Position Lock Registry — Phase 2 Task 2.1.

Shared per-position lock between AIManager and CloseRuleEvaluator.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class PositionLockRegistry:
    def __init__(self):
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._last_used: Dict[Tuple[str, str], float] = {}
        self._internal_lock = asyncio.Lock()

    async def acquire(self, account_id: str, symbol: str, timeout: float = 30.0) -> bool:
        key = (account_id, symbol)
        async with self._internal_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            self._last_used[key] = time.monotonic()
            return True
        except asyncio.TimeoutError:
            logger.warning("Lock timeout: account=%s symbol=%s", account_id, symbol)
            return False

    def release(self, account_id: str, symbol: str) -> None:
        key = (account_id, symbol)
        lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()
            self._last_used[key] = time.monotonic()

    async def cleanup_account(self, account_id: str, force: bool = False) -> None:
        async with self._internal_lock:
            keys_to_remove = [k for k in self._locks if k[0] == account_id]
            for key in keys_to_remove:
                lock = self._locks[key]
                if lock.locked() and force:
                    lock.release()
                if not lock.locked():
                    del self._locks[key]
                    self._last_used.pop(key, None)

    async def evict_stale(self, max_idle_s: float = 300.0) -> None:
        now = time.monotonic()
        async with self._internal_lock:
            keys_to_remove = []
            for key, last in self._last_used.items():
                if now - last > max_idle_s:
                    lock = self._locks.get(key)
                    if lock and not lock.locked():
                        keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._locks[key]
                del self._last_used[key]
