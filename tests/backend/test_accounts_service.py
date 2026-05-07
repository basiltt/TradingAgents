"""Tests for backend.services.accounts_service — service layer."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def db(tmp_path):
    from backend.persistence import AnalysisDB

    return AnalysisDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def svc(db):
    from backend.services.accounts_service import AccountsService

    return AccountsService(db)


@pytest.mark.asyncio
async def test_create_account_success(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "uid1", "error": None})
        account = await svc.create_account("Test", "demo", "apikey12345678", "secret12345678")

    assert account["label"] == "Test"
    assert account["account_type"] == "demo"
    assert account["is_active"] == 1
    assert account["id"] is not None


@pytest.mark.asyncio
async def test_create_account_connection_failure(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": False, "uid": None, "error": "Invalid API key"})
        with pytest.raises(ValueError, match="Connection test failed"):
            await svc.create_account("Test", "demo", "apikey12345678", "secret12345678")


def test_list_accounts_empty(svc):
    assert svc.list_accounts() == []


@pytest.mark.asyncio
async def test_list_accounts_after_create(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        await svc.create_account("A1", "demo", "apikey12345678", "secret12345678")
        await svc.create_account("A2", "live", "apikey99999999", "secret99999999")

    accounts = svc.list_accounts()
    assert len(accounts) == 2


@pytest.mark.asyncio
async def test_update_account(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("Old", "demo", "apikey12345678", "secret12345678")

    updated = svc.update_account(account["id"], label="New")
    assert updated["label"] == "New"


@pytest.mark.asyncio
async def test_delete_account(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("Del", "demo", "apikey12345678", "secret12345678")

    assert svc.delete_account(account["id"]) is True
    assert svc.get_account(account["id"]) is None
    assert svc.list_accounts() == []


@pytest.mark.asyncio
async def test_get_wallet_caches(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("Cache", "demo", "apikey12345678", "secret12345678")

    wallet_data = {"totalEquity": "500", "totalWalletBalance": "400", "totalAvailableBalance": "300", "totalPerpUPL": "50", "coin": []}
    with patch("backend.services.accounts_service.BybitClient") as MockClient2:
        instance2 = MockClient2.return_value
        instance2.get_wallet_balance = AsyncMock(return_value=wallet_data)
        result1 = await svc.get_wallet(account["id"])
        result2 = await svc.get_wallet(account["id"])
        assert instance2.get_wallet_balance.call_count == 1

    assert result1["totalEquity"] == "500"
    assert result2["totalEquity"] == "500"


@pytest.mark.asyncio
async def test_get_positions(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("Pos", "demo", "apikey12345678", "secret12345678")

    positions_data = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    with patch("backend.services.accounts_service.BybitClient") as MockClient2:
        instance2 = MockClient2.return_value
        instance2.get_positions = AsyncMock(return_value=positions_data)
        result = await svc.get_positions(account["id"])

    assert len(result) == 1
    assert result[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_pnl_summary_range_too_large(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("PnL", "demo", "apikey12345678", "secret12345678")

    with pytest.raises(ValueError, match="exceeds maximum"):
        await svc.get_pnl_summary(account["id"], "2025-01-01", "2025-06-01")


@pytest.mark.asyncio
async def test_cache_invalidation_on_delete(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        account = await svc.create_account("Inv", "demo", "apikey12345678", "secret12345678")

    svc._set_cached(f"{account['id']}:wallet", {"test": True}, 60)
    assert svc._get_cached(f"{account['id']}:wallet", 60) is not None

    svc.delete_account(account["id"])
    assert svc._get_cached(f"{account['id']}:wallet", 60) is None


@pytest.mark.asyncio
async def test_dashboard_with_error_account(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        await svc.create_account("Err", "demo", "apikey12345678", "secret12345678")

    with patch.object(svc, "_build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get_wallet_balance = AsyncMock(side_effect=BybitAPIError(10001, "fail"))
        mock_build.return_value = mock_client
        cards = await svc.get_dashboard()

    assert len(cards) == 1
    assert cards[0]["status"] == "error"
