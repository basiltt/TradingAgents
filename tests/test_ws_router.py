"""Tests for backend.routers.ws — Phase 1 unit tests."""

from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.ws import router, _check_origin


def _make_ws_app():
    app = FastAPI()
    app.include_router(router)
    app.state.cors_origins = ["http://localhost:3000"]
    app.state.ws_manager = AsyncMock()
    app.state.event_bus = MagicMock()
    app.state.db = MagicMock()
    return app


class TestCheckOrigin:
    def test_no_origin_header(self):
        ws = MagicMock()
        ws.headers = {}
        assert _check_origin(ws) is False

    def test_allowed_origin(self):
        ws = MagicMock()
        ws.headers = {"origin": "http://localhost:3000"}
        ws.app.state.cors_origins = ["http://localhost:3000", "http://localhost:5173"]
        assert _check_origin(ws) is True

    def test_disallowed_origin(self):
        ws = MagicMock()
        ws.headers = {"origin": "http://evil.com"}
        ws.app.state.cors_origins = ["http://localhost:3000"]
        assert _check_origin(ws) is False


class TestAnalysisWsEndpoint:
    def test_invalid_run_id(self):
        app = _make_ws_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/v1/analysis/not-a-uuid") as ws:
            pass  # should close with 4400

    def test_origin_rejected(self):
        app = _make_ws_app()
        app.state.cors_origins = ["http://allowed.com"]
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://evil.com"},
        ) as ws:
            pass  # should close with 4403

    def test_run_not_found(self):
        app = _make_ws_app()
        app.state.db.get_run = MagicMock(return_value=None)
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "error"
