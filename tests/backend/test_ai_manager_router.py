"""Tests for AI Manager Router — Phase 4 Task 4.1."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_service():
    svc = MagicMock()
    svc.enable = AsyncMock()
    svc.disable = AsyncMock()
    svc.get_status = AsyncMock(return_value=MagicMock(
        enabled=True, state="monitoring",
        model_dump=lambda: {"enabled": True, "state": "monitoring"},
    ))
    svc.patch_config = AsyncMock()
    svc.pause = AsyncMock()
    svc.resume = AsyncMock()
    svc.kill = AsyncMock()
    svc.reset_kill_switch = AsyncMock()
    svc.lock_position = AsyncMock()
    svc.unlock_position = AsyncMock()
    svc.get_decisions = AsyncMock(return_value={"decisions": [], "next_cursor": None})
    svc.get_performance = AsyncMock(return_value={"period": "7d", "total_decisions": 0})
    svc.global_kill = AsyncMock()
    return svc


@pytest.fixture(autouse=True)
def bypass_rate_limit():
    with patch("backend.routers.ai_manager._check_rate_limit", new=AsyncMock()):
        yield


@pytest.fixture
def client(mock_service):
    from fastapi import FastAPI
    from backend.routers.ai_manager import router

    app = FastAPI()
    app.state.ai_manager_service = mock_service
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, headers={"X-Requested-With": "test"})


def test_enable(client, mock_service):
    mock_service.get_status = AsyncMock(return_value=None)
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/enable")
    assert resp.status_code == 200
    assert resp.json()["status"] == "enabled"
    mock_service.enable.assert_called_once()


def test_enable_already_enabled(client, mock_service):
    mock_service.get_status = AsyncMock(return_value=MagicMock(enabled=True))
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/enable")
    assert resp.status_code == 200
    mock_service.enable.assert_not_called()


def test_disable(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/disable")
    assert resp.status_code == 200
    mock_service.disable.assert_called_once_with("acc-1")


def test_get_status(client, mock_service):
    resp = client.get("/api/v1/accounts/acc-1/ai-manager/status")
    assert resp.status_code == 200


def test_get_status_not_found(client, mock_service):
    mock_service.get_status = AsyncMock(return_value=None)
    resp = client.get("/api/v1/accounts/acc-1/ai-manager/status")
    assert resp.status_code == 404


def test_patch_config(client, mock_service):
    resp = client.patch(
        "/api/v1/accounts/acc-1/ai-manager/config",
        json={"confidence_threshold": 0.8},
    )
    assert resp.status_code == 200
    mock_service.patch_config.assert_called_once_with("acc-1", {"confidence_threshold": 0.8})


def test_patch_config_empty_body(client, mock_service):
    resp = client.patch("/api/v1/accounts/acc-1/ai-manager/config", json={})
    assert resp.status_code == 400


def test_pause(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/pause")
    assert resp.status_code == 200
    mock_service.pause.assert_called_once_with("acc-1")


def test_resume(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/resume")
    assert resp.status_code == 200
    mock_service.resume.assert_called_once_with("acc-1")


def test_kill(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/kill")
    assert resp.status_code == 200
    mock_service.kill.assert_called_once_with("acc-1")


def test_reset_kill_switch(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/kill/reset")
    assert resp.status_code == 200
    mock_service.reset_kill_switch.assert_called_once_with("acc-1")


def test_lock_position(client, mock_service):
    resp = client.post("/api/v1/accounts/acc-1/ai-manager/positions/BTCUSDT/lock")
    assert resp.status_code == 200
    mock_service.lock_position.assert_called_once_with("acc-1", "BTCUSDT")


def test_unlock_position(client, mock_service):
    resp = client.delete("/api/v1/accounts/acc-1/ai-manager/positions/BTCUSDT/lock")
    assert resp.status_code == 200
    mock_service.unlock_position.assert_called_once_with("acc-1", "BTCUSDT")


def test_get_decisions(client, mock_service):
    resp = client.get("/api/v1/accounts/acc-1/ai-manager/decisions?limit=10")
    assert resp.status_code == 200
    assert "decisions" in resp.json()


def test_get_performance(client, mock_service):
    resp = client.get("/api/v1/accounts/acc-1/ai-manager/performance?period=7d")
    assert resp.status_code == 200


def test_global_kill(client, mock_service):
    resp = client.post("/api/v1/ai-manager/global-kill")
    assert resp.status_code == 200
    mock_service.global_kill.assert_called_once()


def test_service_unavailable(client, mock_service):
    client.app.state.ai_manager_service = None
    resp = client.get("/api/v1/accounts/acc-1/ai-manager/status")
    assert resp.status_code == 503
