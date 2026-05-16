"""Tests for cross-account trades endpoints (backend/routers/trades.py)."""

import uuid
from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ACCT_A = "00000000-0000-4000-8000-000000000001"
_ACCT_B = "00000000-0000-4000-8000-000000000002"
_TRADE_1 = str(uuid.uuid4())
_TRADE_2 = str(uuid.uuid4())


def _make_trade(*, account_id=_ACCT_A, status="open", symbol="BTC/USDT",
                side="Buy", realized_pnl=None, version=1, **kw):
    return {
        "id": uuid.UUID(kw.get("id", str(uuid.uuid4()))),
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "order_type": "Market",
        "qty": 1.0,
        "filled_qty": 1.0,
        "entry_price": 50000.0,
        "avg_fill_price": 50000.0,
        "exit_price": None,
        "stop_loss_price": None,
        "take_profit_price": None,
        "leverage": 1,
        "status": status,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": None,
        "fees": None,
        "net_pnl": realized_pnl,
        "source": "manual",
        "close_reason": None,
        "version": version,
        "opened_at": "2026-01-01T00:00:00Z",
        "closed_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "parent_trade_id": None,
        "metadata": None,
        "margin_mode": "cross",
        "position_idx": 0,
        "order_id": None,
        "mark_price_at_open": None,
        "order_link_id": None,
        "source_id": None,
        "close_rule_id": None,
        **kw,
    }


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    db.pool.acquire.return_value = cm
    return db, conn


@pytest.fixture
def mock_accounts_svc():
    svc = MagicMock()
    svc.list_accounts = AsyncMock(return_value=[
        {"id": _ACCT_A}, {"id": _ACCT_B},
    ])
    svc.get_positions = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def app(mock_repo, mock_db, mock_accounts_svc):
    from backend.routers.trades import router as trades_router
    app = FastAPI()
    app.include_router(trades_router)
    app.state.trade_repo = mock_repo
    db, _ = mock_db
    app.state.db = db
    app.state.accounts_service = mock_accounts_svc
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def conn(mock_db):
    _, c = mock_db
    return c


