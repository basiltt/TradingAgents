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
    rec = MagicMock()
    ctx = object()
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
