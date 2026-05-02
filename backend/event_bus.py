"""Event bus — thread-safe bridge between sync callbacks and async WS layer — TASK-009."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque, OrderedDict
from dataclasses import asdict
from typing import Any, Callable, Deque, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

_MAX_RING_EVENTS = 500
_MAX_RING_BYTES = 2 * 1024 * 1024  # 2MB
_MAX_CLEANED_IDS = 1000
_MAX_QUEUE_SIZE = 1000

_POISON = {"type": "_poison"}


class EventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queues: Dict[str, asyncio.Queue] = {}
        self._ring_buffers: Dict[str, Deque[Tuple[Dict[str, Any], int]]] = {}
        self._ring_bytes: Dict[str, int] = {}
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._cleaned: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def _get_queue(self, run_id: str) -> asyncio.Queue:
        with self._lock:
            if run_id in self._cleaned:
                raise StopAsyncIteration(f"Run {run_id} already cleaned up")
            if run_id not in self._queues:
                self._queues[run_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
            return self._queues[run_id]

    def emit(self, run_id: str, event: Any) -> None:
        """Must only be called from the event loop thread. Use emit_threadsafe() from other threads."""
        event_dict = asdict(event) if hasattr(event, "__dataclass_fields__") else event

        with self._lock:
            if run_id in self._cleaned:
                return
            queue = self._queues.get(run_id)
            if queue is None:
                self._queues[run_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
                queue = self._queues[run_id]

            if event_dict.get("type") != "report_chunk":
                self._add_to_ring(run_id, event_dict)

        try:
            queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning("Event bus queue full for run %s, dropping oldest", run_id)
            with self._lock:
                self._add_to_ring(run_id, {"type": "events_dropped", "run_id": run_id})
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

    def emit_threadsafe(self, run_id: str, event: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            self._async_emit(run_id, event), self._loop
        )

    async def _async_emit(self, run_id: str, event: Any) -> None:
        self.emit(run_id, event)

    def _add_to_ring(self, run_id: str, event_dict: Dict[str, Any]) -> None:
        serialized = json.dumps(event_dict)
        event_bytes = len(serialized)

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

    def subscribe(self, run_id: str, callback: Callable) -> None:
        with self._lock:
            if run_id not in self._subscribers:
                self._subscribers[run_id] = set()
            self._subscribers[run_id].add(callback)

    def unsubscribe(self, run_id: str, callback: Callable) -> None:
        with self._lock:
            if run_id in self._subscribers:
                self._subscribers[run_id].discard(callback)

    def get_snapshot(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            buf = self._ring_buffers.get(run_id, [])
            return [ev for ev, _ in buf]

    def cleanup_run(self, run_id: str) -> None:
        with self._lock:
            self._cleaned[run_id] = None
            if len(self._cleaned) > _MAX_CLEANED_IDS:
                self._cleaned.popitem(last=False)
            queue = self._queues.pop(run_id, None)
            self._ring_buffers.pop(run_id, None)
            self._ring_bytes.pop(run_id, None)
            self._subscribers.pop(run_id, None)
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
