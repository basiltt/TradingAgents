"""Comprehensive unit tests for ClosePositionsService."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError
from backend.services.close_positions_service import (
    CLOSE_RATE_LIMIT,
    MAX_RULES_PER_ACCOUNT,
    ClosePositionsService,
)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.insert_close_execution = AsyncMock(return_value={"id": "exec-1"})
    db.get_account = AsyncMock(return_value={"id": "acc-1", "name": "Test"})
    db.count_rules_for_account = AsyncMock(return_value=0)
    db.insert_close_rule = AsyncMock(return_value={"id": "rule-1", "account_id": "acc-1", "status": "active"})
    db.list_close_rules = AsyncMock(return_value=[])
    db.get_close_rule = AsyncMock(return_value=None)
    db.update_close_rule = AsyncMock(return_value={"id": "rule-1"})
    db.delete_close_rule = AsyncMock(return_value=True)
    db.list_close_executions = AsyncMock(return_value={"items": [], "total": 0})
    return db


@pytest.fixture
def mock_accounts_service():
    svc = AsyncMock()
    client = AsyncMock()
    client.get_positions = AsyncMock(return_value=[])
    client.place_market_close_order = AsyncMock(return_value={"orderId": "ord-1", "avgPrice": "100.0"})
    svc.get_client = AsyncMock(return_value=client)
    svc.get_wallet = AsyncMock(return_value={"totalEquity": "10000"})
    svc.invalidate_cache = MagicMock()
    return svc


@pytest.fixture
def mock_ws_manager():
    ws = AsyncMock()
    ws.broadcast_to_account = AsyncMock()
    return ws


@pytest.fixture
def mock_trade_service():
    ts = AsyncMock()
    ts.get_open_trades = AsyncMock(return_value=[])
    ts.close_trade_record_only = AsyncMock()
    ts.invalidate_stats_cache = MagicMock()
    return ts


@pytest.fixture
def service(mock_db, mock_accounts_service, mock_ws_manager, mock_trade_service):
    return ClosePositionsService(mock_db, mock_accounts_service, mock_ws_manager, mock_trade_service)


# ─── close_all_positions ───────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_no_positions(service, mock_db, mock_accounts_service):
    """Returns early with zero counts when no positions exist."""
    result = await service.close_all_positions("acc-1")
    assert result["total"] == 0
    assert result["closed"] == 0
    assert result["failed"] == 0
    assert result["execution_id"] == "exec-1"


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_with_positions(service, mock_accounts_service, mock_db):
    """Successfully closes positions and returns counts."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "positionIdx": 0},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0", "positionIdx": 0},
    ]
    result = await service.close_all_positions("acc-1")
    assert result["total"] == 2
    assert result["closed"] == 2
    assert result["failed"] == 0
    mock_accounts_service.invalidate_cache.assert_called_with("acc-1")


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_partial_failure(service, mock_accounts_service, mock_db):
    """One position fails, one succeeds."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "positionIdx": 0},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0", "positionIdx": 0},
    ]
    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"orderId": "ord-1"}
        raise BybitAPIError(10001, "Insufficient balance")

    client.place_market_close_order.side_effect = side_effect
    result = await service.close_all_positions("acc-1")
    assert result["closed"] == 1
    assert result["failed"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_connection_error(service, mock_accounts_service):
    """Generic exception maps to 'Connection error'."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
    ]
    client.place_market_close_order.side_effect = RuntimeError("timeout")
    result = await service.close_all_positions("acc-1")
    assert result["failed"] == 1
    assert result["results"][0]["error"] == "Connection error"


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_lock_prevents_concurrent(service):
    """Second call raises ValueError when close lock is held."""
    # Directly set the lock to simulate an in-progress close
    service._closing_accounts["acc-1"] = time.monotonic()
    with pytest.raises(ValueError, match="Close already in progress"):
        await service.close_all_positions("acc-1")
    service._closing_accounts.pop("acc-1", None)


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_expired_lock(service, mock_accounts_service):
    """Stale lock is expired and close proceeds."""
    # Set a stale lock
    service._closing_accounts["acc-1"] = time.monotonic() - 400
    result = await service.close_all_positions("acc-1")
    assert result["total"] == 0  # no positions


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_invalidates_trade_service_cache(service, mock_accounts_service, mock_trade_service):
    """trade_service.invalidate_stats_cache is called."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    await service.close_all_positions("acc-1")
    mock_trade_service.invalidate_stats_cache.assert_called_with("acc-1")


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_broadcasts_ws_event(service, mock_accounts_service, mock_ws_manager):
    """WebSocket event is broadcast after close."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    await service.close_all_positions("acc-1")
    mock_ws_manager.broadcast_to_account.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_no_ws_manager(mock_db, mock_accounts_service, mock_trade_service):
    """No error when ws_manager is None."""
    svc = ClosePositionsService(mock_db, mock_accounts_service, None, mock_trade_service)
    result = await svc.close_all_positions("acc-1")
    assert result["total"] == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_close_all_no_trade_service(mock_db, mock_accounts_service, mock_ws_manager):
    """No error when trade_service is None."""
    svc = ClosePositionsService(mock_db, mock_accounts_service, mock_ws_manager, None)
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    result = await svc.close_all_positions("acc-1")
    assert result["closed"] == 1


