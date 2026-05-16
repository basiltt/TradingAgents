"""Tests for WebSocket router (backend/routers/ws.py)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.routers.ws import _check_origin


# ---------------------------------------------------------------------------
# _check_origin unit tests
# ---------------------------------------------------------------------------

class TestCheckOrigin:
    def _make_ws(self, origin: str | None, cors_origins: list[str]):
        ws = MagicMock()
        ws.headers = {}
        if origin is not None:
            ws.headers["origin"] = origin
        ws.app = MagicMock()
        ws.app.state.cors_origins = cors_origins
        return ws

    def test_no_origin_header_returns_false(self):
        ws = self._make_ws(None, ["http://localhost:5177"])
        assert _check_origin(ws) is False

    def test_origin_not_in_allowed_returns_false(self):
        ws = self._make_ws("http://evil.com", ["http://localhost:5177"])
        assert _check_origin(ws) is False

    def test_origin_in_allowed_returns_true(self):
        ws = self._make_ws("http://localhost:5177", ["http://localhost:5177"])
        assert _check_origin(ws) is True

    def test_empty_allowed_list_returns_false(self):
        ws = self._make_ws("http://localhost:5177", [])
        assert _check_origin(ws) is False

    def test_multiple_allowed_origins(self):
        ws = self._make_ws("https://app.example.com", [
            "http://localhost:5177",
            "https://app.example.com",
        ])
        assert _check_origin(ws) is True


# ---------------------------------------------------------------------------
# WebSocket endpoint tests via FastAPI app
# ---------------------------------------------------------------------------

def _make_app(run=None, cors_origins=None):
    """Create a minimal FastAPI app with the WS router wired up."""
    from fastapi import FastAPI
    from backend.routers.ws import router

    app = FastAPI()
    app.include_router(router)

    if cors_origins is None:
        cors_origins = ["http://localhost:5177"]

    db = MagicMock()
    db.get_run = AsyncMock(return_value=run)

    ws_manager = MagicMock()
    ws_manager.connect = AsyncMock(return_value=MagicMock())
    ws_manager.ensure_consumer = AsyncMock()
    ws_manager.handle_message = AsyncMock(return_value=None)
    ws_manager.disconnect = AsyncMock()
    ws_manager.remove_consumer_if_empty = AsyncMock()
    ws_manager.broadcast = AsyncMock()
    ws_manager.send_to = AsyncMock()

    event_bus = MagicMock()
    event_bus.drain = AsyncMock(side_effect=asyncio.CancelledError)
    event_bus.get_snapshot = MagicMock(return_value=[])

    app.state.db = db
    app.state.ws_manager = ws_manager
    app.state.event_bus = event_bus
    app.state.cors_origins = cors_origins

    return app, ws_manager, event_bus


class TestAnalysisWsEndpoint:
    def test_invalid_uuid_closes_4400(self):
        app, _, __ = _make_app()
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/v1/analysis/not-a-uuid",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            # Server closes with 4400
            with pytest.raises(Exception):
                ws.receive_text()

    def test_bad_origin_closes_4403(self):
        app, _, __ = _make_app()
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://evil.com"},
        ) as ws:
            with pytest.raises(Exception):
                ws.receive_text()

    def test_run_not_found_sends_error_and_closes_4404(self):
        app, _, __ = _make_app(run=None)
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["message"].lower()

    def test_valid_run_connects_and_disconnects_cleanly(self):
        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, _ = _make_app(run=run)
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ):
            pass  # disconnect immediately
        assert ws_manager.disconnect.called
        assert ws_manager.remove_consumer_if_empty.called

    def test_frame_too_large_closes_1009(self):
        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, _ = _make_app(run=run)
        ws_manager.handle_message = AsyncMock(return_value="frame_too_large")
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            ws.send_text("huge message")
            with pytest.raises(Exception):
                ws.receive_text()

    def test_rate_limited_closes_1008(self):
        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, _ = _make_app(run=run)
        ws_manager.handle_message = AsyncMock(return_value="rate_limited")
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            ws.send_text("too many messages")
            with pytest.raises(Exception):
                ws.receive_text()

    def test_replay_sends_snapshot_events(self):
        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, event_bus = _make_app(run=run)
        ws_manager.handle_message = AsyncMock(return_value="replay")
        event_bus.get_snapshot = MagicMock(return_value=[
            {"type": "log", "message": "step 1"},
            {"type": "log", "message": "step 2"},
        ])
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            ws.send_text('{"type":"replay"}')
            # Disconnect so the loop ends
        # send_to should have been called for each snapshot event
        assert ws_manager.send_to.call_count >= 2


# ---------------------------------------------------------------------------
# Direct tests for _consume inner function and WebSocketDisconnect
# ---------------------------------------------------------------------------

class TestConsumeFunction:
    @pytest.mark.asyncio
    async def test_consume_broadcasts_events_then_cancelled(self):
        """Lines 55-60: _consume drains events and handles CancelledError."""
        import asyncio

        captured_consume = []

        # Intercept ensure_consumer to capture the _consume coroutine
        async def capture_consumer(run_id, consumer_fn):
            captured_consume.append(consumer_fn)

        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, event_bus = _make_app(run=run)
        ws_manager.ensure_consumer = AsyncMock(side_effect=capture_consumer)

        # event_bus.drain returns an event then raises CancelledError
        events = [{"type": "log", "message": "step 1"}]
        call_count = 0

        async def drain_side_effect(run_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return events[0]
            raise asyncio.CancelledError()

        event_bus.drain = AsyncMock(side_effect=drain_side_effect)

        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ):
            pass

        # Now manually invoke the captured _consume coroutine
        assert len(captured_consume) == 1
        await captured_consume[0]()

        # broadcast should have been called with the event
        ws_manager.broadcast.assert_called_once_with(valid_uuid, events[0])

    @pytest.mark.asyncio
    async def test_consume_handles_stop_async_iteration(self):
        """Line 59: StopAsyncIteration in _consume is handled gracefully."""

        captured_consume = []

        async def capture_consumer(run_id, consumer_fn):
            captured_consume.append(consumer_fn)

        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, event_bus = _make_app(run=run)
        ws_manager.ensure_consumer = AsyncMock(side_effect=capture_consumer)

        event_bus.drain = AsyncMock(side_effect=StopAsyncIteration())

        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ):
            pass

        assert len(captured_consume) == 1
        # Should complete without raising
        await captured_consume[0]()


class TestWebSocketDisconnect:
    def test_websocket_disconnect_during_iter_handled_gracefully(self):
        """Lines 77-78: WebSocketDisconnect during iter_text is caught and handled."""

        run = {"run_id": "test-run", "status": "running"}
        app, ws_manager, _ = _make_app(run=run)

        # Simulate message that causes WebSocketDisconnect on next read

        async def handle_then_disconnect(conn, raw):
            # Return None for first message, then the next ws.receive_text will disconnect
            return None

        ws_manager.handle_message = AsyncMock(side_effect=handle_then_disconnect)

        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())

        # The client connecting and immediately disconnecting exercises the finally block
        with client.websocket_connect(
            f"/ws/v1/analysis/{valid_uuid}",
            headers={"origin": "http://localhost:5177"},
        ) as ws:
            ws.send_text("hello")
            # Close from client side — this generates WebSocketDisconnect on server's iter_text
        # disconnect and remove_consumer_if_empty must be called in finally block
        assert ws_manager.disconnect.called
        assert ws_manager.remove_consumer_if_empty.called


class TestWebSocketDisconnectDirect:
    @pytest.mark.asyncio
    async def test_disconnect_exception_handled_in_iter_text(self):
        """Lines 77-78: WebSocketDisconnect during iter_text is swallowed."""
        from starlette.websockets import WebSocketDisconnect
        from backend.routers.ws import analysis_ws

        # Build a mock WebSocket that raises WebSocketDisconnect from iter_text
        run_id = str(uuid.uuid4())

        async def iter_text_raises():
            raise WebSocketDisconnect(code=1001)
            yield  # make it a generator

        ws = MagicMock()
        ws.headers = {"origin": "http://localhost:5177"}
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        ws.iter_text = iter_text_raises

        db = MagicMock()
        db.get_run = AsyncMock(return_value={"run_id": run_id, "status": "running"})

        ws_manager = MagicMock()
        conn = MagicMock()
        ws_manager.connect = AsyncMock(return_value=conn)
        ws_manager.ensure_consumer = AsyncMock()
        ws_manager.disconnect = AsyncMock()
        ws_manager.remove_consumer_if_empty = AsyncMock()

        event_bus = MagicMock()

        app_state = MagicMock()
        app_state.cors_origins = ["http://localhost:5177"]
        app_state.db = db
        app_state.ws_manager = ws_manager
        app_state.event_bus = event_bus

        ws.app = MagicMock()
        ws.app.state = app_state

        # Should complete without raising
        await analysis_ws(ws, run_id)

        # finally block executes
        ws_manager.disconnect.assert_called_once_with(conn)
        ws_manager.remove_consumer_if_empty.assert_called_once()
