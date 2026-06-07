"""Tests for the admin feature-kill-switch endpoint (API §K, FR-007)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from backend.routers.admin import router as admin_router


class _FakePool:
    def __init__(self):
        self.rows: dict[str, bool] = {}
        self.fail = False

    async def execute(self, sql, *args):
        if self.fail:
            raise RuntimeError("db down")
        feature, killed = args[0], args[1]
        self.rows[feature] = killed
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        return [{"feature_name": f, "killed": k} for f, k in self.rows.items()]


class _FakeDB:
    def __init__(self):
        self.pool = _FakePool()


@pytest.fixture
def db():
    return _FakeDB()


@pytest_asyncio.fixture
async def client(db):
    app = FastAPI()
    app.state.db = db
    app.include_router(admin_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_disable_feature_sets_killed_true(client, db):
    resp = await client.post("/api/v1/admin/kill-switch",
                             json={"feature_name": "f2_long", "enabled": False, "updated_by": "ops"})
    assert resp.status_code == 200
    assert resp.json() == {"feature_name": "f2_long", "enabled": False, "killed": True}
    assert db.pool.rows["f2_long"] is True  # killed persisted


@pytest.mark.asyncio
async def test_enable_feature_sets_killed_false(client, db):
    resp = await client.post("/api/v1/admin/kill-switch",
                             json={"feature_name": "f1", "enabled": True})
    assert resp.status_code == 200
    assert resp.json()["killed"] is False
    assert db.pool.rows["f1"] is False


@pytest.mark.asyncio
async def test_master_kill_supported(client, db):
    resp = await client.post("/api/v1/admin/kill-switch",
                             json={"feature_name": "__all__", "enabled": False})
    assert resp.status_code == 200
    assert db.pool.rows["__all__"] is True


@pytest.mark.asyncio
async def test_unknown_feature_rejected(client):
    resp = await client.post("/api/v1/admin/kill-switch",
                             json={"feature_name": "bogus", "enabled": False})
    assert resp.status_code == 422
    assert "Unknown feature_name" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_persist_failure_returns_500(client, db):
    db.pool.fail = True
    resp = await client.post("/api/v1/admin/kill-switch",
                             json={"feature_name": "f1", "enabled": False})
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_get_returns_current_state(client, db):
    db.pool.rows = {"f2_long": True, "f1": False}
    resp = await client.get("/api/v1/admin/kill-switch")
    assert resp.status_code == 200
    ks = resp.json()["kill_switches"]
    # operator-facing 'enabled' mirrors POST polarity; 'killed' included for transparency
    assert ks["f2_long"] == {"enabled": False, "killed": True}
    assert ks["f1"] == {"enabled": True, "killed": False}
