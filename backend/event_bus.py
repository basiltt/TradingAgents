"""Event bus — thread-safe bridge between sync callbacks and async WS layer — TASK-009."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict, deque
from dataclasses import asdict
from typing import Any, Deque, Dict, List, Tuple

logger = logging.getLogger(__name__)

_MAX_RING_EVENTS = 500
_MAX_RING_BYTES = 2 * 1024 * 1024  # 2MB
_MAX_CLEANED_IDS = 1000
_MAX_QUEUE_SIZE = 1000
_RING_BYTES_OVERHEAD = 64
_RING_BYTES_PER_FIELD = 32

_POISON = {"type": "_poison"}


class EventBus:
    """In-process pub/sub with per-run ring buffers for event replay.

    Bridges sync callbacks (LangGraph tool calls) to async WebSocket consumers.
    Each run_id gets a bounded queue for live streaming and a ring buffer (capped
    by count and bytes) for late-joining clients to replay recent events.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queues: Dict[str, asyncio.Queue] = {}
        self._ring_buffers: Dict[str, Deque[Tuple[Dict[str, Any], int]]] = {}
        self._ring_bytes: Dict[str, int] = {}
        self._cleaned: OrderedDict[str, None] = OrderedDict()
        # Lock only for cleanup_run and get_snapshot (called infrequently);
        # emit/drain run lock-free on the event loop thread.
        self._lock = threading.Lock()

    def _get_queue(self, run_id: str) -> asyncio.Queue:
        """Called from event loop thread only (via drain)."""
        if run_id in self._cleaned:
            raise StopAsyncIteration(f"Run {run_id} already cleaned up")
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        return self._queues[run_id]

    def emit(self, run_id: str, event: Any) -> None:
        """Must only be called from the event loop thread. Use emit_threadsafe() from other threads.

        Does NOT acquire the threading lock — this runs exclusively on the event
        loop thread so dict/queue access is safe without locking.  The only writers
        that mutate _queues/_cleaned from other threads go through emit_threadsafe
        (which schedules back onto this thread) or cleanup_run (which holds _lock
        and only removes entries, safe against concurrent reads on this thread).
        """
        if __debug__:
            try:
                running = asyncio.get_running_loop()
                assert running is self._loop, "emit() must be called from the event loop thread"
            except RuntimeError:
                pass
        event_dict = asdict(event) if hasattr(event, "__dataclass_fields__") else event

        if run_id in self._cleaned:
            return
        queue = self._queues.get(run_id)
        if queue is None:
            self._queues[run_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
            queue = self._queues[run_id]

        self._add_to_ring(run_id, event_dict)

        try:
            queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning("Event bus queue full for run %s, dropping oldest", run_id)
            self._add_to_ring(run_id, {"type": "events_dropped", "run_id": run_id})
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

    def emit_threadsafe(self, run_id: str, event: Any) -> None:
        event_dict = asdict(event) if hasattr(event, "__dataclass_fields__") else event
        self._loop.call_soon_threadsafe(self._emit_from_threadsafe, run_id, event_dict)

    def _emit_from_threadsafe(self, run_id: str, event_dict: Dict[str, Any]) -> None:
        """Callback scheduled on the event loop by emit_threadsafe. Lock-free."""
        if run_id in self._cleaned:
            return
        queue = self._queues.get(run_id)
        if queue is None:
            self._queues[run_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
            queue = self._queues[run_id]

        self._add_to_ring(run_id, event_dict)

        try:
            queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

    def _add_to_ring(self, run_id: str, event_dict: Dict[str, Any]) -> None:
        # Rough byte estimate: 64 bytes overhead + 32 per key-value pair avoids str() cost
        event_bytes = _RING_BYTES_OVERHEAD + _RING_BYTES_PER_FIELD * len(event_dict)

        if run_id not in self._ring_buffers:
            self._ring_buffers[run_id] = deque()
            self._ring_bytes[run_id] = 0

        buf = self._ring_buffers[run_id]
        buf.append((event_dict, event_bytes))
        self._ring_bytes[run_id] += event_bytes

        while len(buf) > _MAX_RING_EVENTS or self._ring_bytes[run_id] > _MAX_RING_BYTES:
            if not buf:
                break
            _, removed_bytes = buf.popleft()
            self._ring_bytes[run_id] -= removed_bytes

    async def drain(self, run_id: str) -> Any:
        queue = self._get_queue(run_id)
        event = await queue.get()
        if event is _POISON:
            raise StopAsyncIteration(f"Run {run_id} cleaned up")
        return event

    def get_snapshot(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            buf = list(self._ring_buffers.get(run_id, []))
            return [ev for ev, _ in buf]

    def cleanup_run(self, run_id: str) -> None:
        with self._lock:
            self._cleaned[run_id] = None
            if len(self._cleaned) > _MAX_CLEANED_IDS:
                self._cleaned.popitem(last=False)
            queue = self._queues.pop(run_id, None)
            self._ring_buffers.pop(run_id, None)
            self._ring_bytes.pop(run_id, None)
        if queue:
            try:
                queue.put_nowait(_POISON)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(_POISON)
                except asyncio.QueueFull:
                    pass
