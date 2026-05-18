"""Shared per-account rate limiter for API routers."""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class _TokenBucket:
    """Token-bucket rate limiter with configurable rate (tokens/sec) and burst capacity."""

    def __init__(self, rate: float = 10.0, capacity: float = 10.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token. Returns True if allowed, False if exhausted."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


_rate_limiters: dict[str, _TokenBucket] = {}
_RATE_LIMITER_MAX_ENTRIES = 1000
_RATE_LIMITER_STALE_SECONDS = 3600


async def check_rate_limit(account_id: str) -> None:
    """Enforce per-account rate limiting; raises HTTPException(429) when exhausted."""
    now = time.monotonic()
    if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
        stale = [k for k, v in _rate_limiters.items() if now - v.last_refill > _RATE_LIMITER_STALE_SECONDS]
        for k in stale:
            del _rate_limiters[k]
    if account_id not in _rate_limiters:
        if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
            logger.warning("rate_limiter_capacity_exceeded")
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _rate_limiters[account_id] = _TokenBucket()
    if not _rate_limiters[account_id].consume():
        logger.warning("rate_limit_hit", extra={"account_id": account_id})
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
