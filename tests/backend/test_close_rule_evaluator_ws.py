"""Tests for WS-driven close rule evaluation with debounce."""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from backend.services.close_rule_evaluator import CloseRuleEvaluator


@pytest.fixture()
def mock_deps():
    close_service = AsyncMock()
    accounts_service = AsyncMock()
    db = AsyncMock()
    db.list_active_rules = AsyncMock(return_value=[])
    db.list_active_rules_for_account = AsyncMock(return_value=[])
    return close_service, accounts_service, db


@pytest.fixture()
def evaluator(mock_deps):
    close_service, accounts_service, db = mock_deps
    return CloseRuleEvaluator(close_service=close_service, accounts_service=accounts_service, db=db)


@pytest.mark.asyncio
async def test_on_wallet_update_triggers_rule_check(evaluator, mock_deps):
    _, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[
        {"id": "r1", "account_id": "acc1", "trigger_type": "EQUITY_DROP_PCT",
         "threshold_value": "10", "reference_value": "1000", "cycle_id": None},
    ])
    db.atomic_trigger_rule = AsyncMock(return_value=False)

    wallet_data = {"totalEquity": "950", "totalWalletBalance": "900", "totalPerpUPL": "50"}
    await evaluator.on_wallet_update("acc1", wallet_data)

    db.list_active_rules_for_account.assert_called_once_with("acc1")


@pytest.mark.asyncio
async def test_debounce_skips_rapid_calls(evaluator, mock_deps):
    _, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[])

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}

    await evaluator.on_wallet_update("acc1", wallet_data)
    await evaluator.on_wallet_update("acc1", wallet_data)
    await evaluator.on_wallet_update("acc1", wallet_data)

    assert db.list_active_rules_for_account.call_count == 1


@pytest.mark.asyncio
async def test_debounce_allows_after_interval(evaluator, mock_deps):
    _, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[])

    # Use DIFFERENT equity on the second event: on_wallet_update dedups identical
    # consecutive equity readings (a partial/duplicate WS frame must not re-trigger
    # evaluation). This test isolates the DEBOUNCE-interval behaviour, so vary the
    # equity to bypass that orthogonal equity-dedup guard.
    wallet_data_1 = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}
    wallet_data_2 = {"totalEquity": "1001", "totalWalletBalance": "1001", "totalPerpUPL": "0"}

    await evaluator.on_wallet_update("acc1", wallet_data_1)
    evaluator._last_ws_eval["acc1"] = time.monotonic() - 2.0
    await evaluator.on_wallet_update("acc1", wallet_data_2)

    assert db.list_active_rules_for_account.call_count == 2


@pytest.mark.asyncio
async def test_different_accounts_not_debounced(evaluator, mock_deps):
    _, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[])

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}

    await evaluator.on_wallet_update("acc1", wallet_data)
    await evaluator.on_wallet_update("acc2", wallet_data)

    assert db.list_active_rules_for_account.call_count == 2


@pytest.mark.asyncio
async def test_ws_triggered_rule_fires_close(evaluator, mock_deps):
    close_service, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[
        {"id": "r1", "account_id": "acc1", "trigger_type": "EQUITY_DROP_PCT",
         "threshold_value": "5", "reference_value": "1000", "cycle_id": None},
    ])
    db.atomic_trigger_rule = AsyncMock(return_value=True)
    close_service.close_all_for_rule = AsyncMock(return_value={})
    db.update_close_rule = AsyncMock()
    db.deactivate_rules_for_account = AsyncMock(return_value=0)

    wallet_data = {"totalEquity": "900", "totalWalletBalance": "850", "totalPerpUPL": "50"}
    await evaluator.on_wallet_update("acc1", wallet_data)

    close_service.close_all_for_rule.assert_called_once()


