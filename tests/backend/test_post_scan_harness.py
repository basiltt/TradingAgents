"""Self-tests for the Phase-2 recording harness (TASK-2.1).

These prove the test double itself is trustworthy BEFORE the golden-equality test
(TASK-2.10) depends on it:
  * deterministic order ids (pure function of inputs)
  * concurrency-safe recording under forced interleaving (no lost/corrupted entry,
    per-account order preserved as awaits resolved)
  * rate-aware 10006 fires only when concurrency exceeds the threshold (so width=1
    is always throttle-free => golden-safe)
"""

from __future__ import annotations

import asyncio

import pytest

from tests.backend.post_scan_harness import (
    FakeThrottleError,
    Placement,
    RateAwareThrottle,
    RecordingAccountsService,
    RecordingCloseService,
    deterministic_order_id,
)


def test_order_id_is_pure_function_of_inputs():
    a = deterministic_order_id("acc1", "BTCUSDT", 1)
    b = deterministic_order_id("acc1", "BTCUSDT", 1)
    assert a == b == "ord-acc1-BTCUSDT-1"
    # seq disambiguates a repeat of the same (account, symbol)
    assert deterministic_order_id("acc1", "BTCUSDT", 2) != a


@pytest.mark.asyncio
async def test_place_trade_records_full_kwargs_tuple():
    acc = RecordingAccountsService()
    res = await acc.place_trade(
        account_id="acc1", symbol="BTCUSDT", signal_direction="long",
        trade_direction="straight", leverage=20, take_profit_pct=150,
        stop_loss_pct=100, capital_pct=5, base_capital=1000.0,
        source="scanner", strategy_kind="trend", strategy_cohort="trend",
    )
    assert res["trade_id"] == "ord-acc1-BTCUSDT-1"
    [p] = acc.placements["acc1"]
    assert isinstance(p, Placement)
    assert p.golden_tuple() == (
        "acc1", "BTCUSDT", "long", "straight", 20, 150, 100, 5, 1000.0,
        "scanner", "trend", "trend", "ord-acc1-BTCUSDT-1",
    )


@pytest.mark.asyncio
async def test_recording_is_race_free_under_forced_interleaving():
    # Latency forces every task to yield at the same await, maximizing interleave.
    acc = RecordingAccountsService(latency=0.001)

    async def place(account_id: str, n: int):
        await acc.place_trade(
            account_id=account_id, symbol=f"S{n}USDT", signal_direction="long",
            trade_direction="straight", leverage=10, take_profit_pct=5,
            stop_loss_pct=50, capital_pct=10, base_capital=1000.0,
            source="scanner", strategy_kind="trend", strategy_cohort="trend",
        )

    # 3 accounts x 20 placements, all concurrent.
    tasks = [place(f"acc{a}", n) for a in range(3) for n in range(20)]
    await asyncio.gather(*tasks)

    # No lost/duplicated entries: 60 total, 20 per account.
    assert len(acc.placement_log) == 60
    for a in range(3):
        assert len(acc.placements[f"acc{a}"]) == 20
        # Per-account order ids are a contiguous 1..20 (seq never skips/collides).
        seqs = [int(p.order_id.rsplit("-", 1)[1]) for p in acc.placements[f"acc{a}"]]
        assert seqs == list(range(1, 21))


@pytest.mark.asyncio
async def test_rate_aware_throttle_fires_only_above_concurrency_threshold():
    # max_in_flight=1 => any genuine concurrency for one account trips 10006.
    throttle = RateAwareThrottle(max_in_flight=1)
    acc = RecordingAccountsService(latency=0.005, throttle=throttle)

    async def place(n: int):
        return await acc.place_trade(
            account_id="acc1", symbol=f"S{n}USDT", signal_direction="long",
            trade_direction="straight", leverage=10, take_profit_pct=5,
            stop_loss_pct=50, capital_pct=10, base_capital=1000.0,
            source="scanner", strategy_kind="trend", strategy_cohort="trend",
        )

    # 5 concurrent placements on ONE account with threshold 1 => some must throttle.
    results = await asyncio.gather(*[place(n) for n in range(5)], return_exceptions=True)
    throttled = [r for r in results if isinstance(r, FakeThrottleError)]
    assert throttle.tripped > 0
    assert len(throttled) == throttle.tripped


@pytest.mark.asyncio
async def test_throttle_never_fires_on_sequential_path():
    # width=1 emulation: place strictly one-at-a-time. Threshold 1 must NOT trip.
    throttle = RateAwareThrottle(max_in_flight=1)
    acc = RecordingAccountsService(latency=0.001, throttle=throttle)
    for n in range(10):
        await acc.place_trade(
            account_id="acc1", symbol=f"S{n}USDT", signal_direction="long",
            trade_direction="straight", leverage=10, take_profit_pct=5,
            stop_loss_pct=50, capital_pct=10, base_capital=1000.0,
            source="scanner", strategy_kind="trend", strategy_cohort="trend",
        )
    assert throttle.tripped == 0
    assert len(acc.placement_log) == 10


@pytest.mark.asyncio
async def test_close_service_records_created_and_deleted_rules():
    close = RecordingCloseService()
    r1 = await close.create_rule("acc1", {"trigger_type": "EQUITY_RISE_PCT", "threshold_value": "10"})
    r2 = await close.create_rule("acc1", {"trigger_type": "EQUITY_DROP_PCT", "threshold_value": "5"})
    assert r1["id"] == "rule-acc1-1"
    assert r2["id"] == "rule-acc1-2"
    await close.delete_rule("acc1", r1["id"])
    assert close.deleted["acc1"] == ["rule-acc1-1"]
    assert close.created_rule_fingerprint()["acc1"] == [
        ("EQUITY_RISE_PCT", "10"), ("EQUITY_DROP_PCT", "5"),
    ]


@pytest.mark.asyncio
async def test_create_rule_ids_deterministic_across_runs():
    # Two independent close services see identical id streams for identical calls.
    async def run():
        close = RecordingCloseService()
        out = []
        for tt in ("EQUITY_RISE_PCT", "EQUITY_DROP_PCT", "TRAILING_PROFIT"):
            out.append((await close.create_rule("accX", {"trigger_type": tt, "threshold_value": "1"}))["id"])
        return out

    assert await run() == await run() == ["rule-accX-1", "rule-accX-2", "rule-accX-3"]
