"""Tests for ClosePositionsService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.close_positions_service import ClosePositionsService, MAX_RULES_PER_ACCOUNT


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.insert_close_execution.return_value = {"id": "exec-1"}
    db.get_account.return_value = {"id": "acc-1", "name": "Test"}
    db.count_rules_for_account.return_value = 0
    db.insert_close_rule.return_value = {"id": "rule-1", "status": "active"}
    db.get_close_rule.return_value = None
    db.delete_close_rule.return_value = True
    return db


@pytest.fixture
def mock_accounts():
    svc = MagicMock()
    client = AsyncMock()
    client.get_positions.return_value = []
    client.place_market_close_order.return_value = {"orderId": "ord-1"}
    svc.get_client = AsyncMock(return_value=client)
    svc.get_wallet = AsyncMock(return_value={"totalEquity": "1000"})
    svc.invalidate_cache = MagicMock()
    return svc


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    return ws


@pytest.fixture
def mock_trade_service():
    ts = MagicMock()
    ts.get_open_trades = AsyncMock(return_value=[])
    ts.close_trade_record_only = AsyncMock()
    ts._invalidate_stats_cache = MagicMock()
    return ts


@pytest.fixture
def service(mock_db, mock_accounts, mock_ws, mock_trade_service):
    return ClosePositionsService(mock_db, mock_accounts, mock_ws, mock_trade_service)


# ── close_all_positions ──────────────────────────────────────


@pytest.mark.asyncio
async def test_close_all_positions_happy_path(service, mock_accounts, mock_db):
    """Positions exist, all closed successfully."""
    client = await mock_accounts.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "positionIdx": 0},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0", "positionIdx": 0},
    ]

    result = await service.close_all_positions("acc-1")

    assert result["total"] == 2
    assert result["closed"] == 2
    assert result["failed"] == 0
    assert result["execution_id"] == "exec-1"
    assert len(result["results"]) == 2
    mock_db.insert_close_execution.assert_called_once()
    mock_accounts.invalidate_cache.assert_called_once_with("acc-1")


@pytest.mark.asyncio
async def test_close_all_positions_empty(service, mock_db):
    """No positions returns zeros and still records execution."""
    result = await service.close_all_positions("acc-1")

    assert result["total"] == 0
    assert result["closed"] == 0
    assert result["failed"] == 0
    assert result["execution_id"] == "exec-1"
    mock_db.insert_close_execution.assert_called_once()


@pytest.mark.asyncio
async def test_close_all_positions_reentrancy_guard(service):
    """Calling close while already closing raises ValueError."""
    service._closing_accounts.add("acc-1")

    with pytest.raises(ValueError, match="Close already in progress"):
        await service.close_all_positions("acc-1")


@pytest.mark.asyncio
async def test_close_all_positions_guard_cleanup_on_error(service, mock_accounts):
    """Guard is removed even when an exception occurs."""
    client = await mock_accounts.get_client("acc-1")
    client.get_positions.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await service.close_all_positions("acc-1")

    assert "acc-1" not in service._closing_accounts


@pytest.mark.asyncio
async def test_close_all_positions_with_failures(service, mock_accounts):
    """Mixed success/failure results are counted correctly."""
    client = await mock_accounts.get_client("acc-1")
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0"},
    ]
    # First call succeeds, second raises generic exception
    client.place_market_close_order.side_effect = [
        {"orderId": "ord-1"},
        Exception("network error"),
    ]

    result = await service.close_all_positions("acc-1")

    assert result["closed"] == 1
    assert result["failed"] == 1


# ── create_rule ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule_happy_path(service, mock_db):
    """Creates a rule and returns the row."""
    rule_data = {"trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"}
    result = await service.create_rule("acc-1", rule_data)

    assert result["id"] == "rule-1"
    mock_db.insert_close_rule.assert_called_once()


@pytest.mark.asyncio
async def test_create_rule_account_not_found(service, mock_db):
    """Raises ValueError when account doesn't exist."""
    mock_db.get_account.return_value = None

    with pytest.raises(ValueError, match="Account not found"):
        await service.create_rule("bad-id", {"trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"})


@pytest.mark.asyncio
async def test_create_rule_max_rules_exceeded(service, mock_db):
    """Raises ValueError when rule limit is reached."""
    mock_db.count_rules_for_account.return_value = MAX_RULES_PER_ACCOUNT

    with pytest.raises(ValueError, match="Maximum"):
        await service.create_rule("acc-1", {"trigger_type": "EQUITY_DROP_ABS", "threshold_value": "500"})


@pytest.mark.asyncio
async def test_create_rule_pct_type_auto_reference(service, mock_db, mock_accounts):
    """Percentage rules auto-populate reference_value from wallet equity."""
    rule_data = {"trigger_type": "EQUITY_DROP_PCT", "threshold_value": "10"}
    await service.create_rule("acc-1", rule_data)

    call_args = mock_db.insert_close_rule.call_args[0][0]
    assert call_args["reference_value"] == "1000"


# ── delete_rule ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_rule_not_found(service, mock_db):
    """Returns False when rule doesn't exist."""
    mock_db.get_close_rule.return_value = None

    result = await service.delete_rule("acc-1", "no-such-rule")
    assert result is False


@pytest.mark.asyncio
async def test_delete_rule_wrong_account(service, mock_db):
    """Returns False when rule belongs to different account."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "other-acc"}

    result = await service.delete_rule("acc-1", "rule-1")
    assert result is False


@pytest.mark.asyncio
async def test_delete_rule_success(service, mock_db):
    """Returns True on successful deletion."""
    mock_db.get_close_rule.return_value = {"id": "rule-1", "account_id": "acc-1"}

    result = await service.delete_rule("acc-1", "rule-1")
    assert result is True
    mock_db.delete_close_rule.assert_called_once_with("rule-1")
