"""Tests for the /api/v1/debug router using a stubbed recorder/repository on app.state."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.debug import router as debug_router


def _app(repo, recorder):
    app = FastAPI()
    app.state.debug_trace_recorder = recorder
    recorder.repo = repo   # router reads the public `repo` accessor
    app.include_router(debug_router, prefix="/api/v1")
    return app


def test_get_scan_tree_returns_aggregate():
    repo = MagicMock()
    repo.get_latest_run_id_for_scan = AsyncMock(return_value=7)
    repo.get_run_tree = AsyncMock(return_value={
        "run": {"id": 7, "scan_id": "s1", "trigger_source": "scheduled"},
        "accounts": [{"account_id": "a1", "account_label": "Dad - Demo",
                      "lifecycle_events": [], "symbol_decisions": [],
                      "exchange_snapshots": [], "narrative": "Account Dad - Demo: ..."}],
    })
    recorder = MagicMock()
    client = TestClient(_app(repo, recorder))
    resp = client.get("/api/v1/debug/scan/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["scan_id"] == "s1"
    assert body["accounts"][0]["account_label"] == "Dad - Demo"


def test_get_scan_tree_404_when_no_run():
    repo = MagicMock()
    repo.get_latest_run_id_for_scan = AsyncMock(return_value=None)
    recorder = MagicMock()
    client = TestClient(_app(repo, recorder))
    resp = client.get("/api/v1/debug/scan/missing")
    assert resp.status_code == 404


def test_get_and_update_config():
    repo = MagicMock()
    repo.get_config = AsyncMock(return_value={"tracing_enabled": True, "retention_days": 60, "symbol_decision_cap": 200})
    repo.update_config = AsyncMock(return_value={"tracing_enabled": False, "retention_days": 30, "symbol_decision_cap": 200})
    recorder = MagicMock()
    recorder.refresh_config = AsyncMock()
    client = TestClient(_app(repo, recorder))
    assert client.get("/api/v1/debug/config").json()["retention_days"] == 60
    resp = client.put("/api/v1/debug/config", json={"tracing_enabled": False, "retention_days": 30})
    assert resp.status_code == 200
    assert resp.json()["tracing_enabled"] is False
    recorder.refresh_config.assert_awaited()
