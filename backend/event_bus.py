"""Event bus — thread-safe bridge between sync callbacks and async WS layer — TASK-009."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Callable, Deque, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_MAX_RING_EVENTS = 500
_MAX_RING_BYTES = 2 * 1024 * 1024  # 2MB


class EventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queues: Dict[str, asyncio.Queue] = defaultdict(lambda: asyncio.Queue(maxsize=1000))
        self._ring_buffers: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._ring_bytes: Dict[str, int] = defaultdict(int)
        self._subscribers: Dict[str, Set[Callable]] = defaultdict(set)
        self._lock = threading.Lock()

    def emit(self, run_id: str, event: Any) -> None:
        event_dict = asdict(event) if hasattr(event, "__dataclass_fields__") else event
        queue = self._queues[run_id]

        if event_dict.get("type") != "report_chunk":
            with self._lock:
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

        buf = self._ring_buffers[run_id]
        buf.append(event_dict)
        self._ring_bytes[run_id] += event_bytes

        while len(buf) > _MAX_RING_EVENTS or self._ring_bytes[run_id] > _MAX_RING_BYTES:
            if not buf:
                break
            removed = buf.popleft()
            self._ring_bytes[run_id] -= len(json.dumps(removed))

    async def drain(self, run_id: str) -> Any:
        return await self._queues[run_id].get()

    def subscribe(self, run_id: str, callback: Callable) -> None:
        self._subscribers[run_id].add(callback)

    def unsubscribe(self, run_id: str, callback: Callable) -> None:
        self._subscribers[run_id].discard(callback)

    def get_snapshot(self, run_id: str) -> List[Dict[str, Any]]:
        return list(self._ring_buffers.get(run_id, []))

    def cleanup_run(self, run_id: str) -> None:
        self._queues.pop(run_id, None)
        self._ring_buffers.pop(run_id, None)
        self._ring_bytes.pop(run_id, None)
        self._subscribers.pop(run_id, None)
