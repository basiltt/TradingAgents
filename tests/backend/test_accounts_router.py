"""Tests for backend.routers.accounts — API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.accounts import router as accounts_router
from backend.routers.portfolio import router as portfolio_router
from backend.services.bybit_client import BybitAPIError

_TEST_ID = "00000000-0000-4000-8000-000000000001"
_MISSING_ID = "00000000-0000-4000-8000-000000000099"


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def mock_svc():
    return MagicMock()


@pytest.fixture
def app(mock_svc):
    app = FastAPI()
    app.include_router(portfolio_router)
    app.include_router(accounts_router)
    app.state.accounts_service = mock_svc
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
