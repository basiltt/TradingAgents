"""Tests for backend.routers.accounts — API endpoints."""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.routers.accounts import router as accounts_router
from backend.routers.portfolio import router as portfolio_router
from backend.services.bybit_client import BybitAPIError

_TEST_ID = "00000000-0000-4000-8000-000000000001"
_MISSING_ID = "00000000-0000-4000-8000-000000000099"
_TRADE_ID = "00000000-0000-4000-8000-aaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _clear_rate_limiters():
    from backend import rate_limit as mod
    mod._rate_limiters.clear()
    yield
    mod._rate_limiters.clear()


@pytest.fixture
def mock_svc():
    return MagicMock()


@pytest.fixture
def mock_trade_svc():
    svc = MagicMock()
    _trade_result = {
        "id": uuid.UUID(_TRADE_ID), "account_id": _TEST_ID, "status": "closed",
        "symbol": "BTC/USDT", "side": "Buy", "order_type": "Market",
        "qty": 1.0, "filled_qty": 1.0, "entry_price": 50000.0,
        "avg_fill_price": 50000.0, "exit_price": 51000.0,
        "stop_loss_price": None, "take_profit_price": None, "leverage": 1,
        "realized_pnl": 1000.0, "realized_pnl_pct": 2.0, "fees": 5.0,
        "net_pnl": 995.0, "source": "manual", "close_reason": "manual_single",
        "version": 3, "opened_at": "2026-01-01T00:00:00Z",
        "closed_at": "2026-01-02T00:00:00Z", "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z", "parent_trade_id": None,
        "metadata": {}, "margin_mode": "cross", "position_idx": 0,
        "order_id": None, "mark_price_at_open": None,
        "order_link_id": None, "source_id": None, "close_rule_id": None,
    }
    svc.close_single_trade = AsyncMock(return_value=_trade_result)
    _cancel_result = {**_trade_result, "status": "cancelled", "exit_price": None,
                      "realized_pnl": None, "net_pnl": None, "fees": None,
                      "realized_pnl_pct": None, "close_reason": None, "version": 2}
    svc.cancel_trade = AsyncMock(return_value=_cancel_result)
    svc.get_cached_stats = AsyncMock(return_value={
        "total_trades": 10, "open_count": 2, "win_count": 5, "loss_count": 3,
        "win_rate": 0.625, "avg_pnl": 100.0, "total_pnl": 800.0,
        "avg_duration_hours": 24.0, "max_drawdown": -200.0,
        "best_trade": 500.0, "worst_trade": -200.0,
        "profit_factor": 2.5, "sharpe_ratio": 1.2,
    })
    return svc


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
def mock_repo():
    return MagicMock()


