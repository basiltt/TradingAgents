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


def test_rate_limiting(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        for _ in range(10):
            result = await ws_manager.handle_message(conn, '{"type": "pong"}')
            assert result != "rate_limited"
        result = await ws_manager.handle_message(conn, '{"type": "pong"}')
        assert result == "rate_limited"
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())


def test_replay_returns_type(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        result = await ws_manager.handle_message(conn, '{"type": "replay"}')
        assert result == "replay"
        await ws_manager.disconnect(conn)

    event_loop.run_until_complete(_test())


def test_double_disconnect_idempotent(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")
        await ws_manager.disconnect(conn)
        await ws_manager.disconnect(conn)
        assert ws_manager.get_connection_count("run1") == 0

    event_loop.run_until_complete(_test())


def test_ensure_consumer(ws_manager, event_loop):
    async def _test():
        called = asyncio.Event()

        async def consume():
            called.set()

        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        assert called.is_set()
        # cleanup
        for task in ws_manager._consumers.values():
            task.cancel()

    event_loop.run_until_complete(_test())


def test_ensure_consumer_no_duplicate(ws_manager, event_loop):
    async def _test():
        count = 0

        async def consume():
            nonlocal count
            count += 1
            await asyncio.sleep(10)

        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        assert count == 1
        for task in ws_manager._consumers.values():
            task.cancel()

    event_loop.run_until_complete(_test())


def test_remove_consumer_if_empty(ws_manager, event_loop):
    async def _test():
        async def consume():
            await asyncio.sleep(10)

        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        await ws_manager.remove_consumer_if_empty("run1")
        assert "run1" not in ws_manager._consumers

    event_loop.run_until_complete(_test())


def test_remove_consumer_not_empty(ws_manager, event_loop):
    async def _test():
        ws = _mock_ws()
        conn = await ws_manager.connect(ws, "run1")

        async def consume():
            await asyncio.sleep(10)

        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        await ws_manager.remove_consumer_if_empty("run1")
        assert "run1" in ws_manager._consumers
        await ws_manager.disconnect(conn)
        for task in ws_manager._consumers.values():
            task.cancel()

    event_loop.run_until_complete(_test())


def test_shutdown(ws_manager, event_loop):
    async def _test():
        async def consume():
            await asyncio.sleep(10)

        await ws_manager.ensure_consumer("run1", consume)
        await asyncio.sleep(0.05)
        await ws_manager.shutdown()
        assert len(ws_manager._consumers) == 0

    event_loop.run_until_complete(_test())


def test_get_connection_count_nonexistent(ws_manager):
    assert ws_manager.get_connection_count("nope") == 0
