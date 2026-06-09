"""WebSocket connection manager — TASK-011."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30
_PONG_TIMEOUT = 90
_OUTBOUND_BUFFER_SIZE = 2048
_INBOUND_FRAME_MAX = 4096
_INBOUND_RATE_LIMIT = 10  # per second


class WSConnection:
    """Wraps a single WebSocket connection with send buffering and heartbeat monitoring."""

    def __init__(self, ws: WebSocket, run_id: str):
        self.ws = ws
        self.run_id = run_id
        self.outbound: asyncio.Queue = asyncio.Queue(maxsize=_OUTBOUND_BUFFER_SIZE)
        self.last_pong: float = time.monotonic()
        self._send_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._seq = 0
        self._msg_timestamps: list[float] = []
        self._closed = False

    def next_seq(self) -> int:
        """Return the next outbound message sequence number for this connection."""
        self._seq += 1
        return self._seq


class WSManager:
    """Manages all active WebSocket connections, routing events by run_id.

    Consumes from EventBus per-run queues and fans out to all connected clients.
    Handles slow consumers via bounded outbound queues and heartbeat-based pruning.
    """

    def __init__(self, event_bus: Any = None):
        self._connections: Dict[str, Set[WSConnection]] = {}
        self._event_bus = event_bus
        self._lock = asyncio.Lock()
        self._consumers: Dict[str, asyncio.Task] = {}
        self._consumer_lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, run_id: str) -> WSConnection:
        """Register a new WebSocket for a run and start its send/heartbeat loops.

        Returns the wrapping WSConnection.
        """
        conn = WSConnection(ws, run_id)
        async with self._lock:
            if run_id not in self._connections:
                self._connections[run_id] = set()
            self._connections[run_id].add(conn)

        conn._send_task = asyncio.create_task(self._send_loop(conn))
        conn._heartbeat_task = asyncio.create_task(self._heartbeat_loop(conn))
        return conn

    async def disconnect(self, conn: WSConnection) -> None:
        """Remove a connection, drop empty run groups, and cancel its loops.

        Idempotent — a no-op if the connection is already closed.
        """
        if conn._closed:
            return
        conn._closed = True

        async with self._lock:
            conns = self._connections.get(conn.run_id)
            if conns:
                conns.discard(conn)
                if not conns:
                    del self._connections[conn.run_id]

        if conn._send_task:
            conn._send_task.cancel()
        if conn._heartbeat_task:
            conn._heartbeat_task.cancel()

    async def broadcast(self, run_id: str, event: Dict[str, Any]) -> None:
        """Enqueue an event to every connection for a run.

        Events are dropped (and logged) for any connection whose outbound queue
        is full, so a slow consumer cannot block the broadcast.
        """
        async with self._lock:
            conns = list(self._connections.get(run_id, set()))

        for conn in conns:
            try:
                conn.outbound.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Queue full on run %s, dropping event", run_id)

    async def send_to(self, conn: WSConnection, event: Dict[str, Any]) -> None:
        """Enqueue an event to a single connection, closing it if its queue is full."""
        try:
            conn.outbound.put_nowait(event)
        except asyncio.QueueFull:
            asyncio.create_task(self._close_slow(conn))

    async def _send_loop(self, conn: WSConnection) -> None:
        try:
            while True:
                event = await conn.outbound.get()
                out = {**event, "seq": conn.next_seq()}
                await conn.ws.send_json(out)
        except Exception:
            await self.disconnect(conn)

    async def _heartbeat_loop(self, conn: WSConnection) -> None:
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                try:
                    conn.outbound.put_nowait({"type": "heartbeat"})
                except asyncio.QueueFull:
                    break
                if time.monotonic() - conn.last_pong > _PONG_TIMEOUT:
                    logger.warning("Pong timeout for run %s", conn.run_id)
                    await conn.ws.close(code=1008, reason="Pong timeout")
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await self.disconnect(conn)

    async def handle_message(self, conn: WSConnection, raw: str) -> Optional[str]:
        """Validate and process an inbound client frame; return its message type.

        Enforces a max frame size ("frame_too_large") and a per-second rate limit
        ("rate_limited"), returns None for non-JSON payloads, and updates last_pong
        on "pong" frames. Otherwise returns the parsed message type.
        """
        if len(raw) > _INBOUND_FRAME_MAX:
            return "frame_too_large"

        now = time.monotonic()
        cutoff = now - 1.0
        conn._msg_timestamps = [t for t in conn._msg_timestamps if t > cutoff]
        if len(conn._msg_timestamps) >= _INBOUND_RATE_LIMIT:
            return "rate_limited"
        conn._msg_timestamps.append(now)

        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        msg_type = msg.get("type")
        if msg_type == "pong":
            conn.last_pong = time.monotonic()
        elif msg_type == "replay":
            pass

        return msg_type

    async def _close_slow(self, conn: WSConnection) -> None:
        try:
            await conn.ws.close(code=1008, reason="Slow consumer")
        except Exception:
            pass
        await self.disconnect(conn)

    def get_connection_count(self, run_id: str) -> int:
        """Return the number of active connections for a run."""
        return len(self._connections.get(run_id, set()))

    async def ensure_consumer(self, run_id: str, consume_fn) -> None:
        """Start the per-run event-bus consumer task if one is not already running.

        The task self-removes from the registry on completion via a done-callback.
        """
        async with self._consumer_lock:
            task = self._consumers.get(run_id)
            if task and not task.done():
                return
            task = asyncio.create_task(consume_fn())
            def _done_cb(_t: asyncio.Task[None], _rid: str = run_id) -> None:
                self._on_consumer_done(_rid)
            task.add_done_callback(_done_cb)
            self._consumers[run_id] = task

    def _on_consumer_done(self, run_id: str) -> None:
        """Remove a finished consumer task from _consumers (done-callback)."""
        self._consumers.pop(run_id, None)

    async def remove_consumer_if_empty(self, run_id: str) -> None:
        """Cancel and drop the run's consumer task if it has no remaining connections."""
        async with self._lock:
            count = len(self._connections.get(run_id, set()))
        if count > 0:
            return
        async with self._consumer_lock:
            task = self._consumers.pop(run_id, None)
        if task and not task.done():
            task.cancel()

    async def shutdown(self) -> None:
        """Cancel and await all per-run consumer tasks (graceful teardown)."""
        async with self._consumer_lock:
            tasks = list(self._consumers.values())
            self._consumers.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
