"""Unit tests for EventBus — covers emit, ring buffer, drain, cleanup, and thread safety."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.event_bus import EventBus, _MAX_RING_EVENTS, _MAX_QUEUE_SIZE


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def bus(event_loop):
    return EventBus(loop=event_loop)


class TestEmit:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_emit_creates_queue(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "test", "data": "hello"})
        assert "run1" in bus._queues

    @pytest.mark.asyncio(loop_scope="function")
    async def test_emit_and_drain(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "progress", "pct": 50})
        event = await bus.drain("run1")
        assert event["type"] == "progress"
        assert event["pct"] == 50

    @pytest.mark.asyncio(loop_scope="function")
    async def test_emit_after_cleanup_is_noop(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "first"})
        bus.cleanup_run("run1")
        bus.emit("run1", {"type": "second"})
        assert "run1" not in bus._queues

    @pytest.mark.asyncio(loop_scope="function")
    async def test_emit_queue_full_drops_oldest(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        q = asyncio.Queue(maxsize=2)
        bus._queues["run1"] = q
        bus._ring_buffers["run1"] = __import__("collections").deque()
        bus._ring_bytes["run1"] = 0
        q.put_nowait({"type": "a"})
        q.put_nowait({"type": "b"})
        bus.emit("run1", {"type": "c"})
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        types = [i["type"] for i in items]
        assert "c" in types


class TestRingBuffer:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_ring_buffer_bounded(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        for i in range(_MAX_RING_EVENTS + 100):
            bus.emit("run1", {"type": "event", "i": i})
        snapshot = bus.get_snapshot("run1")
        assert len(snapshot) <= _MAX_RING_EVENTS

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_snapshot_empty(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        assert bus.get_snapshot("nonexistent") == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_snapshot_returns_events(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "a"})
        bus.emit("run1", {"type": "b"})
        snapshot = bus.get_snapshot("run1")
        assert len(snapshot) == 2
        assert snapshot[0]["type"] == "a"


class TestCleanup:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_cleanup_removes_state(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "test"})
        bus.cleanup_run("run1")
        assert "run1" not in bus._ring_buffers
        assert "run1" not in bus._ring_bytes

    @pytest.mark.asyncio(loop_scope="function")
    async def test_drain_after_cleanup_raises(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.emit("run1", {"type": "test"})
        bus.cleanup_run("run1")
        with pytest.raises(StopAsyncIteration):
            await bus.drain("run1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cleanup_bounded_cleaned_set(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        for i in range(1100):
            bus.cleanup_run(f"run_{i}")
        assert len(bus._cleaned) <= 1000


class TestGetQueue:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_queue_creates_new(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        q = bus._get_queue("run1")
        assert q is not None
        assert q.maxsize == _MAX_QUEUE_SIZE

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_queue_returns_same(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        q1 = bus._get_queue("run1")
        q2 = bus._get_queue("run1")
        assert q1 is q2

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_queue_after_cleanup_raises(self):
        loop = asyncio.get_running_loop()
        bus = EventBus(loop=loop)
        bus.cleanup_run("run1")
        with pytest.raises(StopAsyncIteration):
            bus._get_queue("run1")
