"""Sealed-day manifest + completion frontier (Phase P1).

Root cause RC-3: `get_coverage_gaps` re-evaluates `candle_count < expected` on
EVERY run. A closed day that legitimately has fewer candles than the formula
expects (low-volume symbol, listing day, exchange downtime) is flagged as a gap
*forever* and re-fetched from Bybit on every rerun — the headline "re-downloads
klines every time" complaint.

The fix is an immutability rule, not a better count heuristic:

  * A candle is CLOSED (immutable) once its interval has fully elapsed. The
    *completion frontier* is the last fully-closed bar boundary:
        frontier = floor(now / T) * T          (T = interval seconds)
    Any day whose end (00:00 next day) is at/below the frontier contains only
    closed candles — it can never gain or change a candle.

  * Once such a day has been fetched and stored, it is SEALED: its candle_count
    becomes a recorded FACT, never again a refetch trigger. A sealed day with
    144/288 candles is COMPLETE (the exchange simply had 144 bars that day), not
    a perpetual gap.

  * Only days NOT yet sealed — the forming (current) day, or days never fetched —
    are eligible for a fetch. This makes a closed day fetched exactly once, ever.

This module is pure (no DB, no network) so it is fully unit-testable headless
(N3). The DB wiring lives in KlineCacheService; the persistence schema is the
v58 `sealed`/`sealed_at` columns on kline_cache_coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

# Interval → seconds. Mirrors the kline_cache_service interval map.
_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}


def interval_seconds(interval: str) -> int:
    """Seconds per bar for an interval; defaults to 5m (300) for unknown."""
    return _INTERVAL_SECONDS.get(interval, 300)


def completion_frontier(now: datetime, interval: str) -> datetime:
    """The last fully-closed bar boundary at `now`: floor(now/T)*T.

    Every candle with open_time < frontier is closed (immutable). `now` MUST be
    timezone-aware UTC; callers pass datetime.now(timezone.utc). Passed in (never
    read from a clock here) so the logic is deterministic + unit-testable.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    T = interval_seconds(interval)
    epoch = int(now.timestamp())
    floored = (epoch // T) * T
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def day_is_closed(d: date, frontier: datetime) -> bool:
    """True when day `d` is entirely below the completion frontier (all candles
    closed). A day is closed iff its END (00:00 of the next day) <= frontier."""
    day_end = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
    return day_end <= frontier


@dataclass(frozen=True)
class DayClass:
    """Classification of a (symbol, interval, day) cell for the refetch decision."""
    date: date
    sealed: bool          # recorded immutable — never refetch
    closed: bool          # below the completion frontier (eligible to seal)
    cached_count: int     # candles currently stored (0 = never fetched)

    @property
    def needs_fetch(self) -> bool:
        """A day needs fetching iff it is NOT sealed AND (forming OR never cached).

        - sealed  → NEVER (the whole point; count is a fact, not a gate).
        - closed but not sealed and never cached → fetch once, then seal.
        - closed but not sealed and already cached → fetch once to seal (lazy seal
          of pre-existing rows from before the manifest existed), then seal.
        - forming (not closed) → always eligible (the current day still grows).
        """
        if self.sealed:
            return False
        if not self.closed:
            return True  # forming day — keep refreshing until it closes + seals
        return True       # closed, unsealed → fetch once to seal it


def classify_days(
    *,
    expected_dates: Iterable[date],
    sealed_dates: set[date],
    cached_counts: dict[date, int],
    frontier: datetime,
) -> list[DayClass]:
    """Classify each expected day for the refetch decision.

    Args:
        expected_dates: the days in the requested window.
        sealed_dates: days already marked sealed in the manifest.
        cached_counts: date → stored candle_count (absent = 0).
        frontier: completion frontier (from completion_frontier()).
    """
    out: list[DayClass] = []
    for d in expected_dates:
        out.append(DayClass(
            date=d,
            sealed=d in sealed_dates,
            closed=day_is_closed(d, frontier),
            cached_count=cached_counts.get(d, 0),
        ))
    return out


def days_needing_fetch(classes: Iterable[DayClass]) -> list[date]:
    """The subset of days that still require an exchange fetch."""
    return [c.date for c in classes if c.needs_fetch]


def days_to_seal(classes: Iterable[DayClass]) -> list[date]:
    """Closed, not-yet-sealed days that now HAVE cached candles — ready to seal.

    Called AFTER a fetch+store pass: any closed day with candles can be sealed so
    it is never re-evaluated. A closed day with 0 candles after a real fetch
    attempt is a genuine no-data day (pre-listing / delisted / full-day gap) — it
    is sealed too (negative seal) so we don't re-fetch nothing forever.
    """
    return [c.date for c in classes if c.closed and not c.sealed]


def contiguous_runs(days: list[date]) -> list[tuple[date, date]]:
    """Collapse a sorted day list into contiguous [lo, hi] runs.

    Fetching per contiguous run (instead of one min→max bracket spanning isolated
    gaps) avoids re-pulling already-cached interior days — RC-3's "one stale day
    drags the whole history" amplifier.
    """
    if not days:
        return []
    s = sorted(set(days))
    runs: list[tuple[date, date]] = []
    run_lo = run_hi = s[0]
    for d in s[1:]:
        if d == run_hi + timedelta(days=1):
            run_hi = d
        else:
            runs.append((run_lo, run_hi))
            run_lo = run_hi = d
    runs.append((run_lo, run_hi))
    return runs


def ratchet_frontier(prev: Optional[datetime], computed: datetime) -> datetime:
    """Monotonic frontier: never let a backward wall-clock step reopen sealed days.

    AC-009a — if the system clock steps backward, `computed` could regress and
    un-close a day. Clamp to max(prev, computed) so the frontier only advances.
    """
    if prev is None:
        return computed
    return max(prev, computed)
