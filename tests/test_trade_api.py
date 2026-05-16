"""Tests for trade API endpoints in backend.routers.accounts."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.routers.accounts import router, _rate_limiters
from backend.schemas import TradeCloseRequest


def _make_trade(**overrides) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "account_id": "acc-1",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "order_type": "market",
        "qty": 0.01,
        "filled_qty": None,
        "entry_price": None,
        "avg_fill_price": None,
        "exit_price": None,
        "stop_loss_price": None,
        "take_profit_price": None,
        "leverage": 10,
        "margin_mode": "isolated",
        "status": "open",
        "order_id": None,
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
        "opened_at": datetime.now(timezone.utc),
        "closed_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def clear_rate_limiters():
    _rate_limiters.clear()
    yield
    _rate_limiters.clear()


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.list_trades = AsyncMock(return_value={"items": [], "has_more": False, "cursor": None})
    repo.get_open_trades = AsyncMock(return_value=[])
    repo.get_trade_stats = AsyncMock(return_value={
        "total_trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0, "avg_hold_time": None,
    })
    repo.get_trade_with_events = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.pool = pool
    return db


@pytest.fixture
def client(mock_repo, mock_db):
    app = FastAPI()
    app.include_router(router)
    app.state.accounts_service = MagicMock()
    app.state.trade_repo = mock_repo
    app.state.db = mock_db
    app.state.trade_service = None
    return TestClient(app)


@pytest.fixture
def account_id():
    return str(uuid.uuid4())


class TestListTrades:
    def test_list_trades_empty(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["has_more"] is False

    def test_list_trades_with_results(self, client, account_id, mock_repo):
        trade = _make_trade(account_id=account_id)
        mock_repo.list_trades.return_value = {
            "items": [trade], "has_more": False, "cursor": None,
        }
        resp = client.get(f"/accounts/{account_id}/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert isinstance(item["id"], str)
        assert isinstance(item["metadata"], dict)
        assert item["symbol"] == "BTCUSDT"

    def test_list_trades_invalid_metadata_fallback(self, client, account_id, mock_repo):
        trade = _make_trade(account_id=account_id, metadata="not-valid-json")
        mock_repo.list_trades.return_value = {
            "items": [trade], "has_more": False, "cursor": None,
        }
        resp = client.get(f"/accounts/{account_id}/trades")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["metadata"] == {}

    def test_list_trades_include_total(self, client, account_id, mock_repo):
        mock_repo.list_trades.return_value = {
            "items": [], "has_more": False, "cursor": None, "total": 42,
        }
        resp = client.get(f"/accounts/{account_id}/trades?include_total=true")
        assert resp.status_code == 200
        assert resp.json()["total"] == 42

    def test_list_trades_invalid_sort_400(self, client, account_id, mock_repo):
        mock_repo.list_trades.side_effect = ValueError("Invalid sort")
        resp = client.get(f"/accounts/{account_id}/trades?sort=DROP_TABLE")
        assert resp.status_code == 400

    def test_list_trades_invalid_symbol_400(self, client, account_id, mock_repo):
        mock_repo.list_trades.side_effect = ValueError("Invalid symbol")
        resp = client.get(f"/accounts/{account_id}/trades?symbol='; DROP TABLE--")
        assert resp.status_code == 400

    def test_list_trades_invalid_account_id_400(self, client):
        resp = client.get("/accounts/not-a-uuid/trades")
        assert resp.status_code == 400

    def test_list_trades_filter_by_status(self, client, account_id, mock_repo):
        mock_repo.list_trades.return_value = {"items": [], "has_more": False, "cursor": None}
        resp = client.get(f"/accounts/{account_id}/trades?status=open")
        assert resp.status_code == 200
        call_kwargs = mock_repo.list_trades.call_args
        assert call_kwargs[1]["status"] == "open" or call_kwargs.kwargs.get("status") == "open"


    def test_list_trades_pagination_cursor(self, client, account_id, mock_repo):
        trade = _make_trade(account_id=account_id)
        mock_repo.list_trades.return_value = {
            "items": [trade], "has_more": True, "cursor": "abc123",
        }
        resp = client.get(f"/accounts/{account_id}/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_more"] is True
        assert data["cursor"] == "abc123"

    def test_list_trades_cursor_too_long_400(self, client, account_id, mock_repo):
        long_cursor = "A" * 600
        resp = client.get(f"/accounts/{account_id}/trades?cursor={long_cursor}")
        assert resp.status_code == 422

    def test_list_trades_invalid_from_date_400(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades?from_date=not-a-date")
        assert resp.status_code == 400

    def test_list_trades_invalid_to_date_400(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades?to_date=not-a-date")
        assert resp.status_code == 400


class TestGetOpenTrades:
    def test_get_open_trades(self, client, account_id, mock_repo):
        trade = _make_trade(account_id=account_id, status="open")
        mock_repo.get_open_trades.return_value = [trade]
        resp = client.get(f"/accounts/{account_id}/trades/open")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_route_ordering_open_not_captured_as_trade_id(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades/open")
        assert resp.status_code == 200


class TestGetTradeStats:
    def test_get_stats_empty_account(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0

    def test_get_stats_via_trade_service(self, mock_repo, mock_db, account_id):
        app = FastAPI()
        app.include_router(router)
        app.state.accounts_service = MagicMock()
        app.state.trade_repo = mock_repo
        app.state.db = mock_db
        trade_svc = MagicMock()
        trade_svc.get_cached_stats = AsyncMock(return_value={
            "total_trades": 5, "win_rate": 0.6, "avg_pnl": 10.0,
            "total_pnl": 50.0, "avg_hold_time": 3600.0,
        })
        app.state.trade_service = trade_svc
        tc = TestClient(app)
        resp = tc.get(f"/accounts/{account_id}/trades/stats")
        assert resp.status_code == 200
        assert resp.json()["total_trades"] == 5
        trade_svc.get_cached_stats.assert_awaited_once()


class TestGetTradeDetail:
    def test_get_trade_not_found_404(self, client, account_id):
        tid = str(uuid.uuid4())
        resp = client.get(f"/accounts/{account_id}/trades/{tid}")
        assert resp.status_code == 404
        assert resp.json()["code"] == "TRADE_NOT_FOUND"

    def test_get_trade_detail_with_events(self, client, account_id, mock_repo):
        tid = uuid.uuid4()
        trade = _make_trade(id=tid, account_id=account_id)
        trade["events"] = [{"id": 1, "trade_id": tid, "event_type": "placed",
                            "old_status": None, "new_status": "pending",
                            "actor": "user", "payload": {}, "created_at": datetime.now(timezone.utc)}]
        mock_repo.get_trade_with_events.return_value = trade
        resp = client.get(f"/accounts/{account_id}/trades/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) == 1

    def test_get_trade_invalid_trade_id_400(self, client, account_id):
        resp = client.get(f"/accounts/{account_id}/trades/not-a-uuid")
        assert resp.status_code == 400

    def test_get_trade_idor_404(self, client, mock_repo):
        aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        mock_repo.get_trade_with_events.return_value = None
        resp = client.get(f"/accounts/{aid}/trades/{tid}")
        assert resp.status_code == 404
        call_args = mock_repo.get_trade_with_events.call_args
        assert call_args.kwargs["account_id"] == aid


class TestCloseTrade:
    def test_close_trade_no_service_503(self, client, account_id):
        tid = str(uuid.uuid4())
        resp = client.post(f"/accounts/{account_id}/trades/{tid}/close")
        assert resp.status_code == 503
        assert resp.json()["code"] == "SERVICE_UNAVAILABLE"

    def test_close_trade_invalid_trade_id_400(self, client, account_id):
        resp = client.post(f"/accounts/{account_id}/trades/not-a-uuid/close")
        assert resp.status_code == 400

    def test_close_request_qty_validation(self):
        with pytest.raises(ValidationError):
            TradeCloseRequest(qty=0)
        with pytest.raises(ValidationError):
            TradeCloseRequest(qty=-1)
        req = TradeCloseRequest(qty=5.0)
        assert req.qty == 5.0
        req_none = TradeCloseRequest()
        assert req_none.qty is None

    @pytest.mark.skip(reason="Requires full TradeService integration test setup")
    def test_close_trade_success(self, client, account_id):
        pass

    @pytest.mark.skip(reason="Requires full TradeService integration test setup")
    def test_close_trade_already_closed_409(self, client, account_id):
        pass

    @pytest.mark.skip(reason="Requires full TradeService integration test setup")
    def test_close_trade_partial(self, client, account_id):
        pass


class TestCancelTrade:
    def test_cancel_trade_no_service_503(self, client, account_id):
        tid = str(uuid.uuid4())
        resp = client.post(f"/accounts/{account_id}/trades/{tid}/cancel")
        assert resp.status_code == 503
        assert resp.json()["code"] == "SERVICE_UNAVAILABLE"

    def test_cancel_trade_invalid_trade_id_400(self, client, account_id):
        resp = client.post(f"/accounts/{account_id}/trades/not-a-uuid/cancel")
        assert resp.status_code == 400

    @pytest.mark.skip(reason="Requires full TradeService integration test setup")
    def test_cancel_pending_trade(self, client, account_id):
        pass

    @pytest.mark.skip(reason="Requires full TradeService integration test setup")
    def test_cancel_partially_filled(self, client, account_id):
        pass


class TestRateLimiter:
    def test_rate_limit_429(self, client, account_id):
        tid = str(uuid.uuid4())
        for _ in range(10):
            client.post(f"/accounts/{account_id}/trades/{tid}/close")
        resp = client.post(f"/accounts/{account_id}/trades/{tid}/close")
        assert resp.status_code == 429

    def test_rate_limit_isolation_per_account(self, client):
        aid_a = str(uuid.uuid4())
        aid_b = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        for _ in range(10):
            client.post(f"/accounts/{aid_a}/trades/{tid}/close")
        resp = client.post(f"/accounts/{aid_b}/trades/{tid}/close")
        assert resp.status_code != 429

    def test_rate_limit_recovery_after_refill(self, client, account_id):
        tid = str(uuid.uuid4())
        for _ in range(10):
            client.post(f"/accounts/{account_id}/trades/{tid}/close")
        resp = client.post(f"/accounts/{account_id}/trades/{tid}/close")
        assert resp.status_code == 429
        bucket = _rate_limiters[account_id]
        bucket.tokens = 10.0
        resp = client.post(f"/accounts/{account_id}/trades/{tid}/close")
        assert resp.status_code != 429

    def test_rate_limit_eviction_stale_entries(self, client):
        from backend.routers.accounts import _RATE_LIMITER_MAX_ENTRIES, _TokenBucket
        _rate_limiters.clear()
        now = time.monotonic()
        for i in range(_RATE_LIMITER_MAX_ENTRIES):
            bucket = _TokenBucket()
            bucket.last_refill = now - 7200
            _rate_limiters[f"stale-{i}"] = bucket
        assert len(_rate_limiters) == _RATE_LIMITER_MAX_ENTRIES
        new_aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        resp = client.post(f"/accounts/{new_aid}/trades/{tid}/close")
        assert len(_rate_limiters) < _RATE_LIMITER_MAX_ENTRIES
        assert resp.status_code != 429

    def test_rate_limit_capacity_exceeded_non_stale(self, client):
        from backend.routers.accounts import _RATE_LIMITER_MAX_ENTRIES, _TokenBucket
        _rate_limiters.clear()
        for i in range(_RATE_LIMITER_MAX_ENTRIES):
            _rate_limiters[f"fresh-{i}"] = _TokenBucket()
        new_aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        resp = client.post(f"/accounts/{new_aid}/trades/{tid}/close")
        assert resp.status_code == 429
