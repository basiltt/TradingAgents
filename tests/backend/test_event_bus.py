"""Tests for event bus — TASK-009."""

import asyncio
import json

import pytest


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def bus(event_loop):
    from backend.event_bus import EventBus
    return EventBus(loop=event_loop)


def test_emit_and_drain(bus, event_loop):
    async def _test():
        bus.emit("run1", {"type": "message", "content": "hello"})
        event = await asyncio.wait_for(bus.drain("run1"), timeout=1.0)
        assert event["content"] == "hello"

    event_loop.run_until_complete(_test())


def test_queue_full_drops_oldest(bus, event_loop):
    async def _test():
        from backend.event_bus import EventBus
        small_bus = EventBus(loop=event_loop)
        small_bus._queues["run1"] = asyncio.Queue(maxsize=2)
        small_bus.emit("run1", {"type": "a", "n": 1})
        small_bus.emit("run1", {"type": "b", "n": 2})
        small_bus.emit("run1", {"type": "c", "n": 3})
        first = await small_bus.drain("run1")
        assert first["n"] == 2

    event_loop.run_until_complete(_test())


def test_ring_buffer_includes_report_chunk(bus, event_loop):
    bus.emit("run1", {"type": "report_chunk", "content": "data"})
    bus.emit("run1", {"type": "message", "content": "hello"})
    snapshot = bus.get_snapshot("run1")
    assert len(snapshot) == 2
    assert snapshot[0]["type"] == "report_chunk"
    assert snapshot[1]["type"] == "message"


def test_ring_buffer_count_overflow(bus, event_loop):
    from backend import event_bus
    original = event_bus._MAX_RING_EVENTS
    event_bus._MAX_RING_EVENTS = 3
    try:
        for i in range(5):
            bus.emit("run1", {"type": "message", "n": i})
        snapshot = bus.get_snapshot("run1")
        assert len(snapshot) == 3
        assert snapshot[0]["n"] == 2
    finally:
        event_bus._MAX_RING_EVENTS = original


def test_ring_buffer_byte_overflow(bus, event_loop):
    from backend import event_bus
    original = event_bus._MAX_RING_BYTES
    event_bus._MAX_RING_BYTES = 100
    try:
        bus.emit("run1", {"type": "message", "data": "x" * 50})
        bus.emit("run1", {"type": "message", "data": "y" * 50})
        snapshot = bus.get_snapshot("run1")
        assert len(snapshot) <= 2
    finally:
        event_bus._MAX_RING_BYTES = original


def test_cleanup_run(bus, event_loop):
    bus.emit("run1", {"type": "message"})
    bus.cleanup_run("run1")
    assert bus.get_snapshot("run1") == []


def test_drain_after_cleanup_raises(bus, event_loop):
    async def _test():
        bus.emit("run1", {"type": "message"})
        bus.cleanup_run("run1")
        with pytest.raises(StopAsyncIteration):
            await bus.drain("run1")

    event_loop.run_until_complete(_test())


def test_emit_on_cleaned_run_is_noop(bus, event_loop):
    bus.emit("run1", {"type": "message"})
    bus.cleanup_run("run1")
    bus.emit("run1", {"type": "message2"})
    assert bus.get_snapshot("run1") == []


def test_cleanup_with_full_queue(bus, event_loop):
    async def _test():
        small_queue = asyncio.Queue(maxsize=1)
        small_queue.put_nowait({"type": "blocking"})
        bus._queues["run1"] = small_queue
        bus.cleanup_run("run1")
        with pytest.raises(StopAsyncIteration):
            await bus.drain("run1")

    event_loop.run_until_complete(_test())


def test_thread_safe_emit(bus, event_loop):
    import threading

    async def _test():
        done = asyncio.Event()

        def bg():
            bus.emit_threadsafe("run1", {"type": "message", "from": "thread"})

        t = threading.Thread(target=bg)
        t.start()
        t.join()
        await asyncio.sleep(0.1)
        event = await asyncio.wait_for(bus.drain("run1"), timeout=2.0)
        assert event["from"] == "thread"

    event_loop.run_until_complete(_test())