@pytest.fixture
def app(mock_svc, mock_trade_svc, mock_db, mock_repo):
    app = FastAPI()
    app.include_router(portfolio_router)
    app.include_router(accounts_router)
    app.state.accounts_service = mock_svc
    app.state.trade_service = mock_trade_svc
    db, _ = mock_db
    app.state.db = db
    app.state.trade_repo = mock_repo
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestCreateAccount:
    def test_success(self, client, mock_svc):
        mock_svc.create_account = AsyncMock(return_value={"id": "abc", "label": "Test", "account_type": "demo"})
        resp = client.post("/accounts", json={"label": "Test", "account_type": "demo", "api_key": "key1234567890", "api_secret": "sec1234567890"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Test"

    def test_missing_label(self, client, mock_svc):
        resp = client.post("/accounts", json={"label": "", "account_type": "demo", "api_key": "key1234567890", "api_secret": "sec1234567890"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_invalid_account_type(self, client, mock_svc):
        resp = client.post("/accounts", json={"label": "X", "account_type": "paper", "api_key": "key1234567890", "api_secret": "sec1234567890"})
        assert resp.status_code == 422

    def test_short_api_key(self, client, mock_svc):
        resp = client.post("/accounts", json={"label": "X", "account_type": "demo", "api_key": "short", "api_secret": "sec1234567890"})
        assert resp.status_code == 422

    def test_connection_failure(self, client, mock_svc):
        mock_svc.create_account = AsyncMock(side_effect=ValueError("Connection test failed: Bad key"))
        resp = client.post("/accounts", json={"label": "X", "account_type": "demo", "api_key": "key1234567890", "api_secret": "sec1234567890"})
        assert resp.status_code == 400
        assert "CREDENTIAL_VALIDATION_FAILED" in resp.json()["code"]


class TestListAccounts:
    def test_empty(self, client, mock_svc):
        mock_svc.list_accounts = AsyncMock(return_value=[])
        resp = client.get("/accounts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_accounts(self, client, mock_svc):
        mock_svc.list_accounts = AsyncMock(return_value=[{"id": "1", "label": "A"}])
        resp = client.get("/accounts")
        assert len(resp.json()) == 1


class TestGetAccount:
    def test_found(self, client, mock_svc):
        mock_svc.get_account = AsyncMock(return_value={"id": "1", "label": "A"})
        resp = client.get(f"/accounts/{_TEST_ID}")
        assert resp.status_code == 200

    def test_not_found(self, client, mock_svc):
        mock_svc.get_account = AsyncMock(return_value=None)
        resp = client.get(f"/accounts/{_MISSING_ID}")
        assert resp.status_code == 404


class TestDeleteAccount:
    def test_success(self, client, mock_svc):
        mock_svc.delete_account = AsyncMock(return_value=True)
        resp = client.delete(f"/accounts/{_TEST_ID}")
        assert resp.status_code == 200

    def test_not_found(self, client, mock_svc):
        mock_svc.delete_account = AsyncMock(return_value=False)
        resp = client.delete(f"/accounts/{_MISSING_ID}")
        assert resp.status_code == 404


class TestWallet:
    def test_success(self, client, mock_svc):
        mock_svc.get_wallet = AsyncMock(return_value={"totalEquity": "1000"})
        resp = client.get(f"/accounts/{_TEST_ID}/wallet")
        assert resp.status_code == 200
        assert resp.json()["totalEquity"] == "1000"

    def test_not_found(self, client, mock_svc):
        mock_svc.get_wallet = AsyncMock(side_effect=ValueError("Account 1 not found"))
        resp = client.get(f"/accounts/{_TEST_ID}/wallet")
        assert resp.status_code == 404

    def test_bybit_error(self, client, mock_svc):
        mock_svc.get_wallet = AsyncMock(side_effect=BybitAPIError(10001, "Bad"))
        resp = client.get(f"/accounts/{_TEST_ID}/wallet")
        assert resp.status_code == 502


class TestClosedPnl:
    def test_invalid_date(self, client, mock_svc):
        resp = client.get(f"/accounts/{_TEST_ID}/closed-pnl?start_date=bad&end_date=2025-01-07")
        assert resp.status_code == 422

    def test_success(self, client, mock_svc):
        mock_svc.get_closed_pnl = AsyncMock(return_value={"records": [], "total": 0, "page": 1})
        resp = client.get(f"/accounts/{_TEST_ID}/closed-pnl?start_date=2025-01-01&end_date=2025-01-07")
        assert resp.status_code == 200


class TestPnlSummary:
    def test_success(self, client, mock_svc):
        mock_svc.get_pnl_summary = AsyncMock(return_value={"total_pnl": "100", "win_rate": 60.0, "win_count": 6, "loss_count": 4, "avg_win": "25", "avg_loss": "-10"})
        resp = client.get(f"/accounts/{_TEST_ID}/closed-pnl/summary?start_date=2025-01-01&end_date=2025-01-07")
        assert resp.status_code == 200
        assert resp.json()["win_rate"] == 60.0


class TestPortfolio:
    def test_dashboard(self, client, mock_svc):
        mock_svc.get_dashboard = AsyncMock(return_value=[{"id": "1", "status": "active"}])
        resp = client.get("/portfolio/dashboard")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_summary(self, client, mock_svc):
        mock_svc.get_portfolio_summary = AsyncMock(return_value={"total_equity": "5000", "active_accounts": 2})
        resp = client.get("/portfolio/summary")
        assert resp.status_code == 200
        assert resp.json()["total_equity"] == "5000"


# --- New coverage: rotate credentials ---

class TestRotateCredentials:
    def test_success(self, client, mock_svc):
        mock_svc.rotate_credentials = AsyncMock(return_value={"id": _TEST_ID})
        resp = client.patch(f"/accounts/{_TEST_ID}/credentials", json={
            "api_key": "k" * 20, "api_secret": "s" * 20,
        })
        assert resp.status_code == 200

    def test_not_found(self, client, mock_svc):
        mock_svc.rotate_credentials = AsyncMock(return_value=None)
        resp = client.patch(f"/accounts/{_TEST_ID}/credentials", json={
            "api_key": "k" * 20, "api_secret": "s" * 20,
        })
        assert resp.status_code == 404

    def test_bad_credentials(self, client, mock_svc):
        mock_svc.rotate_credentials = AsyncMock(side_effect=ValueError("Invalid key"))
        resp = client.patch(f"/accounts/{_TEST_ID}/credentials", json={
            "api_key": "k" * 20, "api_secret": "s" * 20,
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "CREDENTIAL_VALIDATION_FAILED"

    def test_bybit_error(self, client, mock_svc):
        mock_svc.rotate_credentials = AsyncMock(side_effect=BybitAPIError(ret_code=10001, ret_msg="Fail"))
        resp = client.patch(f"/accounts/{_TEST_ID}/credentials", json={
            "api_key": "k" * 20, "api_secret": "s" * 20,
        })
        assert resp.status_code == 502

    def test_short_key_validation(self, client):
        resp = client.patch(f"/accounts/{_TEST_ID}/credentials", json={
            "api_key": "short", "api_secret": "short",
        })
        assert resp.status_code == 422


class TestUpdateAccount:
    def test_success(self, client, mock_svc):
        mock_svc.update_account = AsyncMock(return_value={"id": _TEST_ID, "label": "Updated"})
        resp = client.patch(f"/accounts/{_TEST_ID}", json={"label": "Updated"})
        assert resp.status_code == 200

    def test_not_found(self, client, mock_svc):
        mock_svc.update_account = AsyncMock(return_value=None)
        resp = client.patch(f"/accounts/{_TEST_ID}", json={"label": "X"})
        assert resp.status_code == 404


# --- Delete with foreign key ---

class TestDeleteAccountFK:
    def test_foreign_key_409(self, client, mock_svc):
        class ForeignKeyViolation(Exception):
            pass
        mock_svc.delete_account = AsyncMock(side_effect=ForeignKeyViolation("foreign key"))
        resp = client.delete(f"/accounts/{_TEST_ID}")
        assert resp.status_code == 409
        assert resp.json()["code"] == "ACCOUNT_HAS_TRADES"


# --- Analytics Inclusion ---

class TestAnalyticsInclusion:
    def test_toggle_on(self, client, mock_svc):
        mock_svc.set_analytics_inclusion = AsyncMock(return_value={"id": _TEST_ID, "include_in_analytics": True})
        resp = client.patch(f"/accounts/{_TEST_ID}/analytics-inclusion", json={"include": True})
        assert resp.status_code == 200

    def test_not_found(self, client, mock_svc):
        mock_svc.set_analytics_inclusion = AsyncMock(return_value=None)
        resp = client.patch(f"/accounts/{_TEST_ID}/analytics-inclusion", json={"include": True})
        assert resp.status_code == 404

    def test_non_boolean_int(self, client):
        resp = client.patch(f"/accounts/{_TEST_ID}/analytics-inclusion", json={"include": 1})
        assert resp.status_code == 422

    def test_non_boolean_string(self, client):
        resp = client.patch(f"/accounts/{_TEST_ID}/analytics-inclusion", json={"include": "true"})
        assert resp.status_code == 422


# --- Close / Cancel trade endpoints ---

class TestCloseTrade:
    def test_success(self, client, mock_trade_svc):
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 200

    def test_trade_not_found(self, client, mock_trade_svc):
        from backend.services.trade_repository import TradeNotFound
        mock_trade_svc.close_single_trade = AsyncMock(side_effect=TradeNotFound("nope"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 404

    def test_invalid_status(self, client, mock_trade_svc):
        from backend.services.trade_repository import InvalidStatusTransition
        mock_trade_svc.close_single_trade = AsyncMock(side_effect=InvalidStatusTransition("already closed"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 409

    def test_concurrent_mod(self, client, mock_trade_svc):
        from backend.services.trade_repository import ConcurrentModification
        mock_trade_svc.close_single_trade = AsyncMock(side_effect=ConcurrentModification("version"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 409

    def test_bybit_error(self, client, mock_trade_svc):
        mock_trade_svc.close_single_trade = AsyncMock(side_effect=BybitAPIError(ret_code=10001, ret_msg="Rejected"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 502

    def test_invalid_trade_id(self, client):
        resp = client.post(f"/accounts/{_TEST_ID}/trades/not-a-uuid/close")
        assert resp.status_code in (400, 422)

    def test_service_unavailable(self, client, app):
        app.state.trade_service = None
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/close")
        assert resp.status_code == 503


class TestCancelTrade:
    def test_success(self, client, mock_trade_svc):
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/cancel")
        assert resp.status_code == 200

    def test_trade_not_found(self, client, mock_trade_svc):
        from backend.services.trade_repository import TradeNotFound
        mock_trade_svc.cancel_trade = AsyncMock(side_effect=TradeNotFound("nope"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/cancel")
        assert resp.status_code == 404

    def test_invalid_status(self, client, mock_trade_svc):
        from backend.services.trade_repository import InvalidStatusTransition
        mock_trade_svc.cancel_trade = AsyncMock(side_effect=InvalidStatusTransition("nope"))
        resp = client.post(f"/accounts/{_TEST_ID}/trades/{_TRADE_ID}/cancel")
        assert resp.status_code == 409


# --- Place Trade endpoint ---

class TestPlaceTrade:
    def _body(self, **kw):
        return {
            "symbol": "BTCUSDT", "signal_direction": "buy",
            "trade_direction": "straight", "leverage": 10,
            "take_profit_pct": 5.0, "stop_loss_pct": 3.0,
            "capital_pct": 10.0, "base_capital": 1000.0, **kw,
        }

    def test_success(self, client, mock_svc):
        mock_svc.place_trade = AsyncMock(return_value={"id": "x", "status": "open"})
        resp = client.post(f"/accounts/{_TEST_ID}/trade", json=self._body())
        assert resp.status_code == 200

    def test_validation_error(self, client):
        resp = client.post(f"/accounts/{_TEST_ID}/trade", json={"symbol": "X"})
        assert resp.status_code == 422

    def test_bybit_error(self, client, mock_svc):
        mock_svc.place_trade = AsyncMock(side_effect=BybitAPIError(ret_code=10001, ret_msg="Rejected"))
        resp = client.post(f"/accounts/{_TEST_ID}/trade", json=self._body())
        assert resp.status_code == 502


# --- Rate Limiter ---

class TestRateLimiter:
    def test_token_bucket_allows_burst(self):
        from backend.rate_limit import _TokenBucket
        bucket = _TokenBucket(rate=10.0, capacity=10.0)
        for _ in range(10):
            assert bucket.consume() is True
        assert bucket.consume() is False

    def test_token_bucket_refills(self):
        from backend.rate_limit import _TokenBucket
        bucket = _TokenBucket(rate=100.0, capacity=10.0)
        for _ in range(10):
            bucket.consume()
        assert bucket.consume() is False
        bucket.last_refill -= 0.1
        assert bucket.consume() is True

    @pytest.mark.asyncio
    async def test_rate_limit_429(self):
        from backend.rate_limit import check_rate_limit, _rate_limiters, _TokenBucket
        _rate_limiters.clear()
        bucket = _TokenBucket(rate=0.0, capacity=1.0)
        bucket.consume()
        _rate_limiters["test-acct"] = bucket
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit("test-acct")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_stale_eviction(self):
        from backend.rate_limit import (
            check_rate_limit, _rate_limiters, _TokenBucket,
            _RATE_LIMITER_MAX_ENTRIES, _RATE_LIMITER_STALE_SECONDS,
        )
        _rate_limiters.clear()
        for i in range(_RATE_LIMITER_MAX_ENTRIES):
            b = _TokenBucket()
            b.last_refill = time.monotonic() - _RATE_LIMITER_STALE_SECONDS - 1
            _rate_limiters[f"stale-{i}"] = b
        await check_rate_limit("new-acct")
        assert "new-acct" in _rate_limiters
        assert len(_rate_limiters) < _RATE_LIMITER_MAX_ENTRIES


# --- Service disabled (503) ---

class TestServiceDisabled:
    def test_accounts_service_none(self, app, client):
        app.state.accounts_service = None
        resp = client.get("/accounts")
        assert resp.status_code == 503

    def test_bad_uuid_returns_400(self, client):
        resp = client.get("/accounts/not-a-uuid")
        assert resp.status_code == 400
