"""Injectable clock — TASK seam for testable time (TTL/idle/timeouts)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """Test clock with controllable virtual time."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)
