"""Tests for WebSocket manager — TASK-011."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def ws_manager():
    from backend.ws_manager import WSManager
    return WSManager()


def _mock_ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def test_connect_and_disconnect(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        assert ws_manager.get_connection_count("run1") == 1
        await ws_manager.disconnect(conn)
        assert ws_manager.get_connection_count("run1") == 0

    event_loop.run_until_complete(_test())


def test_broadcast(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        await ws_manager.broadcast("run1", {"type": "message", "content": "hello"})
        await asyncio.sleep(0.1)
        ws.send_json.assert_called()
        sent = ws.send_json.call_args[0][0]
        assert sent["content"] == "hello"
        assert "seq" in sent
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())


def test_handle_pong(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        old_pong = conn.last_pong
        await asyncio.sleep(0.01)
        await ws_manager.handle_message(conn, '{"type": "pong"}')
        assert conn.last_pong > old_pong
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())


def test_frame_too_large(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        result = await ws_manager.handle_message(conn, "x" * 5000)
        assert result == "frame_too_large"
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())


def test_invalid_json_handled(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        result = await ws_manager.handle_message(conn, "not json")
        assert result is None
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())