class TestListTradesCrossAccount:
    def test_no_filter(self, client, mock_repo, conn):
        trades = [_make_trade(account_id=_ACCT_A), _make_trade(account_id=_ACCT_B)]
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": trades, "cursor": None, "has_more": False,
        })
        resp = client.get("/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is False

    def test_filter_by_account(self, client, mock_repo, conn):
        trades = [_make_trade(account_id=_ACCT_A)]
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": trades, "cursor": None, "has_more": False,
        })
        resp = client.get(f"/trades?account_id={_ACCT_A}")
        assert resp.status_code == 200
        call_kw = mock_repo.list_trades_cross_account.call_args
        account_ids = call_kw.kwargs.get("account_ids", [])
        assert _ACCT_A in account_ids

    def test_filter_by_status(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades?status=open,closed")
        assert resp.status_code == 200

    def test_filter_by_symbol(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades?symbol=BTC/USDT")
        assert resp.status_code == 200

    def test_filter_by_side_case_insensitive(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        for s in ["buy", "BUY", "Buy"]:
            resp = client.get(f"/trades?side={s}")
            assert resp.status_code == 200

    def test_filter_by_date_range(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades?from_date=2026-01-01T00:00:00Z&to_date=2026-12-31T23:59:59Z")
        assert resp.status_code == 200

    def test_sort_by_realized_pnl(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades?sort_by=realized_pnl")
        assert resp.status_code == 200

    def test_cursor_pagination(self, client, mock_repo, conn):
        cursor = b64encode(b"2026-01-01T00:00:00Z|00000000-0000-4000-8000-000000000001").decode()
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get(f"/trades?cursor={cursor}")
        assert resp.status_code == 200

    def test_invalid_account_id(self, client, mock_repo):
        resp = client.get("/trades?account_id=not-a-uuid")
        assert resp.status_code == 422

    def test_invalid_status(self, client, mock_repo):
        resp = client.get("/trades?status=bogus")
        assert resp.status_code == 422

    def test_invalid_symbol(self, client, mock_repo):
        resp = client.get("/trades?symbol=!!!")
        assert resp.status_code == 422

    def test_invalid_sort_by(self, client, mock_repo):
        resp = client.get("/trades?sort_by=unknown_col")
        assert resp.status_code == 422

    def test_invalid_cursor(self, client, mock_repo, conn):
        resp = client.get("/trades?cursor=not_base64!!!")
        assert resp.status_code == 422

    def test_max_50_account_ids(self, client, mock_repo):
        ids = ",".join(str(uuid.uuid4()) for _ in range(51))
        resp = client.get(f"/trades?account_id={ids}")
        assert resp.status_code == 422

    def test_unknown_account_ids_filtered(self, client, mock_repo, mock_accounts_svc, conn):
        unknown = str(uuid.uuid4())
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get(f"/trades?account_id={_ACCT_A},{unknown}")
        assert resp.status_code == 200
        call_kw = mock_repo.list_trades_cross_account.call_args
        account_ids = call_kw.kwargs.get("account_ids", call_kw[1].get("account_ids", []))
        assert unknown not in account_ids

    def test_ownership_filter(self, client, mock_repo, mock_accounts_svc, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades")
        assert resp.status_code == 200
        call_kw = mock_repo.list_trades_cross_account.call_args
        account_ids = call_kw.kwargs.get("account_ids", call_kw[1].get("account_ids", []))
        assert set(account_ids) == {_ACCT_A, _ACCT_B}

    def test_sort_asc_order(self, client, mock_repo, conn):
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades?sort_by=created_at&sort_dir=asc")
        assert resp.status_code == 200

    def test_invalid_date_format_returns_422(self, client, mock_repo):
        resp = client.get("/trades?from_date=not-a-date")
        assert resp.status_code == 422

    def test_unrealized_pnl_enrichment(self, client, mock_repo, mock_accounts_svc, conn):
        trade = _make_trade(account_id=_ACCT_A, status="open", symbol="BTCUSDT", side="Buy")
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [trade], "cursor": None, "has_more": False,
        })
        mock_accounts_svc.get_positions = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "side": "Buy", "size": "0.01",
             "positionIdx": 0, "unrealisedPnl": "123.45"},
        ])
        resp = client.get("/trades")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["unrealized_pnl"] == 123.45

    def test_position_fetch_failure_returns_null_pnl(self, client, mock_repo, mock_accounts_svc, conn):
        trade = _make_trade(account_id=_ACCT_A, status="open")
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [trade], "cursor": None, "has_more": False,
        })
        mock_accounts_svc.get_positions = AsyncMock(side_effect=Exception("network error"))
        resp = client.get("/trades")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["unrealized_pnl"] is None

    def test_closed_trade_has_null_unrealized_pnl(self, client, mock_repo, conn):
        trade = _make_trade(account_id=_ACCT_A, status="closed")
        mock_repo.list_trades_cross_account = AsyncMock(return_value={
            "items": [trade], "cursor": None, "has_more": False,
        })
        resp = client.get("/trades")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["unrealized_pnl"] is None