# ─── close_all_for_rule ────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_no_positions(service):
    """Returns empty result when no positions."""
    result = await service.close_all_for_rule("acc-1", "rule-1")
    assert result["total"] == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_filters_symbols(service, mock_accounts_service):
    """Only closes positions matching the symbol filter."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0"},
    ]
    result = await service.close_all_for_rule("acc-1", "rule-1", symbols=["BTCUSDT"])
    assert result["total"] == 1
    assert result["closed"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_lock_skips(service):
    """Returns skipped=True when lock is active."""
    service._closing_accounts["acc-1"] = time.monotonic()
    result = await service.close_all_for_rule("acc-1", "rule-1")
    assert result.get("skipped") is True
    service._closing_accounts.pop("acc-1")


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_expired_lock(service, mock_accounts_service):
    """Stale lock is expired for rule-triggered close."""
    service._closing_accounts["acc-1"] = time.monotonic() - 400
    result = await service.close_all_for_rule("acc-1", "rule-1")
    assert result["total"] == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_with_positions(service, mock_accounts_service):
    """Closes all positions for rule."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
    ]
    result = await service.close_all_for_rule("acc-1", "rule-1")
    assert result["closed"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_close_for_rule_empty_symbols_closes_nothing(service, mock_accounts_service):
    """SAFETY: an explicit EMPTY symbols list must close NOTHING (not fall through
    to close-all). Regression for the `if symbols:` vs `if symbols is not None:` bug —
    an empty scoping list closing every position would be catastrophic."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1"},
    ]
    result = await service.close_all_for_rule("acc-1", "rule-1", symbols=[])
    assert result["total"] == 0
    assert result["closed"] == 0
    # The exchange close order must never have been called for any position.
    client.place_market_close_order.assert_not_called()


# ─── _close_matching_trades ────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_close_matching_trades_closes_records(service, mock_trade_service, mock_accounts_service):
    """Matching open trades are closed via trade_service."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
    ]
    mock_trade_service.get_open_trades.return_value = [
        {"id": "t-1", "symbol": "BTCUSDT", "side": "Buy"},
    ]
    await service.close_all_positions("acc-1")
    mock_trade_service.close_trade_record_only.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_close_matching_trades_handles_error(service, mock_trade_service, mock_accounts_service):
    """Error in close_trade_record_only is swallowed."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
    ]
    mock_trade_service.get_open_trades.return_value = [
        {"id": "t-1", "symbol": "BTCUSDT", "side": "Buy"},
    ]
    mock_trade_service.close_trade_record_only.side_effect = RuntimeError("db error")
    # Should not raise
    result = await service.close_all_positions("acc-1")
    assert result["closed"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_close_matching_trades_get_open_trades_error(service, mock_trade_service, mock_accounts_service):
    """Error in get_open_trades is swallowed."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
    ]
    mock_trade_service.get_open_trades.side_effect = RuntimeError("fail")
    result = await service.close_all_positions("acc-1")
    assert result["closed"] == 1


# ─── create_rule ───────────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_success(service, mock_db):
    """Creates a rule successfully."""
    result = await service.create_rule("acc-1", {
        "trigger_type": "EQUITY_DROP_ABS",
        "threshold_value": "500",
    })
    assert result["id"] == "rule-1"


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_account_not_found(service, mock_db):
    """Raises ValueError when account doesn't exist."""
    mock_db.get_account.return_value = None
    with pytest.raises(ValueError, match="Account not found"):
        await service.create_rule("bad-acc", {"trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"})


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_max_limit(service, mock_db):
    """Raises ValueError when max rules reached."""
    mock_db.count_rules_for_account.return_value = MAX_RULES_PER_ACCOUNT
    with pytest.raises(ValueError, match="Maximum"):
        await service.create_rule("acc-1", {"trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"})


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_pct_fetches_reference(service, mock_accounts_service):
    """Percentage rule fetches current equity as reference."""
    await service.create_rule("acc-1", {
        "trigger_type": "EQUITY_DROP_PCT",
        "threshold_value": "10",
    })
    mock_accounts_service.get_wallet.assert_called_with("acc-1")


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_pct_zero_equity(service, mock_accounts_service):
    """Raises when equity is zero for percentage rule."""
    mock_accounts_service.get_wallet.return_value = {"totalEquity": "0"}
    with pytest.raises(ValueError, match="equity is zero"):
        await service.create_rule("acc-1", {
            "trigger_type": "EQUITY_DROP_PCT",
            "threshold_value": "10",
        })


@pytest.mark.asyncio(loop_scope="function")
async def test_create_rule_negative_threshold(service):
    """Raises when threshold is not positive."""
    with pytest.raises(ValueError, match="must be positive"):
        await service.create_rule("acc-1", {
            "trigger_type": "EQUITY_DROP_ABS",
            "threshold_value": "-1",
        })


