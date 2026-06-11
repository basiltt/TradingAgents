"""Unit tests for AutoTradeExecutor in auto_trade_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.auto_trade_service import AutoTradeExecutor, TradeExecution


@pytest.mark.asyncio
async def test_init_balances_creates_rules_and_tracks_ids():
    # Setup mocks
    mock_accounts = AsyncMock()
    mock_accounts.get_wallet.return_value = {
        "totalAvailableBalance": "1000",
        "totalWalletBalance": "1000",
    }
    mock_accounts.get_positions.return_value = []

    mock_close_svc = AsyncMock()
    # Mock create_rule to return rule with unique ID
    rule_counter = 0
    async def mock_create_rule(account_id, rule_data):
        nonlocal rule_counter
        rule_counter += 1
        return {"id": f"rule_id_{rule_counter}"}
    mock_close_svc.create_rule.side_effect = mock_create_rule
    mock_close_svc.delete_all_rules.return_value = 2

    # Instantiate executor
    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)

    configs = [
        {
            "account_id": "acc_1",
            "target_goal_type": "profit_pct",
            "target_goal_value": 10,
            "max_drawdown_pct": 5,
            "breakeven_timeout_hours": 2,
            "max_trade_duration_hours": 4,
            "skip_if_positions_open": False,
        },
        # Sibling config sharing same account to verify propagation
        {
            "account_id": "acc_1",
            "target_goal_type": "profit_pct",
            "target_goal_value": 10,
            "max_drawdown_pct": 5,
            "breakeven_timeout_hours": 2,
            "max_trade_duration_hours": 4,
            "skip_if_positions_open": False,
        }
    ]

    executor.init_configs(configs)
    await executor.init_balances()

    # 4 rules should have been created
    assert mock_close_svc.create_rule.call_count == 4

    # Verify both states (original and sibling) have the same rule IDs and base_capital propagated
    for state in executor._state.values():
        assert state.base_capital == 1000.0
        assert len(state.created_rule_ids) == 4
        assert "rule_id_1" in state.created_rule_ids
        assert "rule_id_2" in state.created_rule_ids
        assert "rule_id_3" in state.created_rule_ids
        assert "rule_id_4" in state.created_rule_ids


@pytest.mark.asyncio
async def test_refresh_configs_preserves_state_and_updates_active_rules():
    mock_accounts = AsyncMock()
    mock_close_svc = AsyncMock()
    mock_close_svc.list_rules.return_value = [
        {"id": "rise_rule", "trigger_type": "EQUITY_RISE_PCT", "status": "active"},
        {"id": "drawdown_rule", "trigger_type": "EQUITY_DROP_PCT_SMART", "status": "active"},
    ]

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    executor.init_configs([{
        "account_id": "acc_1",
        "capital_pct": 18,
        "target_goal_type": "profit_pct",
        "target_goal_value": 8,
        "max_drawdown_pct": 10,
        "smart_drawdown_close": True,
    }])
    state = list(executor._state.values())[0]
    state.trades_executed = 2
    state.existing_symbols = {"BTCUSDT"}
    state.close_rule_id = "rise_rule"
    state.drawdown_rule_id = "drawdown_rule"
    state.created_rule_ids = ["rise_rule", "drawdown_rule"]

    refreshed = await executor.refresh_configs([{
        "account_id": "acc_1",
        "capital_pct": 22,
        "target_goal_type": "profit_pct",
        "target_goal_value": 15,
        "max_drawdown_pct": 12,
        "smart_drawdown_close": True,
    }])
    await executor.sync_active_close_rules_from_config()

    assert refreshed == 1
    state = list(executor._state.values())[0]
    assert state.trades_executed == 2
    assert state.existing_symbols == {"BTCUSDT"}
    assert state.config["capital_pct"] == 22
    assert state.config["target_goal_value"] == 15
    mock_close_svc.update_rule.assert_any_await(
        "acc_1", "rise_rule", {"threshold_value": "15"}
    )
    mock_close_svc.update_rule.assert_any_await(
        "acc_1",
        "drawdown_rule",
        {"trigger_type": "EQUITY_DROP_PCT_SMART", "threshold_value": "12"},
    )


@pytest.mark.asyncio
async def test_cleanup_unused_rules_zero_trades():
    mock_accounts = AsyncMock()
    mock_close_svc = AsyncMock()

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    configs = [
        {
            "account_id": "acc_1",
        }
    ]
    executor.init_configs(configs)
    
    # Manually populate state with created rules
    state = list(executor._state.values())[0]
    state.created_rule_ids = ["rule_1", "rule_2"]
    state.trades_executed = 0

    await executor.cleanup_unused_rules()

    # delete_rule should be called for each rule
    assert mock_close_svc.delete_rule.call_count == 2
    mock_close_svc.delete_rule.assert_any_call("acc_1", "rule_1")
    mock_close_svc.delete_rule.assert_any_call("acc_1", "rule_2")


@pytest.mark.asyncio
async def test_cleanup_unused_rules_with_trades():
    mock_accounts = AsyncMock()
    mock_close_svc = AsyncMock()

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    configs = [
        {
            "account_id": "acc_1",
        }
    ]
    executor.init_configs(configs)
    
    state = list(executor._state.values())[0]
    state.created_rule_ids = ["rule_1", "rule_2"]
    state.trades_executed = 1

    await executor.cleanup_unused_rules()

    # delete_rule should not be called
    mock_close_svc.delete_rule.assert_not_called()


@pytest.mark.asyncio
async def test_post_scan_recheck_zero_trades_cleans_up():
    mock_accounts = AsyncMock()
    mock_accounts.get_positions.return_value = []
    mock_accounts.get_wallet.return_value = {
        "totalAvailableBalance": "1000",
        "totalWalletBalance": "1000",
    }

    mock_close_svc = AsyncMock()
    # Mock rule creation to return unique rule IDs
    rule_counter = 0
    async def mock_create_rule(account_id, rule_data):
        nonlocal rule_counter
        rule_counter += 1
        return {"id": f"new_rule_{rule_counter}"}
    mock_close_svc.create_rule.side_effect = mock_create_rule

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    configs = [
        {
            "account_id": "acc_1",
            "target_goal_type": "profit_pct",
            "target_goal_value": 10,
            "max_drawdown_pct": 5,
            "breakeven_timeout_hours": 2,
            "max_trade_duration_hours": 4,
            "skip_if_positions_open": True,
        }
    ]
    executor.init_configs(configs)

    # Set state as stopped due to open positions so recheck triggers
    state = list(executor._state.values())[0]
    state.stopped = True
    state.stopped_reason = "positions_already_open"
    state.created_rule_ids = ["old_rule"]

    # We mock _try_trade to not execute anything
    with patch.object(executor, "_try_trade", return_value=None):
        results = [{"ticker": "BTC", "status": "completed", "direction": "Buy"}]
        executions = await executor.post_scan_recheck(results)

    # Verify executions is empty
    assert len(executions) == 0
    # Re-created 4 rules
    assert mock_close_svc.create_rule.call_count == 4
    # But because 0 trades were executed, all 4 new rules should be cleaned up
    assert mock_close_svc.delete_rule.call_count == 4
    mock_close_svc.delete_rule.assert_any_call("acc_1", "new_rule_1")
    mock_close_svc.delete_rule.assert_any_call("acc_1", "new_rule_2")
    mock_close_svc.delete_rule.assert_any_call("acc_1", "new_rule_3")
    mock_close_svc.delete_rule.assert_any_call("acc_1", "new_rule_4")


@pytest.mark.asyncio
async def test_executor_accepts_recorder_and_context_optional():
    from backend.services.auto_trade_service import AutoTradeExecutor
    mock_accounts = AsyncMock()
    ex = AutoTradeExecutor(mock_accounts, None)
    assert ex._recorder is None
    assert ex._debug_ctx is None
    rec = MagicMock()
    ctx = object()
    ex2 = AutoTradeExecutor(mock_accounts, None, recorder=rec, debug_ctx=ctx)
    assert ex2._recorder is rec
    assert ex2._debug_ctx is ctx


@pytest.mark.asyncio
async def test_try_trade_emits_min_score_skip_decision():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    rec = MagicMock()
    ctx = object()
    ex = AutoTradeExecutor(AsyncMock(), None, recorder=rec, debug_ctx=ctx)
    state = _AccountState(config={
        "account_id": "acc_1", "min_score": 7, "confidence_filter": "any",
        "execution_mode": "batch",
    })
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -3}
    out = await ex._try_trade(state, result, phase="batch")
    assert out is None
    rec.emit_symbol_decision.assert_called()
    _, kwargs = rec.emit_symbol_decision.call_args
    assert kwargs["reason_code"] == "min_score"
    assert kwargs["decision"] == "skipped"


@pytest.mark.asyncio
async def test_try_trade_emit_is_noop_without_recorder():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    ex = AutoTradeExecutor(AsyncMock(), None)
    state = _AccountState(config={"account_id": "acc_1", "min_score": 7, "execution_mode": "batch"})
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -3}
    out = await ex._try_trade(state, result)
    assert out is None


@pytest.mark.asyncio
async def test_init_balances_emits_snapshot_and_skip_when_positions_open():
    from backend.services.auto_trade_service import AutoTradeExecutor
    rec = MagicMock()
    ctx = object()
    accounts = AsyncMock()
    accounts.get_account.return_value = {"id": "acc_1"}
    accounts.get_positions.return_value = [{"symbol": "AAPLUSDT", "side": "Sell", "size": "1"}]
    accounts.get_wallet.return_value = {"totalAvailableBalance": "1000", "totalWalletBalance": "1000"}
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    ex.init_configs([{"account_id": "acc_1", "skip_if_positions_open": True, "execution_mode": "batch"}])
    await ex.init_balances()
    assert rec.emit_exchange_snapshot.called
    evs = [c.kwargs.get("event_type") for c in rec.emit_lifecycle.call_args_list]
    assert "marked_stopped" in evs


@pytest.mark.asyncio
async def test_emit_account_summaries_emits_one_per_state():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    from backend.services.debug_trace_recorder import RunContext
    rec = MagicMock()
    ctx = RunContext(scan_id="s1")
    ctx.run_id = 7   # an active run is required for summaries to emit
    accounts = AsyncMock()
    accounts.get_account.return_value = {"id": "acc_1", "label": "Dad - Demo"}
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    ex._state = {"acc_1_0": _AccountState(config={"account_id": "acc_1", "execution_mode": "batch"})}
    count = await ex.emit_account_summaries()
    rec.emit_account_trace.assert_called_once()
    _, kwargs = rec.emit_account_trace.call_args
    assert kwargs["account_label"] == "Dad - Demo"
    assert count == 1


@pytest.mark.asyncio
async def test_emit_account_summaries_noop_when_run_inactive():
    """When the run is inactive (run_id None — tracing disabled/open_run failed),
    summaries must NOT do get_account DB lookups or emit; just return the count."""
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    from backend.services.debug_trace_recorder import RunContext
    rec = MagicMock()
    ctx = RunContext(scan_id="s1")  # run_id stays None
    accounts = AsyncMock()
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    ex._state = {"acc_1_0": _AccountState(config={"account_id": "acc_1", "execution_mode": "batch"})}
    count = await ex.emit_account_summaries()
    assert count == 1
    rec.emit_account_trace.assert_not_called()
    accounts.get_account.assert_not_called()   # no wasted DB lookups when tracing off


@pytest.mark.asyncio
async def test_try_trade_success_unaffected_by_raising_recorder():
    """A raising recorder on the success-path emit must NOT corrupt trade accounting."""
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    rec = MagicMock()
    # emit_symbol_decision raises — must be swallowed, trade must still count as success.
    rec.emit_symbol_decision.side_effect = RuntimeError("boom")
    ctx = object()
    accounts = AsyncMock()
    accounts.place_trade.return_value = {"trade_id": "t1", "side": "Sell"}
    accounts.get_mark_price.return_value = 100.0
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    state = _AccountState(config={
        "account_id": "acc_1", "min_score": 0, "confidence_filter": "any",
        "execution_mode": "batch", "leverage": 5, "capital_pct": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "direction": "straight",
    })
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -7, "id": 1}
    out = await ex._try_trade(state, result, phase="batch")
    assert out is not None
    assert out.status == "success"
    assert state.trades_executed == 1
    assert state.trades_failed == 0   # the raising emit did NOT cause a double-count


@pytest.mark.asyncio
async def test_shared_lock_recheck_skips_position_opened_since_scan():
    """C2 regression: with the shared position-lock registry, placement re-checks
    LIVE positions under the lock and skips a symbol opened since the scan started
    (e.g. by the AI manager) — preventing a duplicate/opposite position."""
    from backend.services.position_lock_registry import PositionLockRegistry

    mock_accounts = AsyncMock()
    # the scan's initial snapshot had NO position, but a live re-check finds one
    mock_accounts.get_positions.return_value = [{"symbol": "BTCUSDT", "size": "0.5"}]
    mock_accounts.place_trade = AsyncMock()  # must NOT be called

    registry = PositionLockRegistry()
    executor = AutoTradeExecutor(mock_accounts, None, position_lock_registry=registry)

    # minimal state: symbol not in the stale existing_symbols set
    from backend.services.auto_trade_service import _AccountState
    cfg = {"account_id": "acc1", "leverage": 10, "take_profit_pct": 150,
           "stop_loss_pct": 100, "capital_pct": 5, "direction": "straight"}
    state = _AccountState(config=cfg)
    state.base_capital = 1000.0
    state.existing_symbols = set()  # scan-time snapshot was empty

    result = {"id": "scan-1", "score": 0.9, "status": "completed",
              "direction": "long", "confidence": "high", "ticker": "BTC"}

    out = await executor._try_trade(state, result, phase="batch")
    # placement was skipped by the under-lock live re-check
    mock_accounts.place_trade.assert_not_called()
    assert state.trades_skipped >= 1
    assert "BTCUSDT" in state.existing_symbols  # now tracked
    # the lock was released (re-acquire succeeds immediately)
    assert await registry.acquire("acc1", "BTCUSDT", timeout=0.5) is True
    registry.release("acc1", "BTCUSDT")


@pytest.mark.asyncio
async def test_post_scan_recheck_honors_fill_to_max_trades():
    """Regression (prod run #28, "Dad - Demo"): an account rescued by the post-scan
    recheck must honor fill_to_max_trades — backfilling the remaining max_trades
    slots from the next-best (sub-min_score) signals via a relaxed pass — exactly
    like the normal execute_batch path does. Before the fix the recheck ran a single
    strict pass only, so an account with max_trades=3 but just ONE signal clearing
    min_score placed 1 trade and stalled, silently ignoring the user's toggle.
    """
    mock_accounts = AsyncMock()
    # Positions cleared during the scan → recheck rescues the account.
    mock_accounts.get_positions.return_value = []
    mock_accounts.get_wallet.return_value = {
        "totalAvailableBalance": "1000",
        "totalWalletBalance": "1000",
    }
    mock_accounts.get_mark_price.return_value = 100.0  # no price drift

    placed: list = []

    async def fake_place_trade(**kwargs):
        placed.append(kwargs["symbol"])
        return {"side": kwargs["signal_direction"], "trade_id": f"t{len(placed)}"}

    mock_accounts.place_trade.side_effect = fake_place_trade

    mock_close_svc = AsyncMock()
    mock_close_svc.list_rules.return_value = []  # not paused
    rule_counter = 0

    async def mock_create_rule(account_id, rule_data):
        nonlocal rule_counter
        rule_counter += 1
        return {"id": f"new_rule_{rule_counter}"}

    mock_close_svc.create_rule.side_effect = mock_create_rule

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    configs = [
        {
            "account_id": "acc_1",
            "max_trades": 3,
            "min_score": 7,
            "fill_to_max_trades": True,
            "signal_sides": "both",
            "leverage": 10,
            "take_profit_pct": 150,
            "stop_loss_pct": 100,
            "capital_pct": 20,
            "direction": "straight",
            "skip_if_positions_open": True,
            # no max_same_sector / max_same_direction so they don't interfere
        }
    ]
    executor.init_configs(configs)

    state = list(executor._state.values())[0]
    state.stopped = True
    state.stopped_reason = "positions_already_open"

    # One signal clears min_score=7; two next-best signals are below it. With
    # fill_to_max_trades on, all three should be placed (1 strict + 2 relaxed fill).
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
    ]

    executions = await executor.post_scan_recheck(results)

    successful = [e for e in executions if e.status == "success"]
    assert state.trades_executed == 3, (
        f"expected 3 trades (1 strict + 2 fill), got {state.trades_executed}; placed={placed}"
    )
    assert len(successful) == 3
    # List equality: strict MEGA first, then fill in stable (input) order for the -6 tie.
    assert placed == ["MEGAUSDT", "HIGHUSDT", "HOLOUSDT"]


def _recheck_fill_executor(*, execution_mode: str, fill_to_max_trades: bool,
                           place_side_effect=None, config_overrides: dict | None = None):
    """Build an executor + one account rescued by the recheck (positions cleared),
    parameterized by execution_mode and the fill toggle. Returns (executor, state, placed).

    place_side_effect: optional custom place_trade side effect (e.g. to simulate a
    mid-fill failure). config_overrides: extra/override keys merged into the config.
    """
    mock_accounts = AsyncMock()
    mock_accounts.get_positions.return_value = []
    mock_accounts.get_wallet.return_value = {
        "totalAvailableBalance": "1000",
        "totalWalletBalance": "1000",
    }
    mock_accounts.get_mark_price.return_value = 100.0

    placed: list = []

    async def fake_place_trade(**kwargs):
        placed.append(kwargs["symbol"])
        return {"side": kwargs["signal_direction"], "trade_id": f"t{len(placed)}"}

    mock_accounts.place_trade.side_effect = place_side_effect or fake_place_trade

    mock_close_svc = AsyncMock()
    mock_close_svc.list_rules.return_value = []
    counter = 0

    async def mk_rule(account_id, rule_data):
        nonlocal counter
        counter += 1
        return {"id": f"r{counter}"}

    mock_close_svc.create_rule.side_effect = mk_rule

    executor = AutoTradeExecutor(mock_accounts, mock_close_svc)
    cfg = {
        "account_id": "acc_1",
        "max_trades": 3,
        "min_score": 7,
        "fill_to_max_trades": fill_to_max_trades,
        "signal_sides": "both",
        "leverage": 10,
        "take_profit_pct": 150,
        "stop_loss_pct": 100,
        "capital_pct": 20,
        "direction": "straight",
        "skip_if_positions_open": True,
        "execution_mode": execution_mode,
    }
    if config_overrides:
        cfg.update(config_overrides)
    executor.init_configs([cfg])
    state = list(executor._state.values())[0]
    state.stopped = True
    state.stopped_reason = "positions_already_open"
    return executor, state, placed


@pytest.mark.asyncio
async def test_post_scan_recheck_fill_covers_immediate_mode():
    """The recheck rescue path is execution-mode-agnostic, so fill_to_max_trades must
    backfill an IMMEDIATE-mode rescued account too (its normal fill runs via
    fill_immediate_remaining, which the recheck bypasses). One qualifying + two
    sub-min_score signals → 3 placements."""
    executor, state, placed = _recheck_fill_executor(execution_mode="immediate", fill_to_max_trades=True)
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
    ]
    await executor.post_scan_recheck(results)
    assert state.trades_executed == 3, f"placed={placed}"
    assert placed == ["MEGAUSDT", "HIGHUSDT", "HOLOUSDT"]


@pytest.mark.asyncio
async def test_post_scan_recheck_no_fill_when_toggle_disabled():
    """Negative guard: with fill_to_max_trades OFF, the recheck must NOT backfill —
    it places only the strictly-qualifying signal (score >= min_score) and stops,
    so the fix never over-trades an account that disabled the toggle."""
    executor, state, placed = _recheck_fill_executor(execution_mode="batch", fill_to_max_trades=False)
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
    ]
    await executor.post_scan_recheck(results)
    assert state.trades_executed == 1, f"expected strict-only 1, placed={placed}"
    assert placed == ["MEGAUSDT"]


@pytest.mark.asyncio
async def test_post_scan_recheck_fill_caps_at_max_trades_in_score_order():
    """T1: the fill must stop at max_trades AND place the highest-|score| sub-min
    candidates first. max_trades=2 with 1 strict + 4 sub-min candidates → exactly 2
    placed: the strict one plus the single best fill candidate (by |score|)."""
    executor, state, placed = _recheck_fill_executor(
        execution_mode="batch", fill_to_max_trades=True,
        config_overrides={"max_trades": 2, "min_score": 7},
    )
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "BIG", "status": "completed", "direction": "sell", "score": -6.5, "confidence": "moderate"},
        {"id": "r3", "ticker": "MID", "status": "completed", "direction": "sell", "score": -5, "confidence": "low"},
        {"id": "r4", "ticker": "SMOL", "status": "completed", "direction": "sell", "score": -3, "confidence": "low"},
        {"id": "r5", "ticker": "TINY", "status": "completed", "direction": "sell", "score": -1, "confidence": "low"},
    ]
    await executor.post_scan_recheck(results)
    # Exactly max_trades, and the fill picked the best remaining by |score| (BIG, not MID/SMOL/TINY).
    assert placed == ["MEGAUSDT", "BIGUSDT"], f"placed={placed}"
    assert state.trades_executed == 2


@pytest.mark.asyncio
async def test_post_scan_recheck_fill_respects_max_same_direction():
    """T2: relaxed fill must NOT bypass the concentration gate. max_same_direction=2,
    all-sell signals → strict places 1 short, fill adds 1 more (=2), the 3rd is
    blocked by max_same_direction even though a max_trades slot remains."""
    executor, state, placed = _recheck_fill_executor(
        execution_mode="batch", fill_to_max_trades=True,
        config_overrides={"max_trades": 3, "min_score": 7, "max_same_direction": 2},
    )
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -5, "confidence": "low"},
    ]
    await executor.post_scan_recheck(results)
    assert placed == ["MEGAUSDT", "HIGHUSDT"], f"placed={placed}"
    assert state.trades_executed == 2


@pytest.mark.asyncio
async def test_post_scan_recheck_fill_excludes_stale_signals():
    """Regression for the relaxed-age bypass: max_signal_age must be enforced even in
    the relaxed fill. A fresh strict signal places; a stale sub-min candidate (older
    than max_signal_age_minutes) must NOT be filled despite an open slot."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresh = now.isoformat()
    stale = (now - timedelta(minutes=45)).isoformat()
    executor, state, placed = _recheck_fill_executor(
        execution_mode="batch", fill_to_max_trades=True,
        config_overrides={"max_trades": 3, "min_score": 7, "max_signal_age_minutes": 10},
    )
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high", "completed_at": fresh},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate", "completed_at": stale},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -5, "confidence": "low", "completed_at": fresh},
    ]
    await executor.post_scan_recheck(results)
    # Stale HIGH is excluded; fresh HOLO fills the second slot.
    assert "HIGHUSDT" not in placed, f"stale signal was filled: placed={placed}"
    assert placed == ["MEGAUSDT", "HOLOUSDT"], f"placed={placed}"
    assert state.trades_executed == 2


