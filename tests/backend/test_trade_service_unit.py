"""Comprehensive unit tests for TradeService."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.trade_repository import (
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
)
from backend.services.trade_service import TradeService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> dict:
    """Factory for trade dicts."""
    base = {
        "id": uuid.uuid4(),
        "account_id": "acc-1",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "qty": "1.0",
        "filled_qty": "0",
        "entry_price": "50000",
        "avg_fill_price": "50000",
        "status": "open",
        "version": 1,
        "position_idx": 0,
        "order_id": "order-123",
        "close_reason": None,
        "realized_pnl": None,
        "net_pnl": None,
        "metadata": None,
    }
    base.update(overrides)
    return base


class _AsyncCtx:
    """Helper async context manager that yields a fixed value."""
    def __init__(self, value):
        self._value = value
    async def __aenter__(self):
        return self._value
    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    db.pool.acquire.return_value = _AsyncCtx(conn)
    # conn.transaction() must return an async context manager (not a coroutine)
    conn.transaction = MagicMock(return_value=_AsyncCtx(None))
    return db, conn


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_accounts():
    svc = AsyncMock()
    client = AsyncMock()
    svc.get_client.return_value = client
    return svc, client


@pytest.fixture
def mock_ws():
    return AsyncMock()


@pytest.fixture
def service(mock_db, mock_repo, mock_accounts, mock_ws):
    db, _ = mock_db
    accounts_svc, _ = mock_accounts
    return TradeService(
        db=db,
        trade_repo=mock_repo,
        accounts_service=accounts_svc,
        ws_manager=mock_ws,
    )


# ---------------------------------------------------------------------------
# get_cached_stats
# ---------------------------------------------------------------------------

class TestGetCachedStats:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_fetches_from_repo_on_cache_miss(self, service, mock_db, mock_repo):
        _, conn = mock_db
        mock_repo.get_trade_stats.return_value = {"total": 5, "win_rate": 0.6}
        result = await service.get_cached_stats("acc-1")
        assert result == {"total": 5, "win_rate": 0.6}
        mock_repo.get_trade_stats.assert_awaited_once_with(conn, account_id="acc-1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_cached_value_within_ttl(self, service, mock_db, mock_repo):
        _, conn = mock_db
        mock_repo.get_trade_stats.return_value = {"total": 5}
        await service.get_cached_stats("acc-1")
        mock_repo.get_trade_stats.reset_mock()
        result = await service.get_cached_stats("acc-1")
        assert result == {"total": 5}
        mock_repo.get_trade_stats.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_refetches_after_ttl_expires(self, service, mock_db, mock_repo):
        _, conn = mock_db
        mock_repo.get_trade_stats.return_value = {"total": 5}
        await service.get_cached_stats("acc-1")
        # Manually expire the cache entry
        key_data = service._stats_cache["acc-1"]
        service._stats_cache["acc-1"] = (key_data[0] - 20.0, key_data[1])
        mock_repo.get_trade_stats.return_value = {"total": 10}
        result = await service.get_cached_stats("acc-1")
        assert result == {"total": 10}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cache_evicts_oldest_when_full(self, service, mock_db, mock_repo):
        mock_repo.get_trade_stats.return_value = {"total": 1}
        service._STATS_CACHE_MAX = 2
        await service.get_cached_stats("a1")
        await service.get_cached_stats("a2")
        await service.get_cached_stats("a3")
        assert "a1" not in service._stats_cache
        assert "a3" in service._stats_cache


class TestInvalidateStatsCache:
    def test_removes_existing_entry(self, service):
        service._stats_cache["acc-1"] = (time.monotonic(), {"total": 5})
        service.invalidate_stats_cache("acc-1")
        assert "acc-1" not in service._stats_cache

    def test_noop_for_missing_key(self, service):
        service.invalidate_stats_cache("nonexistent")  # no error


# ---------------------------------------------------------------------------
# get_open_trades
# ---------------------------------------------------------------------------

class TestGetOpenTrades:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_trades(self, service, mock_db, mock_repo):
        _, conn = mock_db
        mock_repo.get_open_trades.return_value = [{"id": "t1"}, {"id": "t2"}]
        result = await service.get_open_trades("acc-1")
        assert len(result) == 2
        mock_repo.get_open_trades.assert_awaited_once_with(conn, account_id="acc-1", limit=500)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_custom_limit(self, service, mock_db, mock_repo):
        _, conn = mock_db
        mock_repo.get_open_trades.return_value = []
        await service.get_open_trades("acc-1", limit=10)
        mock_repo.get_open_trades.assert_awaited_once_with(conn, account_id="acc-1", limit=10)


# ---------------------------------------------------------------------------
# close_single_trade
# ---------------------------------------------------------------------------

class TestCloseSingleTrade:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_value_error_for_zero_qty(self, service):
        with pytest.raises(ValueError, match="qty must be positive"):
            await service.close_single_trade("acc-1", "t1", qty=0)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_value_error_for_negative_qty(self, service):
        with pytest.raises(ValueError, match="qty must be positive"):
            await service.close_single_trade("acc-1", "t1", qty=-1)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_trade_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.close_single_trade("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_invalid_status_for_closed_trade(self, service, mock_repo):
        mock_repo.get_trade.return_value = _make_trade(status="closed")
        with pytest.raises(InvalidStatusTransition, match="already closed"):
            await service.close_single_trade("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_invalid_status_for_zero_remaining(self, service, mock_repo):
        mock_repo.get_trade.return_value = _make_trade(qty="1.0", filled_qty="1.0")
        with pytest.raises(InvalidStatusTransition, match="No remaining"):
            await service.close_single_trade("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_freshly_opened_trade_is_closeable(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        """REGRESSION: a normally-opened trade has filled_qty==0 (nothing closed yet),
        so remaining == qty and the manual-close endpoint must succeed. This guards
        the CRITICAL bug where place_trade wrote filled_qty = entry-qty (== qty),
        making remaining == 0 and rejecting EVERY full close with "No remaining
        quantity to close". filled_qty means CUMULATIVE-CLOSED, not entry fill."""
        _, client = mock_accounts
        # filled_qty="0" is exactly what place_trade now writes at open.
        trade = _make_trade(qty="1.0", filled_qty="0")
        mock_repo.get_trade.return_value = trade
        mock_repo.update_trade_status.return_value = trade
        mock_repo.close_trade.return_value = {**trade, "status": "closed", "realized_pnl": "10", "net_pnl": "9"}
        client.place_market_close_order.return_value = {"avgPrice": "51000", "cumExecFee": "5", "cumExecQty": "1.0"}

        result = await service.close_single_trade("acc-1", str(trade["id"]))
        assert result["status"] == "closed"
        client.place_market_close_order.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_value_error_qty_exceeds_remaining(self, service, mock_repo):
        mock_repo.get_trade.return_value = _make_trade(qty="1.0", filled_qty="0.5")
        with pytest.raises(ValueError, match="exceeds remaining"):
            await service.close_single_trade("acc-1", "t1", qty=0.8)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_full_close_happy_path(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, conn = mock_db
        _, client = mock_accounts
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        mock_repo.update_trade_status.return_value = trade
        closed_trade = {**trade, "status": "closed", "realized_pnl": "100", "net_pnl": "95"}
        mock_repo.close_trade.return_value = closed_trade
        client.place_market_close_order.return_value = {"avgPrice": "51000", "cumExecFee": "5", "cumExecQty": "1.0"}

        result = await service.close_single_trade("acc-1", str(trade["id"]))
        assert result["status"] == "closed"
        client.place_market_close_order.assert_awaited_once()
        mock_ws.broadcast_to_account.assert_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_partial_close_happy_path(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, conn = mock_db
        _, client = mock_accounts
        trade = _make_trade(qty="2.0", filled_qty="0")
        mock_repo.get_trade.return_value = trade
        mock_repo.update_trade_status.return_value = {**trade, "version": 2}
        child = {**trade, "id": uuid.uuid4(), "qty": "0.5", "status": "closed", "net_pnl": "50"}
        mock_repo.create_child_trade.return_value = child
        client.place_market_close_order.return_value = {"avgPrice": "51000", "cumExecFee": "2", "cumExecQty": "0.5"}

        result = await service.close_single_trade("acc-1", str(trade["id"]), qty=0.5)
        assert result["id"] == child["id"]


# ---------------------------------------------------------------------------
# close_trade_record_only
# ---------------------------------------------------------------------------

class TestCloseTradeRecordOnly:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_trade_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.close_trade_record_only("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_invalid_status(self, service, mock_repo):
        mock_repo.get_trade.return_value = _make_trade(status="cancelled")
        with pytest.raises(InvalidStatusTransition):
            await service.close_trade_record_only("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_happy_path_without_exchange_result(self, service, mock_db, mock_repo, mock_ws):
        _, conn = mock_db
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        closed = {**trade, "status": "closed", "realized_pnl": 0, "net_pnl": 0}
        mock_repo.update_trade_status.return_value = trade
        mock_repo.close_trade.return_value = closed

        result = await service.close_trade_record_only("acc-1", str(trade["id"]))
        assert result["status"] == "closed"
        mock_ws.broadcast_to_account.assert_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_happy_path_with_exchange_result(self, service, mock_db, mock_repo, mock_ws):
        _, conn = mock_db
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        closed = {**trade, "status": "closed", "realized_pnl": "1000", "net_pnl": "995"}
        mock_repo.update_trade_status.return_value = trade
        mock_repo.close_trade.return_value = closed

        exchange_result = {"avgPrice": "51000", "cumExecFee": "5"}
        result = await service.close_trade_record_only(
            "acc-1", str(trade["id"]), exchange_result=exchange_result
        )
        assert result["status"] == "closed"


# ---------------------------------------------------------------------------
# cancel_trade
# ---------------------------------------------------------------------------

class TestCancelTrade:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_trade_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.cancel_trade("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_raises_invalid_status_for_open(self, service, mock_repo):
        mock_repo.get_trade.return_value = _make_trade(status="open")
        with pytest.raises(InvalidStatusTransition, match="Cannot cancel"):
            await service.cancel_trade("acc-1", "t1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_pending_with_order(self, service, mock_repo, mock_accounts):
        _, client = mock_accounts
        trade = _make_trade(status="pending", order_id="ord-1")
        mock_repo.get_trade.return_value = trade
        updated = {**trade, "status": "cancelled", "version": 2}
        mock_repo.update_trade_status.return_value = updated

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"
        client.cancel_order.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_pending_without_order(self, service, mock_repo, mock_accounts):
        _, client = mock_accounts
        trade = _make_trade(status="pending", order_id=None)
        mock_repo.get_trade.return_value = trade
        updated = {**trade, "status": "cancelled", "version": 2}
        mock_repo.update_trade_status.return_value = updated

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"
        client.cancel_order.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_partially_filled(self, service, mock_repo, mock_accounts):
        _, client = mock_accounts
        trade = _make_trade(status="partially_filled", filled_qty="0.3")
        mock_repo.get_trade.return_value = trade
        updated = {**trade, "status": "open", "version": 2}
        mock_repo.update_trade_status.return_value = updated

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "open"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_handles_exchange_failure_gracefully(self, service, mock_repo, mock_accounts):
        _, client = mock_accounts
        trade = _make_trade(status="pending", order_id="ord-1")
        mock_repo.get_trade.return_value = trade
        client.cancel_order.side_effect = Exception("Network error")
        updated = {**trade, "status": "cancelled", "version": 2}
        mock_repo.update_trade_status.return_value = updated

        # Should NOT raise - exchange cancel failure is logged but not propagated
        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"


# ---------------------------------------------------------------------------
# _extract_pnl
# ---------------------------------------------------------------------------

class TestExtractPnl:
    def test_buy_side_profit(self, service):
        trade = _make_trade(side="Buy", entry_price="50000", qty="1.0")
        result = {"avgPrice": "51000", "cumExecFee": "10"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["exit_price"] == 51000.0
        assert pnl["realized_pnl"] == 1000.0
        assert pnl["fees"] == 10.0
        assert pnl["net_pnl"] == 990.0

    def test_sell_side_profit(self, service):
        trade = _make_trade(side="Sell", entry_price="50000", qty="1.0")
        result = {"avgPrice": "49000", "cumExecFee": "5"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["realized_pnl"] == 1000.0
        assert pnl["net_pnl"] == 995.0

    def test_buy_side_loss(self, service):
        trade = _make_trade(side="Buy", entry_price="50000", qty="1.0")
        result = {"avgPrice": "49000", "cumExecFee": "5"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["realized_pnl"] == -1000.0

    def test_partial_qty_override(self, service):
        trade = _make_trade(side="Buy", entry_price="50000", qty="2.0")
        result = {"avgPrice": "51000", "cumExecFee": "5"}
        pnl = service._extract_pnl(result, trade, close_qty=0.5)
        assert pnl["realized_pnl"] == 500.0

    def test_zero_exit_price(self, service):
        trade = _make_trade(side="Buy", entry_price="50000", qty="1.0")
        result = {"avgPrice": "0", "cumExecFee": "0"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["realized_pnl"] == 0.0
        assert pnl["fees"] == 0.0

    def test_zero_entry_price(self, service):
        trade = _make_trade(side="Buy", entry_price="0", qty="1.0")
        result = {"avgPrice": "51000", "cumExecFee": "5"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["realized_pnl"] == 0.0

    def test_uses_price_fallback(self, service):
        trade = _make_trade(side="Buy", entry_price="50000", qty="1.0")
        result = {"price": "51000", "cumExecFee": "0"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["exit_price"] == 51000.0

    def test_pnl_pct_calculation(self, service):
        trade = _make_trade(side="Buy", entry_price="100", qty="1.0")
        result = {"avgPrice": "110", "cumExecFee": "0"}
        pnl = service._extract_pnl(result, trade)
        assert pnl["realized_pnl_pct"] == 10.0


# ---------------------------------------------------------------------------
# _broadcast_trade_event
# ---------------------------------------------------------------------------

class TestBroadcastTradeEvent:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_noop_when_no_ws_manager(self, mock_db, mock_repo, mock_accounts):
        db, _ = mock_db
        accounts_svc, _ = mock_accounts
        svc = TradeService(db=db, trade_repo=mock_repo, accounts_service=accounts_svc, ws_manager=None)
        # Should not raise
        await svc._broadcast_trade_event("trade.opened", _make_trade())

    @pytest.mark.asyncio(loop_scope="function")
    async def test_trade_opened_event(self, service, mock_ws):
        trade = _make_trade()
        await service._broadcast_trade_event("trade.opened", trade)
        mock_ws.broadcast_to_account.assert_awaited_once()
        call_args = mock_ws.broadcast_to_account.call_args
        assert call_args[0][1] == "trade.opened"
        payload = call_args[0][2]
        assert "data" in payload
        assert payload["trade_id"] == str(trade["id"])

    @pytest.mark.asyncio(loop_scope="function")
    async def test_trade_closed_event(self, service, mock_ws):
        trade = _make_trade(realized_pnl="100", net_pnl="95", close_reason="manual")
        await service._broadcast_trade_event("trade.closed", trade)
        call_args = mock_ws.broadcast_to_account.call_args
        payload = call_args[0][2]
        assert payload["realized_pnl"] == 100.0
        assert payload["net_pnl"] == 95.0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_trade_close_failed_event(self, service, mock_ws):
        trade = _make_trade(
            metadata=json.dumps({"error_code": "RATE_LIMIT", "error_message": "Too fast"}),
            _previous_status="open",
        )
        await service._broadcast_trade_event("trade.close_failed", trade)
        call_args = mock_ws.broadcast_to_account.call_args
        payload = call_args[0][2]
        assert payload["error_code"] == "RATE_LIMIT"
        assert payload["error_message"] == "Too fast"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_failed_with_string_metadata(self, service, mock_ws):
        trade = _make_trade(metadata='{"error_code": "X"}', _previous_status="open")
        await service._broadcast_trade_event("trade.close_failed", trade)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["error_code"] == "X"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_failed_with_invalid_metadata(self, service, mock_ws):
        trade = _make_trade(metadata="not-json{", _previous_status="open")
        await service._broadcast_trade_event("trade.close_failed", trade)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["error_code"] == "UNKNOWN"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unknown_event_type_does_nothing(self, service, mock_ws):
        await service._broadcast_trade_event("trade.unknown", _make_trade())
        mock_ws.broadcast_to_account.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_version_override(self, service, mock_ws):
        trade = _make_trade(version=5)
        await service._broadcast_trade_event("trade.opened", trade, version_override=99)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["version"] == 99

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ws_exception_is_swallowed(self, service, mock_ws):
        mock_ws.broadcast_to_account.side_effect = RuntimeError("ws down")
        # Should NOT raise
        await service._broadcast_trade_event("trade.opened", _make_trade())


# ---------------------------------------------------------------------------
# _handle_close_failure
# ---------------------------------------------------------------------------

class TestHandleCloseFailure:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_reverts_to_open_when_position_exists(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, client = mock_accounts
        trade = _make_trade(status="closing")
        client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy"}]
        updated = {**trade, "status": "open", "version": 3}
        mock_repo.update_trade_status.return_value = updated

        await service._handle_close_failure(client, trade, version=2)
        mock_repo.update_trade_status.assert_called()
        mock_ws.broadcast_to_account.assert_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reconciles_when_position_gone(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, client = mock_accounts
        trade = _make_trade(status="closing")
        client.get_positions.return_value = []  # position gone

        await service._handle_close_failure(client, trade, version=2)
        mock_repo.reconcile_close.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handles_position_check_failure(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, client = mock_accounts
        trade = _make_trade(status="closing")
        client.get_positions.side_effect = Exception("Network")
        updated = {**trade, "status": "open", "version": 3}
        mock_repo.update_trade_status.return_value = updated

        await service._handle_close_failure(client, trade, version=2)
        # Falls through to revert since position_gone=False
        mock_repo.update_trade_status.assert_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handles_concurrent_modification_on_revert(self, service, mock_db, mock_repo, mock_accounts, mock_ws):
        _, client = mock_accounts
        trade = _make_trade(status="closing")
        client.get_positions.return_value = [{"symbol": "BTCUSDT", "side": "Buy"}]
        mock_repo.update_trade_status.side_effect = ConcurrentModification("conflict")

        # Should not raise
        await service._handle_close_failure(client, trade, version=2)
        mock_ws.broadcast_to_account.assert_not_awaited()
