"""Live-SLI breaker tests — G2-4 (FR-037 breaker, NFR-002 protection).

The breaker suspends MCP/sweep work when live trading SLIs degrade (event-loop
lag, reconciler cycle, order-placement p95, pool-wait), with hysteresis so it
doesn't flap. Fail-closed: if SLIs are absent it stays OPEN (MCP suspended).
Pure state machine — deterministic, no clock dependency (caller passes samples).
"""
from __future__ import annotations

from backend.mcp.core.breaker import BreakerState, LiveSLIBreaker


def test_breaker_starts_closed_when_slis_healthy():
    b = LiveSLIBreaker(trip_threshold=2, reset_threshold=2)
    # healthy samples keep it CLOSED (MCP permitted)
    for _ in range(3):
        b.observe(healthy=True)
    assert b.state is BreakerState.CLOSED
    assert b.mcp_permitted() is True


def test_breaker_trips_after_consecutive_unhealthy():
    b = LiveSLIBreaker(trip_threshold=2, reset_threshold=2)
    b.observe(healthy=False)
    assert b.state is BreakerState.CLOSED  # one bad sample not enough (hysteresis)
    b.observe(healthy=False)
    assert b.state is BreakerState.OPEN
    assert b.mcp_permitted() is False


def test_breaker_resets_after_consecutive_healthy():
    b = LiveSLIBreaker(trip_threshold=1, reset_threshold=2)
    b.observe(healthy=False)
    assert b.state is BreakerState.OPEN
    b.observe(healthy=True)
    assert b.state is BreakerState.OPEN  # one good sample not enough to reset
    b.observe(healthy=True)
    assert b.state is BreakerState.CLOSED


def test_breaker_fail_closed_when_slis_absent():
    b = LiveSLIBreaker(trip_threshold=2, reset_threshold=2)
    # absent SLIs (None) → treated as unhealthy, trips fail-closed
    b.observe(healthy=None)
    b.observe(healthy=None)
    assert b.state is BreakerState.OPEN
    assert b.mcp_permitted() is False


def test_breaker_evaluate_from_metrics():
    b = LiveSLIBreaker(trip_threshold=1, reset_threshold=1)
    # a sample where order p95 exceeds the bound is unhealthy
    b.observe_metrics({"order_p95_ms": 999.0, "loop_lag_ms": 5.0},
                      bounds={"order_p95_ms": 200.0, "loop_lag_ms": 100.0})
    assert b.state is BreakerState.OPEN
    # a healthy sample resets (reset_threshold=1)
    b.observe_metrics({"order_p95_ms": 50.0, "loop_lag_ms": 5.0},
                      bounds={"order_p95_ms": 200.0, "loop_lag_ms": 100.0})
    assert b.state is BreakerState.CLOSED


def test_breaker_ignores_absent_optional_metrics():
    """Regression: the bounds dict enumerates every SLI the breaker COULD use,
    but the always-on poller only supplies the instrumented ones (loop_lag_ms).
    A PRESENT-and-within-bound metric must count as healthy even when other
    bounded metrics are absent — otherwise the breaker pins OPEN forever and
    sheds every sweep (the original 'live-SLI breaker stayed open' failure)."""
    b = LiveSLIBreaker(trip_threshold=1, reset_threshold=1)
    bounds = {
        "loop_lag_ms": 250.0,
        "order_p95_ms": 500.0,          # never supplied by the always-on poller
        "reconciler_cycle_ms": 2000.0,  # never supplied
        "pool_wait_ms": 500.0,          # never supplied
    }
    # only loop_lag is measured, and it's healthy → breaker must be CLOSED
    for _ in range(3):
        b.observe_metrics({"loop_lag_ms": 5.0}, bounds=bounds)
    assert b.state is BreakerState.CLOSED
    assert b.mcp_permitted() is True


def test_breaker_trips_when_present_metric_breaches_despite_absent_others():
    """A present metric over its bound still trips, even if the other bounded
    metrics are absent (the absent ones are ignored, the present breach is not)."""
    b = LiveSLIBreaker(trip_threshold=1, reset_threshold=1)
    bounds = {"loop_lag_ms": 250.0, "order_p95_ms": 500.0}
    b.observe_metrics({"loop_lag_ms": 9999.0}, bounds=bounds)  # loop starved
    assert b.state is BreakerState.OPEN
    assert b.mcp_permitted() is False


def test_breaker_fail_closed_when_no_bounded_metric_present():
    """Fail-closed is preserved: a sample with NONE of the bounded metrics (only
    junk keys) is treated as no-signal → unhealthy."""
    b = LiveSLIBreaker(trip_threshold=1, reset_threshold=1)
    bounds = {"loop_lag_ms": 250.0}
    b.observe_metrics({"unrelated_key": 1.0}, bounds=bounds)
    assert b.state is BreakerState.OPEN
