"""Tests for the post-scan placement-integrity detectors (TASK-3.5, NFR-008)."""

from __future__ import annotations

import pytest

from backend.services import post_scan_concurrency as psc
from backend.services import post_scan_flags
from backend.services.auto_trade_service import AutoTradeExecutor, TradeExecution
from backend.services.post_scan_detectors import (
    assert_placement_integrity,
    find_duplicate_placements,
    find_over_cap_accounts,
)
from tests.backend.post_scan_harness import (
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


def _cfg(account_id, **overrides):
    base = {
        "account_id": account_id, "execution_mode": "batch", "max_trades": 3,
        "min_score": 0, "signal_sides": "both", "leverage": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "capital_pct": 10,
        "direction": "straight", "confidence_filter": "any",
    }
    base.update(overrides)
    return base


def _results(*tickers):
    return [
        {"id": f"r{i}", "ticker": t, "status": "completed", "direction": "sell",
         "score": -(10 - i), "confidence": "high"}
        for i, t in enumerate(tickers)
    ]


@pytest.mark.asyncio
async def test_detectors_pass_on_healthy_parallel_tail():
    psc.configure_account_concurrency(2)
    accounts = RecordingAccountsService(latency=0.001)
    ex = AutoTradeExecutor(accounts, RecordingCloseService(), scan_id="det-1")
    ex.init_configs([_cfg("accA"), _cfg("accB")])
    for st in ex._state.values():
        st.base_capital = 1000.0
    await ex.run_post_scan_tail(_results("BTC", "ETH", "SOL"))
    # Healthy: no duplicates, no over-cap.
    assert find_duplicate_placements(ex) == []
    assert find_over_cap_accounts(ex) == []
    assert_placement_integrity(ex)  # does not raise


def test_duplicate_detector_fires_on_seeded_dup():
    accounts = RecordingAccountsService()
    ex = AutoTradeExecutor(accounts, None)
    ex.init_configs([_cfg("accA")])
    state = list(ex._state.values())[0]
    # Seed a duplicate (account, symbol) success — the invariant violation.
    state.executions = [
        TradeExecution(account_id="accA", symbol="BTCUSDT", side="sell", status="success", order_id="t1"),
        TradeExecution(account_id="accA", symbol="BTCUSDT", side="sell", status="success", order_id="t2"),
    ]
    dups = find_duplicate_placements(ex)
    assert dups == [("accA", "BTCUSDT", 2)]
    with pytest.raises(AssertionError, match="duplicate placements"):
        assert_placement_integrity(ex)


def test_over_cap_detector_fires_when_exceeding_max_trades():
    accounts = RecordingAccountsService()
    ex = AutoTradeExecutor(accounts, None)
    ex.init_configs([_cfg("accA", max_trades=1)])
    state = list(ex._state.values())[0]
    # 2 successful placements but max_trades=1.
    state.executions = [
        TradeExecution(account_id="accA", symbol="BTCUSDT", side="sell", status="success", order_id="t1"),
        TradeExecution(account_id="accA", symbol="ETHUSDT", side="sell", status="success", order_id="t2"),
    ]
    over = find_over_cap_accounts(ex)
    assert over == [("accA", 2, 1)]
    with pytest.raises(AssertionError, match="over-cap"):
        assert_placement_integrity(ex)


def test_over_cap_detector_catches_per_config_breach_not_just_account_sum():
    # An account with 2 configs each max_trades=3: cfgA places 5 (breach), cfgB places 1.
    # A per-ACCOUNT-SUM check (6 <= 6) would MASK cfgA's breach — the per-CONFIG detector
    # must catch it (matches the executor's per-state max_trades enforcement).
    accounts = RecordingAccountsService()
    ex = AutoTradeExecutor(accounts, None)
    ex.init_configs([_cfg("accA", max_trades=3), _cfg("accA", max_trades=3)])
    states = list(ex._state.values())
    states[0].executions = [
        TradeExecution(account_id="accA", symbol=f"S{i}USDT", side="sell", status="success", order_id=f"a{i}")
        for i in range(5)  # cfgA: 5 > 3 (breach)
    ]
    states[1].executions = [
        TradeExecution(account_id="accA", symbol="ZZZUSDT", side="sell", status="success", order_id="b1"),
    ]  # cfgB: 1 <= 3 (ok)
    over = find_over_cap_accounts(ex)
    # cfgA's breach is reported even though the account sum (6) equals the cap sum (6).
    assert ("accA", 5, 3) in over
    with pytest.raises(AssertionError, match="over-cap"):
        assert_placement_integrity(ex)


def test_failed_executions_do_not_count_toward_cap_or_dups():
    accounts = RecordingAccountsService()
    ex = AutoTradeExecutor(accounts, None)
    ex.init_configs([_cfg("accA", max_trades=1)])
    state = list(ex._state.values())[0]
    state.executions = [
        TradeExecution(account_id="accA", symbol="BTCUSDT", side="sell", status="success", order_id="t1"),
        TradeExecution(account_id="accA", symbol="BTCUSDT", side="sell", status="failed", error="x"),
        TradeExecution(account_id="accA", symbol="ETHUSDT", side="sell", status="failed", error="y"),
    ]
    # Only 1 success => no dup, not over cap.
    assert find_duplicate_placements(ex) == []
    assert find_over_cap_accounts(ex) == []


@pytest.mark.asyncio
async def test_integrity_holds_at_width2_with_binding_max_trades():
    # A binding max_trades across the fan-out must never be exceeded (regression net).
    psc.configure_account_concurrency(2)
    accounts = RecordingAccountsService(latency=0.001)
    ex = AutoTradeExecutor(accounts, RecordingCloseService(), scan_id="det-cap")
    ex.init_configs([_cfg("accA", max_trades=2), _cfg("accB", max_trades=2)])
    for st in ex._state.values():
        st.base_capital = 1000.0
    await ex.run_post_scan_tail(_results("BTC", "ETH", "SOL", "XRP", "BNB"))
    assert_placement_integrity(ex)
    # Exactly 2 per account (the cap), no more.
    for aid in ("accA", "accB"):
        assert len([p for p in accounts.placements.get(aid, [])]) == 2


@pytest.mark.asyncio
async def test_recheck_retrade_same_symbol_no_false_positive():
    # The detector reads the LIVE per-state executions. post_scan_recheck RESETS
    # state.executions=[] on a rescued account before re-placing, so a symbol placed in
    # the batch stage and then re-placed in recheck (after a force-close cleared the
    # position) appears ONCE in the final state — the detector must NOT false-positive a
    # duplicate. This pins the read-_state-not-all_executions design + reset-before-retrade.
    psc.configure_account_concurrency(2)
    accounts = RecordingAccountsService(latency=0.001)
    # Account starts with an open position (skip_if_positions_open stops it at batch),
    # then the recheck sees positions cleared and re-trades.
    accounts.positions_by_account = {}  # cleared by the time recheck reads them
    ex = AutoTradeExecutor(accounts, RecordingCloseService(), scan_id="det-recheck")
    ex.init_configs([_cfg("accA", max_trades=2,
                          target_goal_type="profit_pct", target_goal_value=10)])
    state = list(ex._state.values())[0]
    state.base_capital = 1000.0
    # Simulate the account having been stopped for positions_already_open at batch
    # (so the recheck rescues it and re-trades the same symbols).
    state.stopped = True
    state.stopped_reason = "positions_already_open"
    await ex.run_post_scan_tail(_results("BTC", "ETH"))
    # The recheck ACTUALLY re-traded (not a trivial all-empty pass) — assert placements
    # happened so "no false positive" is meaningful, not "no placements at all".
    assert len(accounts.placements.get("accA", [])) == 2
    # No false duplicate, no over-cap — even though the same symbols flowed through
    # batch (skipped) then recheck (placed).
    assert find_duplicate_placements(ex) == []
    assert find_over_cap_accounts(ex) == []
    assert_placement_integrity(ex)


@pytest.mark.asyncio
async def test_inline_self_check_logs_high_alert_on_seeded_violation(caplog):
    # The tail's inline integrity self-check (run_post_scan_tail) must LOG a HIGH alert
    # when a duplicate/over-cap placement is detected — the money-safety alert net. We
    # seed a violation by patching _try_trade to place the SAME symbol twice for one
    # account, then assert the structured `post_scan_placement_integrity_violation` log
    # fires (and the tail still completes — fail-open, never raises).
    import logging
    from unittest.mock import patch

    psc.configure_account_concurrency(1)
    accounts = RecordingAccountsService(latency=0.0)
    ex = AutoTradeExecutor(accounts, RecordingCloseService(), scan_id="det-alert")
    ex.init_configs([_cfg("accA", max_trades=5)])
    state = list(ex._state.values())[0]
    state.base_capital = 1000.0

    real_try = ex._try_trade
    seeded = {"done": False}

    async def dup_try(state_arg, result_arg, **kw):
        exec_ = await real_try(state_arg, result_arg, **kw)
        # After the first real placement, inject a duplicate of the SAME symbol into the
        # account's executions to simulate a partition invariant break.
        if exec_ and exec_.status == "success" and not seeded["done"]:
            seeded["done"] = True
            from backend.services.auto_trade_service import TradeExecution
            state_arg.executions.append(
                TradeExecution(account_id="accA", symbol=exec_.symbol, side=exec_.side,
                               status="success", order_id="dup")
            )
        return exec_

    with caplog.at_level(logging.ERROR):
        with patch.object(ex, "_try_trade", side_effect=dup_try):
            out = await ex.run_post_scan_tail(_results("BTC"))

    # The tail completed (fail-open) AND the HIGH violation alert was logged.
    assert out["summaries"]
    assert any("post_scan_placement_integrity_violation" in r.message for r in caplog.records), (
        "the inline self-check did not log the HIGH integrity-violation alert"
    )