@pytest.mark.asyncio
async def test_post_scan_recheck_fill_resilient_to_midfill_failure():
    """T5: a non-ambiguous placement failure mid-fill must not abort the whole fill —
    the loop continues and only successful placements join the traded set / counters."""
    async def flaky_place(**kwargs):
        sym = kwargs["symbol"]
        if sym == "HIGHUSDT":
            raise ValueError("insufficient balance")  # non-ambiguous → status=failed
        return {"side": kwargs["signal_direction"], "trade_id": sym}

    executor, state, placed = _recheck_fill_executor(
        execution_mode="batch", fill_to_max_trades=True,
        place_side_effect=flaky_place,
        config_overrides={"max_trades": 3, "min_score": 7},
    )
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -5, "confidence": "low"},
    ]
    await executor.post_scan_recheck(results)
    # MEGA (strict) + HOLO (fill) succeed; HIGH fails but doesn't abort the loop.
    assert state.trades_executed == 2, f"placed={placed}"
    assert state.trades_failed == 1
    assert "HIGHUSDT" not in {e.symbol for e in state.executions if e.status == "success"}


def _fill_executor(*, execution_mode: str, config_overrides: dict | None = None):
    """Executor + one flat (no open positions) account for exercising the batch /
    immediate strict+fill passes directly via execute_batch / fill_immediate_remaining."""
    mock_accounts = AsyncMock()
    mock_accounts.get_positions.return_value = []
    mock_accounts.get_mark_price.return_value = 100.0
    placed: list = []

    async def fake_place_trade(**kwargs):
        placed.append(kwargs["symbol"])
        return {"side": kwargs["signal_direction"], "trade_id": f"t{len(placed)}"}

    mock_accounts.place_trade.side_effect = fake_place_trade

    executor = AutoTradeExecutor(mock_accounts, None)
    cfg = {
        "account_id": "acc_1", "max_trades": 3, "min_score": 7,
        "fill_to_max_trades": True, "signal_sides": "both", "leverage": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "capital_pct": 20,
        "direction": "straight", "execution_mode": execution_mode,
    }
    if config_overrides:
        cfg.update(config_overrides)
    executor.init_configs([cfg])
    state = list(executor._state.values())[0]
    state.base_capital = 1000.0
    return executor, state, placed


