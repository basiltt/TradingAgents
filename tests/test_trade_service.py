"""Tests for TradeService — orchestration layer for trade lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.trade_service import TradeService
from backend.services.trade_repository import (
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
)


def _make_trade(**overrides) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "account_id": "acc-1",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "order_type": "market",
        "qty": 0.01,
        "filled_qty": None,
        "entry_price": 50000.0,
        "avg_fill_price": 50000.0,
        "exit_price": None,
        "stop_loss_price": None,
        "take_profit_price": None,
        "leverage": 10,
        "margin_mode": "isolated",
        "status": "open",
        "order_id": "bybit-order-1",
        "order_link_id": str(uuid.uuid4()),
        "close_reason": None,
        "close_rule_id": None,
        "parent_trade_id": None,
        "realized_pnl": None,
        "realized_pnl_pct": None,
        "fees": None,
        "net_pnl": None,
        "source": "manual",
        "source_id": None,
        "version": 1,
        "metadata": "{}",
        "position_idx": 0,
        "opened_at": datetime.now(timezone.utc),
        "closed_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_trade = AsyncMock(return_value=None)
    repo.get_trade_stats = AsyncMock(return_value={
        "total_trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0, "avg_hold_time": None,
    })
    repo.update_trade_status = AsyncMock()
    repo.close_trade = AsyncMock()
    repo.reconcile_close = AsyncMock()
    repo.create_child_trade = AsyncMock()
    repo.get_open_trades = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.pool = pool
    return db


@pytest.fixture
def mock_accounts():
    svc = MagicMock()
    svc.get_client = AsyncMock()
    return svc


@pytest.fixture
def mock_ws():
    ws = MagicMock()
    ws.broadcast_to_account = AsyncMock()
    return ws


@pytest.fixture
def service(mock_db, mock_repo, mock_accounts, mock_ws):
    return TradeService(
        db=mock_db,
        trade_repo=mock_repo,
        accounts_service=mock_accounts,
        ws_manager=mock_ws,
    )


class TestGetCachedStats:
    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_repo(self, service, mock_repo):
        mock_repo.get_trade_stats.return_value = {"total_trades": 5, "win_rate": 0.6}
        result = await service.get_cached_stats("acc-1")
        assert result["total_trades"] == 5
        mock_repo.get_trade_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, service, mock_repo):
        mock_repo.get_trade_stats.return_value = {"total_trades": 5}
        await service.get_cached_stats("acc-1")
        await service.get_cached_stats("acc-1")
        assert mock_repo.get_trade_stats.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, service, mock_repo):
        mock_repo.get_trade_stats.return_value = {"total_trades": 5}
        await service.get_cached_stats("acc-1")
        service._invalidate_stats_cache("acc-1")
        await service.get_cached_stats("acc-1")
        assert mock_repo.get_trade_stats.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_eviction_at_capacity(self, service, mock_repo):
        mock_repo.get_trade_stats.return_value = {"total_trades": 1}
        service._STATS_CACHE_MAX = 3
        await service.get_cached_stats("a")
        await service.get_cached_stats("b")
        await service.get_cached_stats("c")
        assert len(service._stats_cache) == 3
        await service.get_cached_stats("d")
        assert len(service._stats_cache) == 3
        assert "d" in service._stats_cache


class TestCloseSingleTrade:
    @pytest.mark.asyncio
    async def test_trade_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.close_single_trade("acc-1", str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_already_closed_raises(self, service, mock_repo):
        trade = _make_trade(status="closed")
        mock_repo.get_trade.return_value = trade
        with pytest.raises(InvalidStatusTransition):
            await service.close_single_trade("acc-1", str(trade["id"]))

    @pytest.mark.asyncio
    async def test_full_close_success(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={
            "avgPrice": "51000", "cumExecFee": "0.5",
        })
        mock_accounts.get_client.return_value = client
        closed_trade = _make_trade(status="closed", exit_price=51000, realized_pnl=10.0)
        mock_repo.close_trade.return_value = closed_trade

        result = await service.close_single_trade("acc-1", str(trade["id"]))
        assert result["status"] == "closed"
        mock_repo.update_trade_status.assert_awaited_once()
        mock_repo.close_trade.assert_awaited_once()
        mock_ws.broadcast_to_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_close_success(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade(qty=1.0)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={
            "avgPrice": "51000", "cumExecFee": "0.3",
        })
        mock_accounts.get_client.return_value = client
        child = _make_trade(status="closed", qty=0.5)
        mock_repo.create_child_trade.return_value = child

        await service.close_single_trade("acc-1", str(trade["id"]), qty=0.5)
        mock_repo.create_child_trade.assert_awaited_once()
        assert mock_repo.update_trade_status.await_count == 2

    @pytest.mark.asyncio
    async def test_close_failure_position_gone_reconciles(self, service, mock_repo, mock_accounts):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("API error"))
        client.get_positions = AsyncMock(return_value=[])
        mock_accounts.get_client.return_value = client
        mock_repo.reconcile_close.return_value = _make_trade(status="closed")

        with pytest.raises(Exception, match="API error"):
            await service.close_single_trade("acc-1", str(trade["id"]))
        mock_repo.reconcile_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_failure_position_exists_reverts(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("timeout"))
        client.get_positions = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "side": "Buy", "size": "0.01"},
        ])
        mock_accounts.get_client.return_value = client

        with pytest.raises(Exception, match="timeout"):
            await service.close_single_trade("acc-1", str(trade["id"]))
        revert_call = mock_repo.update_trade_status.call_args_list[-1]
        assert revert_call.kwargs["new_status"] == "open"
        mock_ws.broadcast_to_account.assert_awaited()

    @pytest.mark.asyncio
    async def test_close_concurrent_modification(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("fail"))
        client.get_positions = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "side": "Buy", "size": "0.01"},
        ])
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.side_effect = [
            _make_trade(status="closing", version=2),
            ConcurrentModification("modified"),
        ]

        with pytest.raises(Exception, match="fail"):
            await service.close_single_trade("acc-1", str(trade["id"]))

    @pytest.mark.asyncio
    async def test_stats_cache_invalidated_on_close(self, service, mock_repo, mock_accounts):
        mock_repo.get_trade_stats.return_value = {"total_trades": 5}
        await service.get_cached_stats("acc-1")
        assert "acc-1" in service._stats_cache

        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={"avgPrice": "51000", "cumExecFee": "0"})
        mock_accounts.get_client.return_value = client
        mock_repo.close_trade.return_value = _make_trade(status="closed")
        mock_repo.update_trade_status.return_value = _make_trade(status="closing", version=2)

        await service.close_single_trade("acc-1", str(trade["id"]))
        assert "acc-1" not in service._stats_cache


class TestCancelTrade:
    @pytest.mark.asyncio
    async def test_cancel_pending_trade(self, service, mock_repo, mock_accounts):
        trade = _make_trade(status="pending", order_id="ord-1")
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.cancel_order = AsyncMock()
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="cancelled")

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"
        client.cancel_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_partially_filled(self, service, mock_repo, mock_accounts):
        trade = _make_trade(status="partially_filled", filled_qty=0.005, order_id="ord-2")
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.cancel_order = AsyncMock()
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="open")

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_cancel_closed_raises(self, service, mock_repo):
        trade = _make_trade(status="closed")
        mock_repo.get_trade.return_value = trade
        with pytest.raises(InvalidStatusTransition):
            await service.cancel_trade("acc-1", str(trade["id"]))

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.cancel_trade("acc-1", str(uuid.uuid4()))


class TestBroadcastTradeEvent:
    @pytest.mark.asyncio
    async def test_ws_broadcast_on_close(self, service, mock_ws):
        trade = _make_trade(status="closed", realized_pnl=10.0, net_pnl=9.5, close_reason="manual_single")
        await service._broadcast_trade_event("trade.closed", trade)
        mock_ws.broadcast_to_account.assert_awaited_once()
        call_args = mock_ws.broadcast_to_account.call_args
        assert call_args[0][1] == "trade.closed"
        payload = call_args[0][2]
        assert "realized_pnl" in payload
        assert "net_pnl" in payload

    @pytest.mark.asyncio
    async def test_ws_broadcast_fire_and_forget(self, service, mock_ws):
        mock_ws.broadcast_to_account.side_effect = Exception("ws error")
        trade = _make_trade(status="closed", realized_pnl=10.0)
        await service._broadcast_trade_event("trade.closed", trade)

    @pytest.mark.asyncio
    async def test_ws_broadcast_close_failed(self, service, mock_ws):
        trade = _make_trade(metadata={"error_code": "10001"})
        await service._broadcast_trade_event("trade.close_failed", trade)
        mock_ws.broadcast_to_account.assert_awaited_once()
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["error_code"] == "10001"

    @pytest.mark.asyncio
    async def test_no_ws_manager(self, mock_db, mock_repo, mock_accounts):
        svc = TradeService(db=mock_db, trade_repo=mock_repo, accounts_service=mock_accounts)
        trade = _make_trade()
        await svc._broadcast_trade_event("trade.closed", trade)


class TestExtractPnl:
    def test_buy_pnl_calculation(self, service):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "51000", "cumExecFee": "0.5"}, trade, 0.01)
        assert result["exit_price"] == 51000.0
        assert result["realized_pnl"] > 0
        assert result["fees"] == 0.5
        assert result["net_pnl"] == result["realized_pnl"] - result["fees"]

    def test_sell_pnl_calculation(self, service):
        trade = _make_trade(side="Sell", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "49000", "cumExecFee": "0.3"}, trade, 0.01)
        assert result["realized_pnl"] > 0

    def test_zero_entry_price(self, service):
        trade = _make_trade(entry_price=None, avg_fill_price=None, qty=0.01)
        result = service._extract_pnl({"avgPrice": "51000"}, trade)
        assert result["realized_pnl"] == 0.0

    def test_partial_qty_uses_close_qty(self, service):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=1.0)
        result = service._extract_pnl({"avgPrice": "51000", "cumExecFee": "0.1"}, trade, 0.5)
        full_result = service._extract_pnl({"avgPrice": "51000", "cumExecFee": "0.1"}, trade, 1.0)
        assert abs(result["realized_pnl"]) < abs(full_result["realized_pnl"])

    def test_none_cumexecfee_defaults_to_zero(self, service):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "51000", "cumExecFee": None}, trade, 0.01)
        assert result["fees"] == 0.0

    def test_buy_side_loss(self, service):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "49000", "cumExecFee": "0"}, trade, 0.01)
        assert result["realized_pnl"] < 0

    def test_price_fallback_when_no_avg_price(self, service):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"price": "51000", "cumExecFee": "0"}, trade, 0.01)
        assert result["exit_price"] == 51000.0
        assert result["realized_pnl"] > 0

    def test_avg_fill_price_fallback(self, service):
        trade = _make_trade(entry_price=None, avg_fill_price=50000.0, side="Buy", qty=0.01)
        result = service._extract_pnl({"avgPrice": "51000"}, trade, 0.01)
        assert result["realized_pnl"] > 0


class TestCloseTradeRecordOnly:
    @pytest.mark.asyncio
    async def test_close_record_only_success(self, service, mock_repo, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        mock_repo.close_trade.return_value = _make_trade(status="closed")

        result = await service.close_trade_record_only("acc-1", str(trade["id"]))
        assert result["status"] == "closed"
        mock_repo.update_trade_status.assert_awaited_once()
        mock_repo.close_trade.assert_awaited_once()
        mock_ws.broadcast_to_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_record_only_not_found(self, service, mock_repo):
        mock_repo.get_trade.return_value = None
        with pytest.raises(TradeNotFound):
            await service.close_trade_record_only("acc-1", str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_close_record_only_already_closed(self, service, mock_repo):
        trade = _make_trade(status="closed")
        mock_repo.get_trade.return_value = trade
        with pytest.raises(InvalidStatusTransition):
            await service.close_trade_record_only("acc-1", str(trade["id"]))


class TestQtyValidation:
    @pytest.mark.asyncio
    async def test_close_qty_zero_raises(self, service):
        with pytest.raises(ValueError, match="qty must be positive"):
            await service.close_single_trade("acc-1", str(uuid.uuid4()), qty=0)

    @pytest.mark.asyncio
    async def test_close_qty_negative_raises(self, service):
        with pytest.raises(ValueError, match="qty must be positive"):
            await service.close_single_trade("acc-1", str(uuid.uuid4()), qty=-1)

    @pytest.mark.asyncio
    async def test_close_qty_exceeds_remaining_raises(self, service, mock_repo, mock_accounts):
        trade = _make_trade(qty=1.0, filled_qty=0.8)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        mock_accounts.get_client.return_value = client
        with pytest.raises(ValueError, match="exceeds remaining"):
            await service.close_single_trade("acc-1", str(trade["id"]), qty=0.5)


class TestRuleTriggeredClose:
    @pytest.mark.asyncio
    async def test_close_with_rule_reason(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={"avgPrice": "51000", "cumExecFee": "0"})
        mock_accounts.get_client.return_value = client
        mock_repo.close_trade.return_value = _make_trade(status="closed", close_reason="rule_triggered")

        await service.close_single_trade(
            "acc-1", str(trade["id"]), close_reason="rule_triggered", close_rule_id="rule-123",
        )
        close_kwargs = mock_repo.close_trade.call_args.kwargs
        assert close_kwargs["close_reason"] == "rule_triggered"
        assert close_kwargs["close_rule_id"] == "rule-123"


class TestBroadcastOpened:
    @pytest.mark.asyncio
    async def test_ws_broadcast_opened(self, service, mock_ws):
        trade = _make_trade(status="open", entry_price=50000.0)
        await service._broadcast_trade_event("trade.opened", trade)
        mock_ws.broadcast_to_account.assert_awaited_once()
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["data"]["side"] == "Buy"
        assert payload["data"]["qty"] == 0.01
        assert payload["data"]["status"] == "open"

    @pytest.mark.asyncio
    async def test_ws_broadcast_unknown_event_ignored(self, service, mock_ws):
        trade = _make_trade()
        await service._broadcast_trade_event("trade.unknown", trade)
        mock_ws.broadcast_to_account.assert_not_awaited()


class TestCancelBybitFailure:
    @pytest.mark.asyncio
    async def test_cancel_pending_bybit_fails_still_cancels(self, service, mock_repo, mock_accounts):
        trade = _make_trade(status="pending", order_id="ord-1")
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.cancel_order = AsyncMock(side_effect=Exception("API error"))
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="cancelled")

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"


class TestPartialCloseFailure:
    @pytest.mark.asyncio
    async def test_partial_close_bybit_fails_reverts(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade(qty=1.0)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("timeout"))
        client.get_positions = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "side": "Buy", "size": "1.0"},
        ])
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="closing", version=2)

        with pytest.raises(Exception, match="timeout"):
            await service.close_single_trade("acc-1", str(trade["id"]), qty=0.5)
        revert_call = mock_repo.update_trade_status.call_args_list[-1]
        assert revert_call.kwargs["new_status"] == "open"


class TestReconcileFailureFallthrough:
    @pytest.mark.asyncio
    async def test_reconcile_fails_reverts_to_open(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("fail"))
        client.get_positions = AsyncMock(return_value=[])
        mock_accounts.get_client.return_value = client
        mock_repo.reconcile_close.side_effect = Exception("reconcile broke")

        with pytest.raises(Exception, match="fail"):
            await service.close_single_trade("acc-1", str(trade["id"]))
        mock_repo.reconcile_close.assert_awaited_once()
        revert_call = mock_repo.update_trade_status.call_args_list[-1]
        assert revert_call.kwargs["new_status"] == "open"
        mock_ws.broadcast_to_account.assert_awaited()
        bc_args = mock_ws.broadcast_to_account.call_args[0]
        assert bc_args[1] == "trade.close_failed"
        assert bc_args[2]["previous_status"] == "open"


class TestGetPositionsFailure:
    @pytest.mark.asyncio
    async def test_get_positions_fails_reverts_to_open(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(side_effect=Exception("fail"))
        client.get_positions = AsyncMock(side_effect=Exception("network"))
        mock_accounts.get_client.return_value = client

        with pytest.raises(Exception, match="fail"):
            await service.close_single_trade("acc-1", str(trade["id"]))
        revert_call = mock_repo.update_trade_status.call_args_list[-1]
        assert revert_call.kwargs["new_status"] == "open"


class TestCancelNoOrderId:
    @pytest.mark.asyncio
    async def test_cancel_pending_no_order_id(self, service, mock_repo, mock_accounts):
        trade = _make_trade(status="pending", order_id=None)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="cancelled")

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "cancelled"
        client.cancel_order.assert_not_awaited()


class TestGetOpenTrades:
    @pytest.mark.asyncio
    async def test_get_open_trades(self, service, mock_repo):
        trades = [_make_trade(), _make_trade(symbol="ETHUSDT")]
        mock_repo.get_open_trades.return_value = trades
        result = await service.get_open_trades("acc-1")
        assert len(result) == 2
        mock_repo.get_open_trades.assert_awaited_once()


class TestSellSidePnl:
    def test_sell_side_loss(self, service):
        trade = _make_trade(side="Sell", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "51000", "cumExecFee": "0"}, trade, 0.01)
        assert result["realized_pnl"] < 0

    def test_sell_side_profit(self, service):
        trade = _make_trade(side="Sell", entry_price=50000.0, qty=0.01)
        result = service._extract_pnl({"avgPrice": "49000", "cumExecFee": "0"}, trade, 0.01)
        assert result["realized_pnl"] > 0


class TestPartialCloseRemainingQty:
    @pytest.mark.asyncio
    async def test_qty_equal_remaining_does_full_close(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade(qty=1.0, filled_qty=0.5)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={"avgPrice": "51000", "cumExecFee": "0"})
        mock_accounts.get_client.return_value = client
        mock_repo.close_trade.return_value = _make_trade(status="closed")

        await service.close_single_trade("acc-1", str(trade["id"]), qty=0.5)
        mock_repo.close_trade.assert_awaited_once()
        mock_repo.create_child_trade.assert_not_awaited()


class TestNoWsManager:
    @pytest.mark.asyncio
    async def test_close_without_ws(self, mock_db, mock_repo, mock_accounts):
        svc = TradeService(db=mock_db, trade_repo=mock_repo, accounts_service=mock_accounts)
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={"avgPrice": "51000", "cumExecFee": "0"})
        mock_accounts.get_client.return_value = client
        mock_repo.close_trade.return_value = _make_trade(status="closed")

        result = await svc.close_single_trade("acc-1", str(trade["id"]))
        assert result["status"] == "closed"


class TestBroadcastMetadataString:
    @pytest.mark.asyncio
    async def test_metadata_as_json_string(self, service, mock_ws):
        trade = _make_trade(metadata='{"error_code": "30001"}')
        await service._broadcast_trade_event("trade.close_failed", trade)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["error_code"] == "30001"

    @pytest.mark.asyncio
    async def test_metadata_invalid_json(self, service, mock_ws):
        trade = _make_trade(metadata="not-json")
        await service._broadcast_trade_event("trade.close_failed", trade)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["error_code"] == "UNKNOWN"


class TestCancelPartialFilledExchangeFailure:
    @pytest.mark.asyncio
    async def test_cancel_partial_filled_bybit_fails_still_updates(self, service, mock_repo, mock_accounts):
        trade = _make_trade(status="partially_filled", order_id="ord-1", filled_qty=0.005)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.cancel_order = AsyncMock(side_effect=Exception("exchange timeout"))
        mock_accounts.get_client.return_value = client
        updated = _make_trade(status="open", filled_qty=0.005, version=2)
        mock_repo.update_trade_status.return_value = updated

        result = await service.cancel_trade("acc-1", str(trade["id"]))
        assert result["status"] == "open"
        assert result["filled_qty"] == 0.005
        mock_repo.update_trade_status.assert_awaited_once()
        call_kw = mock_repo.update_trade_status.call_args.kwargs
        assert call_kw["new_status"] == "open"
        assert call_kw["updates"]["filled_qty"] == 0.005


class TestCloseTradeCloseRaiseConcurrentMod:
    @pytest.mark.asyncio
    async def test_close_trade_concurrent_mod_propagates(self, service, mock_repo, mock_accounts):
        trade = _make_trade()
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={
            "avgPrice": "51000", "cumExecFee": "0.5",
        })
        mock_accounts.get_client.return_value = client
        mock_repo.update_trade_status.return_value = _make_trade(status="closing", version=2)
        mock_repo.close_trade.side_effect = ConcurrentModification("version mismatch")

        with pytest.raises(ConcurrentModification):
            await service.close_single_trade("acc-1", str(trade["id"]))


class TestFullCloseAssertsPnlArgs:
    @pytest.mark.asyncio
    async def test_full_close_forwards_correct_pnl(self, service, mock_repo, mock_accounts, mock_ws):
        trade = _make_trade(side="Buy", entry_price=50000.0, qty=0.01)
        mock_repo.get_trade.return_value = trade
        client = AsyncMock()
        client.place_market_close_order = AsyncMock(return_value={
            "avgPrice": "51000", "cumExecFee": "0.5",
        })
        mock_accounts.get_client.return_value = client
        mock_repo.close_trade.return_value = _make_trade(status="closed")

        await service.close_single_trade("acc-1", str(trade["id"]))

        call_kw = mock_repo.close_trade.call_args.kwargs
        assert call_kw["exit_price"] == 51000.0
        assert call_kw["realized_pnl"] > 0
        assert call_kw["fees"] == 0.5
        assert call_kw["net_pnl"] == call_kw["realized_pnl"] - call_kw["fees"]