class TestStatsCrossAccount:
    def test_all_accounts(self, client, mock_repo, conn):
        mock_repo.get_stats_cross_account = AsyncMock(return_value={
            "total_trades": 10, "open_count": 3, "win_rate": 0.6,
            "avg_pnl": 100.0, "total_pnl": 1000.0,
        })
        resp = client.get("/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 10
        assert data["open_count"] == 3

    def test_single_account(self, client, mock_repo, conn):
        mock_repo.get_stats_cross_account = AsyncMock(return_value={
            "total_trades": 5, "open_count": 1, "win_rate": 0.5,
            "avg_pnl": 50.0, "total_pnl": 250.0,
        })
        resp = client.get(f"/trades/stats?account_id={_ACCT_A}")
        assert resp.status_code == 200

    def test_no_trades(self, client, mock_repo, conn):
        mock_repo.get_stats_cross_account = AsyncMock(return_value={
            "total_trades": 0, "open_count": 0, "win_rate": 0,
            "avg_pnl": 0, "total_pnl": 0,
        })
        resp = client.get("/trades/stats")
        assert resp.status_code == 200
        assert resp.json()["total_trades"] == 0

    def test_invalid_account_id(self, client, mock_repo):
        resp = client.get("/trades/stats?account_id=bad")
        assert resp.status_code == 422

    def test_ignores_unsupported_filters(self, client, mock_repo, conn):
        mock_repo.get_stats_cross_account = AsyncMock(return_value={
            "total_trades": 0, "open_count": 0, "win_rate": 0,
            "avg_pnl": 0, "total_pnl": 0,
        })
        resp = client.get("/trades/stats?symbol=BTC/USDT&side=Buy")
        assert resp.status_code == 200


class TestTradeEvents:
    """Tests for GET /accounts/{id}/trades/{tid}/events (TASK-1.3)."""

    @pytest.fixture
    def events_app(self, mock_repo, mock_db):
        from cryptography.fernet import Fernet
        import os
        os.environ.setdefault("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())
        from backend.routers.accounts import router as accounts_router
        app = FastAPI()
        app.include_router(accounts_router)
        app.state.trade_repo = mock_repo
        db, _ = mock_db
        app.state.db = db
        app.state.accounts_service = MagicMock()
        return app

    @pytest.fixture
    def events_client(self, events_app):
        return TestClient(events_app)

    def test_success(self, events_client, mock_repo, conn):
        trade_id = str(uuid.uuid4())
        mock_repo.get_trade = AsyncMock(return_value={"id": trade_id, "account_id": _ACCT_A})
        conn.fetch = AsyncMock(return_value=[
            {"id": 1, "trade_id": uuid.UUID(trade_id), "event_type": "placed",
             "old_status": None, "new_status": "pending", "fill_qty": None,
             "fill_price": None, "actor": "user", "payload": None,
             "created_at": "2026-01-01T00:00:00Z"},
        ])
        resp = events_client.get(f"/accounts/{_ACCT_A}/trades/{trade_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["truncated"] is False

    def test_trade_not_found(self, events_client, mock_repo, conn):
        mock_repo.get_trade = AsyncMock(return_value=None)
        resp = events_client.get(f"/accounts/{_ACCT_A}/trades/{uuid.uuid4()}/events")
        assert resp.status_code == 404

    def test_wrong_account(self, events_client, mock_repo, conn):
        mock_repo.get_trade = AsyncMock(return_value=None)
        resp = events_client.get(f"/accounts/{_ACCT_B}/trades/{uuid.uuid4()}/events")
        assert resp.status_code == 404

    def test_invalid_trade_id(self, events_client, mock_repo):
        resp = events_client.get(f"/accounts/{_ACCT_A}/trades/not-a-uuid/events")
        assert resp.status_code == 422

    def test_truncated_at_1000(self, events_client, mock_repo, conn):
        trade_id = str(uuid.uuid4())
        mock_repo.get_trade = AsyncMock(return_value={"id": trade_id, "account_id": _ACCT_A})
        events = [
            {"id": i, "trade_id": uuid.UUID(trade_id), "event_type": "placed",
             "old_status": None, "new_status": "pending", "fill_qty": None,
             "fill_price": None, "actor": "user", "payload": None,
             "created_at": "2026-01-01T00:00:00Z"}
            for i in range(1000)
        ]
        conn.fetch = AsyncMock(return_value=events)
        resp = events_client.get(f"/accounts/{_ACCT_A}/trades/{trade_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["truncated"] is True
        assert len(data["items"]) == 1000


class TestWSBroadcasts:
    """Tests for WS broadcast changes (TASK-1.4, 1.5, 1.6)."""

    @pytest.fixture
    def trade_service(self):
        from backend.services.trade_service import TradeService
        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_ws = AsyncMock()
        svc = TradeService(db=mock_db, trade_repo=mock_repo, accounts_service=MagicMock(), ws_manager=mock_ws)
        svc._ws = mock_ws
        return svc, mock_ws

    @pytest.mark.asyncio
    async def test_broadcast_trade_opened_includes_version_and_data(self, trade_service):
        svc, mock_ws = trade_service
        trade = {
            "id": uuid.UUID(_TRADE_1),
            "account_id": _ACCT_A,
            "symbol": "BTC/USDT",
            "side": "Buy",
            "status": "open",
            "version": 2,
            "qty": 1.0,
        }
        await svc._broadcast_trade_event("trade.opened", trade)
        mock_ws.broadcast_to_account.assert_called_once()
        call_args = mock_ws.broadcast_to_account.call_args
        assert call_args[0][1] == "trade.opened"
        payload = call_args[0][2]
        assert payload["version"] == 2
        assert "data" in payload
        assert payload["data"]["symbol"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_broadcast_close_failed_includes_previous_status(self, trade_service):
        svc, mock_ws = trade_service
        trade = {
            "id": uuid.UUID(_TRADE_1),
            "account_id": _ACCT_A,
            "symbol": "BTC/USDT",
            "version": 3,
            "metadata": '{"error_code": "ORDER_FAILED", "error_message": "Insufficient margin"}',
            "_previous_status": "closing",
        }
        await svc._broadcast_trade_event("trade.close_failed", trade)
        mock_ws.broadcast_to_account.assert_called_once()
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["version"] == 3
        assert payload["previous_status"] == "closing"
        assert payload["error_message"] == "Insufficient margin"
        assert payload["error_code"] == "ORDER_FAILED"

    @pytest.mark.asyncio
    async def test_broadcast_closed_includes_version(self, trade_service):
        svc, mock_ws = trade_service
        trade = {
            "id": uuid.UUID(_TRADE_1),
            "account_id": _ACCT_A,
            "symbol": "BTC/USDT",
            "close_reason": "manual_single",
            "realized_pnl": 100.0,
            "net_pnl": 95.0,
            "version": 4,
        }
        await svc._broadcast_trade_event("trade.closed", trade)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["version"] == 4

    @pytest.mark.asyncio
    async def test_broadcast_version_override(self, trade_service):
        svc, mock_ws = trade_service
        trade = {
            "id": uuid.UUID(_TRADE_1),
            "account_id": _ACCT_A,
            "symbol": "BTC/USDT",
            "close_reason": "manual_single",
            "realized_pnl": 100.0,
            "net_pnl": 95.0,
            "version": 4,
        }
        await svc._broadcast_trade_event("trade.closed", trade, version_override=10)
        payload = mock_ws.broadcast_to_account.call_args[0][2]
        assert payload["version"] == 10


class TestTradesRouter503:
    def test_trade_repo_none(self, mock_repo, mock_db, mock_accounts_svc):
        from backend.routers.trades import router as trades_router
        app = FastAPI()
        app.include_router(trades_router)
        app.state.trade_repo = None
        db, _ = mock_db
        app.state.db = db
        app.state.accounts_service = mock_accounts_svc
        c = TestClient(app)
        resp = c.get("/trades/stats")
        assert resp.status_code == 503

    def test_db_none(self, mock_repo, mock_db, mock_accounts_svc):
        from backend.routers.trades import router as trades_router
        app = FastAPI()
        app.include_router(trades_router)
        app.state.trade_repo = mock_repo
        app.state.db = None
        app.state.accounts_service = mock_accounts_svc
        c = TestClient(app)
        mock_repo.get_stats_cross_account = AsyncMock(return_value={
            "total_trades": 0, "open_count": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0,
        })
        resp = c.get("/trades/stats")
        assert resp.status_code == 503