@pytest.mark.asyncio
async def test_execute_batch_fill_backfills_to_max_in_score_order():
    """Guard for the shared _fill_to_max via execute_batch: 1 strict + relaxed backfill
    of the next-best sub-min_score signals up to max_trades, highest |score| first."""
    executor, state, placed = _fill_executor(execution_mode="batch")
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "BIG", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "MID", "status": "completed", "direction": "sell", "score": -5, "confidence": "low"},
        {"id": "r4", "ticker": "TINY", "status": "completed", "direction": "sell", "score": -2, "confidence": "low"},
    ]
    await executor.execute_batch(results)
    assert placed == ["MEGAUSDT", "BIGUSDT", "MIDUSDT"], f"placed={placed}"
    assert state.trades_executed == 3


@pytest.mark.asyncio
async def test_execute_batch_fill_no_double_place_of_strict_symbol():
    """Dedup guard after unifying batch on the _to_symbol key: a symbol placed in the
    strict pass must never be re-placed by the fill pass."""
    executor, state, placed = _fill_executor(execution_mode="batch", config_overrides={"max_trades": 3, "min_score": 5})
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -8, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -3, "confidence": "low"},
    ]
    await executor.execute_batch(results)
    # MEGA strict, HIGH fill — each exactly once, no duplicate of MEGA.
    assert placed == ["MEGAUSDT", "HIGHUSDT"], f"placed={placed}"
    assert placed.count("MEGAUSDT") == 1


