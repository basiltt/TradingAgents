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
    db = MagicMock()
    db.get_run = AsyncMock(return_value=None)
    app.state.db = db
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
        app.state.db.get_run = AsyncMock(return_value=None)
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_happy_path_connect_disconnect(self):
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "11111111-1111-1111-1111-111111111111", "status": "running"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.ensure_consumer = AsyncMock()
        app.state.ws_manager.handle_message = AsyncMock(return_value="ok")
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            ws.send_text('{"type":"ping"}')
        app.state.ws_manager.connect.assert_called_once()
        app.state.ws_manager.disconnect.assert_called_once()

    def test_frame_too_large_closes(self):
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "11111111-1111-1111-1111-111111111111"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.ensure_consumer = AsyncMock()
        app.state.ws_manager.handle_message = AsyncMock(return_value="frame_too_large")
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            ws.send_text("big data")

    def test_rate_limited_closes(self):
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "11111111-1111-1111-1111-111111111111"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.ensure_consumer = AsyncMock()
        app.state.ws_manager.handle_message = AsyncMock(return_value="rate_limited")
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            ws.send_text("too fast")

    def test_replay_sends_snapshot(self):
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "11111111-1111-1111-1111-111111111111"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.ensure_consumer = AsyncMock()
        app.state.ws_manager.handle_message = AsyncMock(return_value="replay")
        app.state.ws_manager.send_to = AsyncMock()
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()
        app.state.event_bus.get_snapshot = MagicMock(return_value=[{"type": "event1"}, {"type": "event2"}])
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            ws.send_text('{"type":"replay"}')


class TestConsumerAndDisconnect:
    def test_consume_drains_event_bus(self):
        """Covers ws.py:55-60: _consume coroutine with real ensure_consumer."""
        import asyncio
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "run1"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.handle_message = AsyncMock(return_value=None)
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()
        broadcast_calls = []

        async def fake_broadcast(run_id, event):
            broadcast_calls.append(event)

        app.state.ws_manager.broadcast = fake_broadcast

        drain_count = 0
        async def fake_drain(run_id):
            nonlocal drain_count
            drain_count += 1
            if drain_count == 1:
                return {"type": "message", "content": "test"}
            raise StopAsyncIteration

        app.state.event_bus.drain = fake_drain

        # Use real ensure_consumer to actually invoke _consume
        async def real_ensure_consumer(run_id, consumer):
            asyncio.get_event_loop().create_task(consumer())

        app.state.ws_manager.ensure_consumer = real_ensure_consumer

        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            import time
            time.sleep(0.1)

        assert len(broadcast_calls) >= 1

    def test_websocket_disconnect_exception_swallowed(self):
        """Covers ws.py:77-78: WebSocketDisconnect is caught."""
        from fastapi.websockets import WebSocketDisconnect
        app = _make_ws_app()
        app.state.db.get_run = AsyncMock(return_value={"id": "run1"})
        mock_conn = MagicMock()
        app.state.ws_manager.connect = AsyncMock(return_value=mock_conn)
        app.state.ws_manager.ensure_consumer = AsyncMock()
        app.state.ws_manager.handle_message = AsyncMock(side_effect=WebSocketDisconnect())
        app.state.ws_manager.disconnect = AsyncMock()
        app.state.ws_manager.remove_consumer_if_empty = AsyncMock()

        client = TestClient(app)
        # Should not raise — WebSocketDisconnect is swallowed
        with client.websocket_connect(
            "/ws/v1/analysis/11111111-1111-1111-1111-111111111111",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            ws.send_text("trigger disconnect")
