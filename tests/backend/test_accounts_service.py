"""Tests for backend.services.accounts_service — service layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def db():
    """Mock DB that simulates in-memory storage for accounts."""
    mock_db = MagicMock()
    _store: dict = {}

    def _insert_account(account):
        account.setdefault("is_active", 1)
        _store[account["id"]] = account

    def _get_account(account_id):
        acc = _store.get(account_id)
        if acc and acc.get("deleted_at"):
            return None
        return acc

    def _list_accounts():
        return [a for a in _store.values() if not a.get("deleted_at")]

    def _update_account(account_id, **fields):
        acc = _store.get(account_id)
        if not acc or acc.get("deleted_at"):
            return False
        acc.update({k: v for k, v in fields.items() if v is not None})
        return True

    def _soft_delete(account_id, deleted_at):
        acc = _store.get(account_id)
        if not acc or acc.get("deleted_at"):
            return False
        acc["deleted_at"] = deleted_at
        acc["is_active"] = 0
        return True

    def _get_credentials(account_id):
        acc = _store.get(account_id)
        if not acc or acc.get("deleted_at"):
            return None
        return {
            "id": acc["id"],
            "account_type": acc["account_type"],
            "api_key_encrypted": acc["api_key_encrypted"],
            "api_secret_encrypted": acc["api_secret_encrypted"],
        }

    mock_db.insert_account = AsyncMock(side_effect=_insert_account)
    mock_db.get_account = AsyncMock(side_effect=_get_account)
    mock_db.list_accounts = AsyncMock(side_effect=_list_accounts)
    mock_db.update_account = AsyncMock(side_effect=_update_account)
    mock_db.soft_delete_account = AsyncMock(side_effect=_soft_delete)
    mock_db.clear_account_cooloff_state = AsyncMock(return_value=None)
    mock_db.get_account_credentials = AsyncMock(side_effect=_get_credentials)
    mock_db.rotate_account_credentials = AsyncMock(return_value=True)
    mock_db.insert_closed_pnl_records = AsyncMock(return_value=0)
    mock_db.get_closed_pnl = AsyncMock(return_value={"items": [], "total": 0, "page": 1, "limit": 100})
    mock_db.get_closed_pnl_summary = AsyncMock(return_value={
        "total_pnl": "0", "win_count": 0, "loss_count": 0,
        "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
    })
    return mock_db


@pytest.fixture
def svc(db):
    from backend.services.accounts_service import AccountsService

    return AccountsService(db)


@pytest.mark.asyncio
async def test_create_account_success(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "uid1", "error": None})
        instance.close = AsyncMock()
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
        instance.close = AsyncMock()
        with pytest.raises(ValueError, match="Connection test failed"):
            await svc.create_account("Test", "demo", "apikey12345678", "secret12345678")


@pytest.mark.asyncio
async def test_list_accounts_empty(svc):
    assert await svc.list_accounts() == []


@pytest.mark.asyncio
async def test_list_accounts_after_create(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        await svc.create_account("A1", "demo", "apikey12345678", "secret12345678")
        await svc.create_account("A2", "live", "apikey99999999", "secret99999999")

    accounts = await svc.list_accounts()
    assert len(accounts) == 2


@pytest.mark.asyncio
async def test_update_account(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Old", "demo", "apikey12345678", "secret12345678")

    updated = await svc.update_account(account["id"], label="New")
    assert updated["label"] == "New"


@pytest.mark.asyncio
async def test_delete_account(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Del", "demo", "apikey12345678", "secret12345678")

    assert await svc.delete_account(account["id"]) is True
    assert await svc.get_account(account["id"]) is None
    assert await svc.list_accounts() == []
    # Cool-off state is cleared on soft-delete (the FK CASCADE can't fire on a soft
    # delete), so a future reactivation can't resurrect a stale streak / active pause.
    svc._db.clear_account_cooloff_state.assert_awaited_with(account["id"])


@pytest.mark.asyncio
async def test_deactivate_account_clears_cooloff_state(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Deact", "demo", "apikey12345678", "secret12345678")

    svc._db.clear_account_cooloff_state.reset_mock()
    await svc.update_account(account["id"], is_active=False)
    svc._db.clear_account_cooloff_state.assert_awaited_once_with(account["id"])

    # Re-activating must NOT clear (no resurrection concern; nothing to clear).
    svc._db.clear_account_cooloff_state.reset_mock()
    await svc.update_account(account["id"], is_active=True)
    svc._db.clear_account_cooloff_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_wallet_caches(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Cache", "demo", "apikey12345678", "secret12345678")

    wallet_data = {"totalEquity": "500", "totalWalletBalance": "400", "totalAvailableBalance": "300", "totalPerpUPL": "50", "coin": []}
    with patch.object(svc, "_build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get_wallet_balance = AsyncMock(return_value=wallet_data)
        mock_build.return_value = mock_client
        result1 = await svc.get_wallet(account["id"])
        result2 = await svc.get_wallet(account["id"])
        assert mock_client.get_wallet_balance.call_count == 1

    assert result1["totalEquity"] == "500"
    assert result2["totalEquity"] == "500"


@pytest.mark.asyncio
async def test_get_positions(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Pos", "demo", "apikey12345678", "secret12345678")

    positions_data = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]
    with patch.object(svc, "_build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get_positions = AsyncMock(return_value=positions_data)
        mock_build.return_value = mock_client
        result = await svc.get_positions(account["id"])

    assert len(result) == 1
    assert result[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_pnl_summary_range_too_large(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("PnL", "demo", "apikey12345678", "secret12345678")

    with pytest.raises(ValueError, match="exceeds maximum"):
        await svc.get_pnl_summary(account["id"], "2025-01-01", "2025-06-01")


@pytest.mark.asyncio
async def test_cache_invalidation_on_delete(svc):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        account = await svc.create_account("Inv", "demo", "apikey12345678", "secret12345678")

    svc._set_cached(f"{account['id']}:wallet", {"test": True}, 60)
    assert svc._get_cached(f"{account['id']}:wallet", 60) is not None

    await svc.delete_account(account["id"])
    assert svc._get_cached(f"{account['id']}:wallet", 60) is None


@pytest.mark.asyncio
async def test_dashboard_with_error_account(svc, db):
    with patch("backend.services.accounts_service.BybitClient") as MockClient:
        instance = MockClient.return_value
        instance.test_connection = AsyncMock(return_value={"success": True, "uid": "u1", "error": None})
        instance.close = AsyncMock()
        await svc.create_account("Err", "demo", "apikey12345678", "secret12345678")

    with patch.object(svc, "_build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get_wallet_balance = AsyncMock(side_effect=BybitAPIError(10001, "fail"))
        mock_build.return_value = mock_client
        cards = await svc.get_dashboard()

    assert len(cards) == 1
    assert cards[0]["status"] == "error"