@pytest.mark.asyncio
async def test_fill_immediate_remaining_backfills_after_strict():
    """Guard for the shared _fill_to_max via fill_immediate_remaining: with a strict
    immediate placement already recorded, the fill backfills remaining slots."""
    executor, state, placed = _fill_executor(execution_mode="immediate")
    # Simulate the strict immediate pass having placed MEGA already.
    state.trades_executed = 1
    state.executions.append(TradeExecution(account_id="acc_1", symbol="MEGAUSDT", side="sell", status="success", order_id="t0"))
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
        {"id": "r3", "ticker": "HOLO", "status": "completed", "direction": "sell", "score": -5, "confidence": "low"},
    ]
    await executor.fill_immediate_remaining(results)
    # MEGA already traded (deduped); fill adds HIGH + HOLO up to max_trades=3.
    assert placed == ["HIGHUSDT", "HOLOUSDT"], f"placed={placed}"
    assert state.trades_executed == 3


@pytest.mark.asyncio
async def test_batch_fill_cross_config_dedup_same_account():
    """The shared `traded` set is mutated in-out precisely so a symbol placed for one
    config of an account is not re-placed by another config of the SAME account during
    the fill. Two batch configs on acc_1, max_trades=1 each: the strict pass places the
    top signal for config A; config B's fill must NOT re-place it, and each config still
    fills its own remaining slot from a distinct next-best signal."""
    mock_accounts = AsyncMock()
    mock_accounts.get_positions.return_value = []
    mock_accounts.get_mark_price.return_value = 100.0
    placed: list = []

    async def fake_place_trade(**kwargs):
        placed.append(kwargs["symbol"])
        return {"side": kwargs["signal_direction"], "trade_id": f"t{len(placed)}"}

    mock_accounts.place_trade.side_effect = fake_place_trade

    executor = AutoTradeExecutor(mock_accounts, None)
    base = {
        "account_id": "acc_1", "max_trades": 1, "min_score": 7,
        "fill_to_max_trades": True, "signal_sides": "both", "leverage": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "capital_pct": 20,
        "direction": "straight", "execution_mode": "batch",
    }
    executor.init_configs([dict(base), dict(base)])  # two configs, same account
    for st in executor._state.values():
        st.base_capital = 1000.0

    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
    ]
    await executor.execute_batch(results)
    # MEGA placed once (strict, config A); config B's fill can't re-place MEGA (shared
    # traded set) so it takes HIGH. No symbol placed twice across configs.
    assert sorted(placed) == ["HIGHUSDT", "MEGAUSDT"], f"placed={placed}"
    assert placed.count("MEGAUSDT") == 1
    states = list(executor._state.values())
    assert states[0].trades_executed == 1 and states[1].trades_executed == 1