@pytest.mark.asyncio
async def test_max_duration_skipped_but_breakeven_evaluated_in_ws(evaluator, mock_deps):
    _, accounts_service, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[
        {"id": "r1", "account_id": "acc1", "trigger_type": "BREAKEVEN_TIMEOUT",
         "threshold_value": "6", "reference_value": "2025-05-23T10:00:00Z", "cycle_id": None},
        {"id": "r2", "account_id": "acc1", "trigger_type": "MAX_DURATION",
         "threshold_value": "12", "reference_value": "2025-05-23T10:00:00Z", "cycle_id": None},
    ])
    # Real open position → non-zero fee buffer (1000 * 0.055/100 * 1.5 = 0.825).
    # With pnl 0 < buffer, the WS-evaluated BREAKEVEN rule must NOT fire.
    accounts_service.get_positions = AsyncMock(return_value=[{"symbol": "BTCUSDT", "positionValue": "1000"}])

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}
    await evaluator.on_wallet_update("acc1", wallet_data)

    # MAX_DURATION stays out of the WS sweep; BREAKEVEN is now WS-evaluated but holds (pnl 0 < fee buffer).
    mock_deps[0].close_all_for_rule.assert_not_called()


@pytest.mark.asyncio
async def test_breakeven_fires_in_ws_when_recovered(evaluator, mock_deps):
    """End-to-end WS path: after the breakeven window, once total open uPnL clears the
    fee buffer the rule closes ALL via the generic close path."""
    close_service, accounts_service, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[
        {"id": "r1", "account_id": "acc1", "trigger_type": "BREAKEVEN_TIMEOUT",
         "threshold_value": "6", "reference_value": "2025-05-23T10:00:00Z", "cycle_id": None},
    ])
    # Real open position → fee buffer 0.825; wallet pnl 50 clears it → breakeven fires.
    accounts_service.get_positions = AsyncMock(return_value=[{"symbol": "BTCUSDT", "positionValue": "1000"}])
    db.atomic_trigger_rule = AsyncMock(return_value=True)
    close_service.close_all_for_rule = AsyncMock(return_value={"closed": 1, "failed": 0})
    db.update_close_rule = AsyncMock()
    db.deactivate_rules_for_account = AsyncMock(return_value=0)

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "50"}
    await evaluator.on_wallet_update("acc1", wallet_data)

    close_service.close_all_for_rule.assert_called_once()


@pytest.mark.asyncio
async def test_lock_prevents_reentrant_evaluation(evaluator, mock_deps):
    """If evaluation is in progress (lock held), subsequent calls skip."""
    _, _, db = mock_deps

    # Return a drawdown rule so the code enters the locked evaluation path
    eval_count = 0
    original_evaluate = evaluator._evaluate_account_rules_with_data

    async def counting_evaluate(*args, **kwargs):
        nonlocal eval_count
        eval_count += 1
        await asyncio.sleep(0.1)

    evaluator._evaluate_account_rules_with_data = counting_evaluate

    db.list_active_rules_for_account = AsyncMock(return_value=[
        {"id": "r1", "account_id": "acc1", "trigger_type": "EQUITY_DROP_PCT",
         "threshold_value": "5", "reference_value": "1100", "cycle_id": None},
    ])

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}

    # Bypass debounce for second call
    async def fire_second():
        await asyncio.sleep(0.02)
        evaluator._last_ws_eval["acc1"] = 0
        await evaluator.on_wallet_update("acc1", wallet_data)

    await asyncio.gather(
        evaluator.on_wallet_update("acc1", wallet_data),
        fire_second(),
    )

    # Only one should have actually run (the other skipped due to lock)
    assert eval_count == 1


@pytest.mark.asyncio
async def test_shutdown_stops_ws_evaluation(evaluator, mock_deps):
    """After shutdown, WS events are ignored."""
    _, _, db = mock_deps
    db.list_active_rules_for_account = AsyncMock(return_value=[])

    await evaluator.shutdown()

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "1000", "totalPerpUPL": "0"}
    await evaluator.on_wallet_update("acc1", wallet_data)

    db.list_active_rules_for_account.assert_not_called()
