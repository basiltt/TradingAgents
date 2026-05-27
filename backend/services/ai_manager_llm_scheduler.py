"""Priority LLM Scheduler — Phase 2 Task 2.2."""

from __future__ import annotations

import asyncio
import itertools
import logging
from contextlib import asynccontextmanager
from typing import Dict

logger = logging.getLogger(__name__)


class PriorityLLMScheduler:
    """3 FAST reserved + 7 shared STANDARD/DEEP slots."""

    _counter = itertools.count()

    def __init__(self):
        self._fast_sem = asyncio.Semaphore(3)
        self._general_sem = asyncio.Semaphore(7)
        self._account_inflight: Dict[str, int] = {}
        self._account_queued: Dict[str, int] = {}
        self._deep_active: int = 0
        self._tokens: Dict[str, str] = {}

    _BURST_TIMEOUT_S = 5.0

    def _make_token_key(self, account_id: str) -> str:
        return f"{account_id}:{next(self._counter)}"

    async def acquire(self, account_id: str, urgency: str) -> bool:
        inflight = self._account_inflight.get(account_id, 0)
        queued = self._account_queued.get(account_id, 0)
        if inflight + queued >= 2:
            return False

        token_key = self._make_token_key(account_id)

        if urgency == "FAST":
            self._account_inflight[account_id] = inflight + 1
            try:
                await asyncio.wait_for(self._fast_sem.acquire(), timeout=0.01)
            except asyncio.TimeoutError:
                self._account_inflight[account_id] = max(0, self._account_inflight.get(account_id, 1) - 1)
                return False
            except BaseException:
                self._account_inflight[account_id] = max(0, self._account_inflight.get(account_id, 1) - 1)
                raise
            self._tokens[token_key] = "FAST"
            return True
        else:
            effective = urgency
            if urgency == "DEEP" and self._deep_active >= 2:
                effective = "STANDARD"

            if effective == "DEEP":
                self._deep_active += 1

            self._account_queued[account_id] = queued + 1
            try:
                await asyncio.wait_for(self._general_sem.acquire(), timeout=self._BURST_TIMEOUT_S)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                self._account_queued[account_id] = max(0, self._account_queued.get(account_id, 1) - 1)
                if effective == "DEEP":
                    self._deep_active = max(0, self._deep_active - 1)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return False

            self._account_queued[account_id] = max(0, self._account_queued.get(account_id, 1) - 1)
            self._account_inflight[account_id] = self._account_inflight.get(account_id, 0) + 1
            self._tokens[token_key] = effective
            return True

    def release(self, account_id: str, urgency: str) -> None:
        token_key = None
        prefix = f"{account_id}:"
        for k in list(self._tokens):
            if k.startswith(prefix):
                token_key = k
                break
        if token_key is None:
            logger.warning("Double-release prevented for %s urgency=%s", account_id, urgency)
            return
        effective = self._tokens.pop(token_key)

        inflight = self._account_inflight.get(account_id, 0)
        if inflight > 0:
            self._account_inflight[account_id] = inflight - 1

        if effective == "FAST":
            self._fast_sem.release()
        else:
            self._general_sem.release()
            if effective == "DEEP":
                self._deep_active = max(0, self._deep_active - 1)

    @asynccontextmanager
    async def slot(self, account_id: str, urgency: str):
        acquired = await self.acquire(account_id, urgency)
        if not acquired:
            raise RuntimeError(f"LLM slot not available for {account_id} urgency={urgency}")
        try:
            yield
        finally:
            self.release(account_id, urgency)
