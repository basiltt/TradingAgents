"""Live-SLI circuit breaker — G2-4 (FR-037, NFR-002), pure + trading-free (core).

When live-trading SLIs degrade under an MCP sweep (event-loop lag, reconciler
cycle time, order-placement p95, pool-wait), the breaker trips OPEN and MCP/sweep
work is suspended until the SLIs recover. Hysteresis (consecutive-sample
thresholds) prevents flapping. Fail-closed: an absent SLI sample counts as
unhealthy, so a missing live-signal source keeps MCP suspended rather than
risking the trading loop.

Pure state machine: the caller feeds samples (no clock, no I/O here), so it is
deterministic and core-import-clean. The composition layer polls real SLIs and
calls observe()/observe_metrics() on a cadence; mount checks mcp_permitted()
before admitting sweep work.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class BreakerState(str, Enum):
    CLOSED = "closed"  # healthy — MCP permitted
    OPEN = "open"      # tripped — MCP suspended


class LiveSLIBreaker:
    def __init__(self, *, trip_threshold: int = 3, reset_threshold: int = 5) -> None:
        """trip_threshold consecutive unhealthy samples → OPEN; reset_threshold
        consecutive healthy samples → CLOSED."""
        self.state = BreakerState.CLOSED
        self._trip_threshold = max(1, trip_threshold)
        self._reset_threshold = max(1, reset_threshold)
        self._bad_run = 0
        self._good_run = 0

    def observe(self, *, healthy: Optional[bool]) -> BreakerState:
        """Feed one health sample. `None` (SLIs absent) counts as unhealthy
        (fail-closed). Returns the resulting state."""
        is_healthy = healthy is True  # None or False → unhealthy
        if is_healthy:
            self._good_run += 1
            self._bad_run = 0
            if self.state is BreakerState.OPEN and self._good_run >= self._reset_threshold:
                self.state = BreakerState.CLOSED
                self._good_run = 0
        else:
            self._bad_run += 1
            self._good_run = 0
            if self.state is BreakerState.CLOSED and self._bad_run >= self._trip_threshold:
                self.state = BreakerState.OPEN
                self._bad_run = 0
        return self.state

    def observe_metrics(
        self, metrics: Optional[dict[str, Any]], *, bounds: dict[str, float]
    ) -> BreakerState:
        """Derive health from a metrics sample: healthy iff every bounded metric
        that is PRESENT is within its bound, and at least one bounded metric is
        present.

        A missing OPTIONAL metric is ignored, not counted as a breach: the bounds
        dict enumerates every SLI the breaker COULD use, but the always-on poller
        only supplies the ones actually instrumented (e.g. loop_lag_ms). Treating
        an absent metric as unhealthy would pin the breaker permanently OPEN and
        shed every sweep — contradicting the documented design ("loop_lag is
        enough; the others augment but are not required"). Fail-closed is still
        honored for a genuinely empty sample (no signal at all → unhealthy) via
        the `present` guard below."""
        if not metrics:
            return self.observe(healthy=None)
        present = 0
        for key, bound in bounds.items():
            v = metrics.get(key)
            if v is None:
                continue  # optional/uninstrumented SLI — ignore, don't penalize
            present += 1
            if float(v) > float(bound):
                return self.observe(healthy=False)
        # No bounded metric present at all → no real signal → fail-closed.
        if present == 0:
            return self.observe(healthy=None)
        return self.observe(healthy=True)

    def mcp_permitted(self) -> bool:
        """True iff MCP/sweep work may run right now."""
        return self.state is BreakerState.CLOSED
