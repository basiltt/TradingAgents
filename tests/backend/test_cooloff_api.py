"""Cool Off Time — Phase 4 API tests (status + clear endpoints) via FastAPI TestClient.

Mocks accounts_service + cooloff_repo on app.state (no DB/exchange). Covers FR-014/015,
NFR-012, K3/DS29: status shape + no-row defaults, 404 unknown account, clear idempotent +
reset_streak flag + audit, 503 when feature off.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.accounts import router as accounts_router

_ACC = "00000000-0000-4000-8000-000000000001"
_MISSING = "00000000-0000-4000-8000-000000000099"


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def mock_svc():
    svc = MagicMock()
    svc.get_account = AsyncMock(return_value={"id": _ACC, "label": "T"})
    return svc


@pytest.fixture
def mock_cooloff_repo():
    return MagicMock()


@pytest.fixture
def app(mock_svc, mock_cooloff_repo):
    app = FastAPI()
    app.include_router(accounts_router)
    app.state.accounts_service = mock_svc
    app.state.cooloff_repo = mock_cooloff_repo
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── GET status ───────────────────────────────────────────────────────────────

def test_status_cooling(client, mock_cooloff_repo):
    until = datetime(2024, 6, 1, 13, 0, tzinfo=timezone.utc)
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": until, "cooloff_reason": "failure",
        "consecutive_wins": 0, "consecutive_losses": 1,
        "cooloff_remaining_seconds": 1800, "cooling": True,
    })
    r = client.get(f"/accounts/{_ACC}/cooloff")
    assert r.status_code == 200
    body = r.json()
    assert body["cooling"] is True
    assert body["cooloff_reason"] == "failure"
    assert body["cooloff_until"] == until.isoformat()
    assert body["cooloff_remaining_seconds"] == 1800
    assert body["consecutive_losses"] == 1


def test_status_no_row_defaults_200(client, mock_cooloff_repo):
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": None, "cooloff_reason": None,
        "consecutive_wins": 0, "consecutive_losses": 0,
        "cooloff_remaining_seconds": 0, "cooling": False,
    })
    r = client.get(f"/accounts/{_ACC}/cooloff")
    assert r.status_code == 200
    assert r.json()["cooling"] is False
    assert r.json()["cooloff_until"] is None


def test_status_unknown_account_404(client, mock_svc):
    mock_svc.get_account = AsyncMock(return_value=None)
    r = client.get(f"/accounts/{_MISSING}/cooloff")
    assert r.status_code == 404


def test_status_invalid_id_400(client):
    r = client.get("/accounts/not-a-uuid/cooloff")
    assert r.status_code == 400


def test_status_feature_off_503():
    app = FastAPI()
    app.include_router(accounts_router)
    svc = MagicMock()
    svc.get_account = AsyncMock(return_value={"id": _ACC})
    app.state.accounts_service = svc
    app.state.cooloff_repo = None  # feature off
    import os
    os.environ.setdefault("ACCOUNTS_ENCRYPTION_KEY", "x")
    c = TestClient(app)
    r = c.get(f"/accounts/{_ACC}/cooloff")
    assert r.status_code == 503


# ── POST clear ───────────────────────────────────────────────────────────────

def test_clear_default_no_reset(client, mock_cooloff_repo):
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": datetime(2024, 6, 1, tzinfo=timezone.utc), "cooloff_reason": "failure",
        "consecutive_wins": 0, "consecutive_losses": 2, "cooloff_remaining_seconds": 60, "cooling": True,
    })
    mock_cooloff_repo.clear = AsyncMock(return_value=True)
    r = client.post(f"/accounts/{_ACC}/cooloff/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] is True
    assert r.json()["cooloff_until"] is None
    mock_cooloff_repo.clear.assert_awaited_once_with(_ACC, reset_streak=False, disable_settings=False)


def test_clear_with_reset_streak(client, mock_cooloff_repo):
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": None, "cooloff_reason": None,
        "consecutive_wins": 0, "consecutive_losses": 0, "cooloff_remaining_seconds": 0, "cooling": False,
    })
    mock_cooloff_repo.clear = AsyncMock(return_value=True)
    r = client.post(f"/accounts/{_ACC}/cooloff/clear?reset_streak=true")
    assert r.status_code == 200
    mock_cooloff_repo.clear.assert_awaited_once_with(_ACC, reset_streak=True, disable_settings=False)


def test_clear_with_disable_settings(client, mock_cooloff_repo):
    """disable_settings=true is the per-account turn-off (manual-surface disable path)."""
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": None, "cooloff_reason": None,
        "consecutive_wins": 0, "consecutive_losses": 0, "cooloff_remaining_seconds": 0,
        "cooling": False, "tiers_enabled": False,
    })
    mock_cooloff_repo.clear = AsyncMock(return_value=True)
    r = client.post(f"/accounts/{_ACC}/cooloff/clear?reset_streak=true&disable_settings=true")
    assert r.status_code == 200
    mock_cooloff_repo.clear.assert_awaited_once_with(_ACC, reset_streak=True, disable_settings=True)


def test_clear_idempotent_no_row(client, mock_cooloff_repo):
    mock_cooloff_repo.read_status = AsyncMock(return_value={
        "cooloff_until": None, "cooloff_reason": None,
        "consecutive_wins": 0, "consecutive_losses": 0, "cooloff_remaining_seconds": 0, "cooling": False,
    })
    mock_cooloff_repo.clear = AsyncMock(return_value=False)
    r = client.post(f"/accounts/{_ACC}/cooloff/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] is False


def test_clear_unknown_account_404(client, mock_svc, mock_cooloff_repo):
    mock_svc.get_account = AsyncMock(return_value=None)
    mock_cooloff_repo.clear = AsyncMock()
    r = client.post(f"/accounts/{_MISSING}/cooloff/clear")
    assert r.status_code == 404
    mock_cooloff_repo.clear.assert_not_awaited()  # never clears a non-existent account
