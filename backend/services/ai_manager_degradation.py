"""Degradation Tier Manager — Phase 2 Task 2.8."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class DegradationTierManager:
    """4 tiers: Nominal(0) → Degraded(1) → Conservative(2) → Safe(3).
    Global scope. All state mutations guarded by asyncio.Lock."""

    HYSTERESIS_S = 300.0  # 5 min sustained health to recover

    def __init__(self, repo=None):
        self._tier: int = 0
        self._lock = asyncio.Lock()
        self._repo = repo
        self._health_streak_start: float = 0.0
        self._last_failure_at: float = 0.0

    async def load_from_db(self) -> None:
        if self._repo:
            self._tier = await self._repo.get_degradation_tier()

    async def check_health(self, event: str) -> None:
        """Process a health event and adjust the degradation tier.

        Valid events: 'success', 'indeterminate', 'timeout', 'unavailable', 'exchange_down'.
        Escalation is immediate; recovery requires HYSTERESIS_S seconds of sustained success.
        """
        async with self._lock:
            now = time.monotonic()
            if event in ("success", "indeterminate"):
                if self._tier == 0:
                    return
                if self._health_streak_start == 0:
                    self._health_streak_start = now
                elif now - self._health_streak_start >= self.HYSTERESIS_S:
                    self._tier = max(0, self._tier - 1)
                    self._health_streak_start = 0.0
                    logger.info("Degradation tier recovered to %d", self._tier)
                    if self._repo:
                        await self._repo.set_degradation_tier(self._tier)
            elif event == "timeout":
                self._health_streak_start = 0.0
                self._last_failure_at = now
                if self._tier < 1:
                    self._tier = 1
                    logger.warning("Degradation tier escalated to 1 (LLM timeout)")
                    if self._repo:
                        await self._repo.set_degradation_tier(self._tier)
            elif event == "unavailable":
                self._health_streak_start = 0.0
                self._last_failure_at = now
                if self._tier < 2:
                    self._tier = 2
                    logger.warning("Degradation tier escalated to 2 (LLM unavailable)")
                    if self._repo:
                        await self._repo.set_degradation_tier(self._tier)
            elif event == "exchange_down":
                self._health_streak_start = 0.0
                self._last_failure_at = now
                if self._tier < 3:
                    self._tier = 3
                    logger.warning("Degradation tier escalated to 3 (exchange down)")
                    if self._repo:
                        await self._repo.set_degradation_tier(self._tier)

    def get_tier(self) -> int:
        return self._tier

    def should_use_llm(self, tier: int = None) -> bool:
        t = tier if tier is not None else self._tier
        return t < 2
