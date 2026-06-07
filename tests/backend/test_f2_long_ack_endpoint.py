"""Tests for the f2-long-ack endpoint (Phase 4 TASK-4.5)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.accounts import router as accounts_router

_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _clear_rate_limiters():
    from backend import rate_limit as mod
    mod._rate_limiters.clear()
    yield
    mod._rate_limiters.clear()


def _client(db):
    app = FastAPI()
    app.include_router(accounts_router, prefix="/api/v1")
    app.state.db = db
    app.state.accounts_service = MagicMock()
    return TestClient(app)


def test_f2_long_ack_records_with_valid_exposure():
    db = MagicMock()
    db.pool = MagicMock()
    db.pool.execute = AsyncMock()
    client = _client(db)
    resp = client.post(f"/api/v1/accounts/{_ID}/f2-long-ack",
                       json={"leverage": 10, "capital_pct": 2.0, "max_trades": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["acked_leverage"] == 10
    assert db.pool.execute.await_count == 1   # ack row written


def test_f2_long_ack_rejects_out_of_bounds_leverage():
    db = MagicMock()
    db.pool = MagicMock()
    db.pool.execute = AsyncMock()
    client = _client(db)
    resp = client.post(f"/api/v1/accounts/{_ID}/f2-long-ack",
                       json={"leverage": 200, "capital_pct": 2.0, "max_trades": 2})
    assert resp.status_code == 422
    assert db.pool.execute.await_count == 0   # nothing written


def test_f2_long_ack_rejects_non_numeric():
    db = MagicMock()
    db.pool = MagicMock()
    db.pool.execute = AsyncMock()
    client = _client(db)
    resp = client.post(f"/api/v1/accounts/{_ID}/f2-long-ack",
                       json={"leverage": "abc", "capital_pct": 2.0, "max_trades": 2})
    assert resp.status_code == 422
