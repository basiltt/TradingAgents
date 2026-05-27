"""AI Manager Circuit Breaker — Phase 2 Task 2.6."""

from __future__ import annotations

import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class AIManagerCircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: int = 3600, repo=None):
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._repo = repo
        self._counts: Dict[str, int] = {}
        self._active: Dict[str, bool] = {}
        self._tripped_at: Dict[str, float] = {}

    async def load_from_db(self, account_id: str, count: int, active: bool) -> None:
        self._counts[account_id] = count
        self._active[account_id] = active
        if active:
            self._tripped_at.setdefault(account_id, time.monotonic())

    async def record_outcome(
        self, account_id: str, realized_pnl: float, action_type: str
    ) -> None:
        if action_type not in ("FULL_CLOSE", "PARTIAL_CLOSE"):
            return
        if realized_pnl >= 0:
            if self._active.get(account_id):
                await self.reset(account_id)
            else:
                self._counts[account_id] = 0
                if self._repo:
                    await self._repo.upsert_state(
                        account_id, circuit_breaker_count=0
                    )
            return

        count = self._counts.get(account_id, 0) + 1
        self._counts[account_id] = count

        if count >= self._threshold:
            if not self._active.get(account_id):
                self._active[account_id] = True
                self._tripped_at[account_id] = time.monotonic()
                logger.warning("Circuit breaker OPEN: account=%s count=%d", account_id, count)

        if self._repo:
            fields = {
                "circuit_breaker_count": count,
                "circuit_breaker_active": self._active.get(account_id, False),
            }
            if count == self._threshold:
                fields["circuit_breaker_half_open_used"] = False
            await self._repo.upsert_state(account_id, **fields)

    def is_tripped(self, account_id: str) -> bool:
        return self._active.get(account_id, False)

    async def check_cooldown(self, account_id: str) -> bool:
        if not self._active.get(account_id):
            return False
        tripped_at = self._tripped_at.get(account_id, 0)
        if time.monotonic() - tripped_at < self._cooldown_s:
            return False
        # Cooldown elapsed — attempt HALF_OPEN via atomic DB CAS
        if self._repo:
            async with self._repo._pool.acquire() as conn:
                result = await conn.fetchrow(
                    "UPDATE ai_manager_state "
                    "SET circuit_breaker_half_open_used = TRUE "
                    "WHERE account_id = $1 AND circuit_breaker_active = TRUE "
                    "  AND circuit_breaker_half_open_used = FALSE "
                    "RETURNING account_id",
                    account_id,
                )
                return result is not None
        return True

    def restart_cooldown(self, account_id: str) -> None:
        self._tripped_at[account_id] = time.monotonic()

    async def reset(self, account_id: str) -> None:
        self._counts[account_id] = 0
        self._active[account_id] = False
        self._tripped_at.pop(account_id, None)
        if self._repo:
            await self._repo.upsert_state(
                account_id,
                circuit_breaker_count=0,
                circuit_breaker_active=False,
                circuit_breaker_half_open_used=False,
            )