@pytest.mark.asyncio
async def test_recheck_fill_skips_account_stopped_for_other_reason():
    """Safety guard: the fill must NOT backfill an account stopped for a reason other
    than max_trades_reached (e.g. target_goal_reached / no_balance / ai_paused). Only
    the max_trades_reached stop is reset by the fill pass."""
    executor, state, placed = _recheck_fill_executor(
        execution_mode="batch", fill_to_max_trades=True,
        config_overrides={"max_trades": 3, "min_score": 7},
    )
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -6, "confidence": "moderate"},
    ]
    # Force a non-max_trades stop AFTER the recheck reset, by patching _try_trade so the
    # strict pass sets target_goal_reached (simulating the goal cap) on first call.
    real_try = executor._try_trade

    async def stop_on_goal(state_arg, result_arg, **kw):
        # Strict pass: place MEGA then mark the account goal-stopped (not max_trades).
        exec_ = await real_try(state_arg, result_arg, **kw)
        if result_arg.get("ticker") == "MEGA":
            state_arg.stopped = True
            state_arg.stopped_reason = "target_goal_reached"
        return exec_

    with patch.object(executor, "_try_trade", side_effect=stop_on_goal):
        await executor.post_scan_recheck(results)

    # MEGA placed in strict; HIGH must NOT be filled because the account is stopped for
    # target_goal_reached (the fill only un-stops max_trades_reached).
    assert placed == ["MEGAUSDT"], f"placed={placed}"
    assert state.stopped is True and state.stopped_reason == "target_goal_reached"


@pytest.mark.asyncio
async def test_fill_preserves_max_trades_reached_reason_when_full():
    """Observability guard: a fully-filled account (strict pass alone reached
    max_trades) must KEEP final stopped_reason == 'max_trades_reached' after the fill
    pass — the fill must not blank it just because fill_to_max_trades is on. This is
    what the debug trace records as gate_that_stopped / final_stopped_reason."""
    executor, state, placed = _fill_executor(
        execution_mode="batch", config_overrides={"max_trades": 1, "min_score": 5},
    )
    # Two qualifying signals; max_trades=1 → strict places MEGA, then sets
    # max_trades_reached on the 2nd. Fill has no remaining slots → must preserve reason.
    results = [
        {"id": "r1", "ticker": "MEGA", "status": "completed", "direction": "sell", "score": -8, "confidence": "high"},
        {"id": "r2", "ticker": "HIGH", "status": "completed", "direction": "sell", "score": -7, "confidence": "high"},
    ]
    await executor.execute_batch(results)
    assert placed == ["MEGAUSDT"], f"placed={placed}"
    assert state.trades_executed == 1
    assert state.stopped_reason == "max_trades_reached", (
        f"fully-filled account lost its stop reason: {state.stopped_reason}"
    )
