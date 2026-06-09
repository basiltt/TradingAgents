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
    """Per-position mutex registry preventing concurrent modifications.

    Ensures that AI Manager and CloseRuleEvaluator never simultaneously close
    the same position. Locks are keyed by (account_id, symbol) and auto-cleaned
    after inactivity.
    """

    def __init__(self):
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._last_used: Dict[Tuple[str, str], float] = {}
        self._internal_lock = asyncio.Lock()

    async def acquire(self, account_id: str, symbol: str, timeout: float = 30.0) -> bool:
        """Acquire the (account_id, symbol) lock, waiting up to timeout; False on timeout."""
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
        """Release the (account_id, symbol) lock if currently held."""
        key = (account_id, symbol)
        lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()
            self._last_used[key] = time.monotonic()

    async def cleanup_account(self, account_id: str, force: bool = False) -> None:
        """Remove this account's UNHELD position locks.

        IMPORTANT (money-safety): a held lock is NEVER force-released here. asyncio
        locks have no owner, so releasing a lock held by ANOTHER coroutine (e.g. the
        AutoTradeExecutor mid-placement, or the CloseRuleEvaluator) silently breaks
        mutual exclusion — two coroutines would then believe they hold the same
        (account, symbol) mutex and could double-place/double-close. The lock's real
        holder releases it in its own ``finally``; we only reap entries that are
        currently free. The ``force`` flag is retained for API compatibility but no
        longer force-releases — a stale-but-held entry is left for ``evict_stale`` /
        the holder to clean up. To reclaim a lock held by a task being torn down,
        cancel AND await that task first so its ``finally`` runs before cleanup.
        """
        async with self._internal_lock:
            keys_to_remove = [k for k in self._locks if k[0] == account_id]
            for key in keys_to_remove:
                lock = self._locks[key]
                if not lock.locked():
                    del self._locks[key]
                    self._last_used.pop(key, None)
                elif force:
                    # Held by someone else — do NOT release. Log so a leaked/stuck
                    # lock is observable rather than silently corrupted.
                    logger.warning(
                        "cleanup_account: lock still held, leaving for holder/evict_stale: %s",
                        key,
                    )

    async def evict_stale(self, max_idle_s: float = 300.0) -> None:
        """Remove unheld locks idle for longer than max_idle_s to bound memory growth."""
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
