"""Phase 3 speedup benchmark + zero-10006 proof (TASK-3.6, NFR-001/002, R196).

These tests are the quantitative half of the Definition-of-Done gate that governs
flipping account-concurrency width>1 in production. Using the deterministic recording
harness (TASK-2.1) with injected per-call latency, they assert:

  1. SPEEDUP: the full post-scan tail's wall-clock is STRICTLY LESS at width=2 than at
     width=1 for the SAME account count N (RTT-overlap / latency-hiding, the real win
     per NFR-002), at N = 5, 10, 20 -- backed by a DETERMINISTIC structural proof
     (observed max-concurrency) so the gate never rests on a bare wall-clock compare.
  2. PLATEAU: the speedup ratio is bounded ABOVE by the concurrency width (you can
     overlap at most `width` accounts' RTTs) and grows toward it as N rises -- the
     signature of latency-hiding, NOT linear-in-N throughput.
  3. ZERO 10006 + NEGATIVE CONTROL: a GLOBAL (IP-level) rate-aware throttle never trips
     when the process-wide semaphore bounds global in-flight at the width; and a
     deliberately-too-low bound MUST trip (falsifiability -- the zero-10006 proof is not
     vacuous).

Determinism: latency is a fixed asyncio.sleep (no wall-clock reads in the logic); the
structural assertions (max_concurrency, throttle.tripped) are exact. time.perf_counter
is used only to measure elapsed for the corroborating wall-clock check (with a 10%
margin well inside the ~50% structural gap), never for control flow.
"""

from __future__ import annotations

import time

import pytest

from backend.services import post_scan_concurrency as psc
from backend.services import post_scan_flags
from backend.services.auto_trade_service import AutoTradeExecutor
from tests.backend.post_scan_harness import (
    RateAwareThrottle,
    RecordingAccountsService,
    RecordingCloseService,
)


@pytest.fixture(autouse=True)
def _reset_state():
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()
    yield
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()


def _cfg(account_id):
    return {
        "account_id": account_id, "execution_mode": "batch", "max_trades": 3,
        "min_score": 0, "signal_sides": "both", "leverage": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "capital_pct": 10,
        "direction": "straight", "confidence_filter": "any",
    }


def _results(n):
    return [
        {"id": f"r{i}", "ticker": f"S{i}", "status": "completed", "direction": "sell",
         "score": -(10 - (i % 10)), "confidence": "high"}
        for i in range(n)
    ]


async def _measure_tail(n_accounts: int, width: int, *, latency: float, throttle=None):
    """Run the full tail for N accounts at a given width; return (elapsed_s, accounts)."""
    psc.configure_account_concurrency(width)
    accounts = RecordingAccountsService(latency=latency, throttle=throttle)
    close = RecordingCloseService()
    ex = AutoTradeExecutor(accounts, close, scan_id=f"bench-{n_accounts}-{width}")
    ex.init_configs([_cfg(f"acc{i}") for i in range(n_accounts)])
    for st in ex._state.values():
        st.base_capital = 1000.0
    results = _results(3)  # 3 symbols => 3 placements per account (max_trades=3)
    t0 = time.perf_counter()
    await ex.run_post_scan_tail(results)
    elapsed = time.perf_counter() - t0
    return elapsed, accounts


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [5, 10, 20])
async def test_parallel_faster_than_sequential_same_n(n):
    latency = 0.01
    seq_elapsed, seq_acc = await _measure_tail(n, width=1, latency=latency)
    par_elapsed, par_acc = await _measure_tail(n, width=2, latency=latency)
    # STRUCTURAL proof (deterministic, never flaky): width=2 genuinely overlapped 2
    # accounts; width=1 was strictly serial. This is the primary assertion.
    assert par_acc.max_concurrency == 2, "width=2 did not actually parallelize"
    assert seq_acc.max_concurrency == 1, "width=1 was not strictly serial"
    # Wall-clock CORROBORATION with a 10% margin (the structural gap is ~50%, so this
    # stays well inside scheduler noise and won't flake on a loaded CI box).
    assert par_elapsed < seq_elapsed * 0.9, (
        f"N={n}: parallel {par_elapsed:.3f}s not < 0.9 * sequential {seq_elapsed:.3f}s"
    )


@pytest.mark.asyncio
async def test_zero_10006_under_concurrency_bound():
    # GLOBAL (IP-level) throttle: trips if more than `width` placements are in flight
    # across ALL accounts at once. At width=2 the process-wide semaphore caps global
    # in-flight at 2, so a threshold of 2 is never exceeded -> zero trips.
    throttle = RateAwareThrottle(max_in_flight=2, scope="global")
    _elapsed, accounts = await _measure_tail(10, width=2, latency=0.005, throttle=throttle)
    assert throttle.tripped == 0, f"rate-aware 10006 fired {throttle.tripped}x -- gate under-throttled"
    assert accounts.max_concurrency == 2  # fan-out genuinely ran at the bound
    assert len(accounts.placement_log) == 30  # 10 accounts x 3 symbols


@pytest.mark.asyncio
async def test_negative_control_10006_fires_when_bound_exceeded():
    # Falsifiability: a GLOBAL throttle with a bound BELOW the width MUST trip -- proving
    # the zero-10006 test is not vacuously true. At width=3 the semaphore allows 3
    # concurrent; a threshold of 2 is exceeded => trips fire.
    throttle = RateAwareThrottle(max_in_flight=2, scope="global")
    _elapsed, accounts = await _measure_tail(9, width=3, latency=0.005, throttle=throttle)
    assert throttle.tripped > 0, "negative control: a too-low bound MUST trip 10006"


@pytest.mark.asyncio
async def test_speedup_is_latency_hiding_capped_at_width():
    # The win is latency-hiding up to the concurrency width, then it plateaus -- NOT a
    # monotonic-in-N throughput law. The speedup RATIO (seq/par) at a FIXED width is
    # bounded ABOVE by ~width and grows toward it as N rises.
    latency = 0.008
    width = 2
    ratios = []
    for n in (5, 10, 20):
        seq, _ = await _measure_tail(n, width=1, latency=latency)
        par, _ = await _measure_tail(n, width=width, latency=latency)
        ratios.append(seq / par)
    assert all(r > 1.0 for r in ratios), f"parallel lost its advantage at some N: {ratios}"
    # Never exceeds the width ceiling (latency-hiding, not throughput) + small tolerance.
    assert all(r <= width + 0.5 for r in ratios), f"speedup exceeded the width ceiling: {ratios}"
    # Grows toward the ceiling as N increases (plateau, not collapse).
    assert ratios[-1] >= ratios[0], f"speedup collapsed instead of plateauing: {ratios}"


@pytest.mark.asyncio
async def test_width1_is_the_sequential_baseline():
    # Sanity: width=1 places strictly one order at a time across all accounts (the
    # byte-identical sequential path). max_concurrency must be exactly 1.
    _elapsed, accounts = await _measure_tail(8, width=1, latency=0.003)
    assert accounts.max_concurrency == 1