@pytest.mark.asyncio(loop_scope="function")
async def test_create_time_based_rule_success(service, mock_db, mock_accounts_service):
    """Creating a time-based rule does not fetch wallet equity and uses/sets default timestamp reference."""
    mock_accounts_service.get_wallet.reset_mock()
    result = await service.create_rule("acc-1", {
        "trigger_type": "BREAKEVEN_TIMEOUT",
        "threshold_value": "4.5",
    })
    assert result["id"] == "rule-1"
    # Verify we did not call get_wallet
    mock_accounts_service.get_wallet.assert_not_called()
    # Verify reference value was inserted
    args = mock_db.insert_close_rule.call_args[0][0]
    assert args["trigger_type"] == "BREAKEVEN_TIMEOUT"
    assert args["threshold_value"] == "4.5"
    assert "T" in args["reference_value"]  # ISO timestamp



# ─── update_rule ───────────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_not_found(service, mock_db):
    """Returns None when rule not found."""
    mock_db.get_close_rule.return_value = None
    result = await service.update_rule("acc-1", "rule-x", {"status": "paused"})
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_wrong_account(service, mock_db):
    """Returns None when rule belongs to different account."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "other-acc", "status": "active"}
    result = await service.update_rule("acc-1", "rule-1", {"status": "paused"})
    assert result is None


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_triggered_state(service, mock_db):
    """Raises ValueError when rule is in terminal state."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "acc-1", "status": "triggered", "trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"}
    with pytest.raises(ValueError, match="Cannot update"):
        await service.update_rule("acc-1", "rule-1", {"status": "paused"})


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_invalid_status(service, mock_db):
    """Raises ValueError for invalid status."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "acc-1", "status": "active", "trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"}
    with pytest.raises(ValueError, match="Status must be"):
        await service.update_rule("acc-1", "rule-1", {"status": "invalid"})


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_pct_threshold_over_100(service, mock_db):
    """Raises when percentage threshold exceeds 100."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "acc-1", "status": "active", "trigger_type": "EQUITY_DROP_PCT", "threshold_value": "10"}
    with pytest.raises(ValueError, match="between 0.01 and 100"):
        await service.update_rule("acc-1", "rule-1", {"threshold_value": "101"})


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_no_changes(service, mock_db):
    """Returns existing rule when no fields change."""
    rule = {"id": "rule-1", "account_id": "acc-1", "status": "active", "trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"}
    mock_db.get_close_rule.return_value = rule
    result = await service.update_rule("acc-1", "rule-1", {})
    assert result == rule


@pytest.mark.asyncio(loop_scope="function")
async def test_update_rule_change_type_to_pct_fetches_wallet(service, mock_db, mock_accounts_service):
    """Switching to pct type fetches wallet for reference."""
    mock_db.get_close_rule.return_value = {
        "id": "rule-1", "account_id": "acc-1", "status": "active",
        "trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500",
    }
    await service.update_rule("acc-1", "rule-1", {"trigger_type": "EQUITY_DROP_PCT", "threshold_value": "10"})
    mock_accounts_service.get_wallet.assert_called_with("acc-1")


# ─── delete_rule ───────────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_rule_success(service, mock_db):
    """Deletes rule successfully."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "acc-1"}
    result = await service.delete_rule("acc-1", "rule-1")
    assert result is True


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_rule_not_found(service, mock_db):
    """Returns False when rule doesn't exist."""
    mock_db.get_close_rule.return_value = None
    result = await service.delete_rule("acc-1", "rule-x")
    assert result is False


@pytest.mark.asyncio(loop_scope="function")
async def test_delete_rule_wrong_account(service, mock_db):
    """Returns False when rule belongs to other account."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "other"}
    result = await service.delete_rule("acc-1", "rule-1")
    assert result is False


# ─── list_rules / list_executions ──────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_list_rules(service, mock_db):
    mock_db.list_close_rules.return_value = [{"id": "r1"}]
    result = await service.list_rules("acc-1")
    assert result == [{"id": "r1"}]


@pytest.mark.asyncio(loop_scope="function")
async def test_list_executions(service, mock_db):
    mock_db.list_close_executions.return_value = {"items": [], "total": 0}
    result = await service.list_executions("acc-1", page=2, limit=10)
    mock_db.list_close_executions.assert_called_with("acc-1", 2, 10)
    assert result == {"items": [], "total": 0}


# ─── set_trade_service ─────────────────────────────────────────────────────


def test_set_trade_service(mock_db, mock_accounts_service):
    svc = ClosePositionsService(mock_db, mock_accounts_service)
    assert svc._trade_service is None
    ts = MagicMock()
    svc.set_trade_service(ts)
    assert svc._trade_service is ts


# ─── broadcast error handling ──────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_broadcast_error_swallowed(service, mock_accounts_service, mock_ws_manager):
    """Broadcast errors don't propagate."""
    client = await mock_accounts_service.get_client("acc-1")
    client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    mock_ws_manager.broadcast_to_account.side_effect = RuntimeError("ws fail")
    # Should not raise
    result = await service.close_all_positions("acc-1")
    assert result["closed"] == 1
