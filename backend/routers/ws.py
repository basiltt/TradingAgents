"""WebSocket endpoint — TASK-014."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

logger = logging.getLogger(__name__)


def _check_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    allowed = set(websocket.app.state.cors_origins)
    if origin in allowed:
        return True
    # Also allow any origin whose port matches a configured CORS origin's port.
    # This lets browsers on other LAN devices connect through the Vite proxy
    # (which preserves the Origin header but rewrites Host).
    try:
        from urllib.parse import urlparse
        origin_port = urlparse(origin).port
        if origin_port is not None:
            for a in allowed:
                if urlparse(a).port == origin_port:
                    return True
    except Exception:
        pass
    return False


@router.websocket("/ws/v1/analysis/{run_id}")
async def analysis_ws(websocket: WebSocket, run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        await websocket.accept()
        await websocket.close(code=4400, reason="Invalid run_id")
        return

    app = websocket.app
    ws_manager = app.state.ws_manager
    event_bus = app.state.event_bus
    db = app.state.db

    if not _check_origin(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    run = await db.get_run(run_id)
    if not run:
        await websocket.accept()
        await websocket.send_json({"type": "error", "seq": 0, "message": "Run not found"})
        await websocket.close(code=4404, reason="Run not found")
        return

    await websocket.accept()
    conn = await ws_manager.connect(websocket, run_id)

    async def _consume():
        try:
            while True:
                event = await event_bus.drain(run_id)
                await ws_manager.broadcast(run_id, event)
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    await ws_manager.ensure_consumer(run_id, _consume)

    try:
        async for raw in websocket.iter_text():
            msg_type = await ws_manager.handle_message(conn, raw)
            if msg_type == "frame_too_large":
                await websocket.close(code=1009, reason="Frame too large")
                break
            elif msg_type == "rate_limited":
                await websocket.close(code=1008, reason="Rate limit exceeded")
                break
            elif msg_type == "replay":
                snapshot = event_bus.get_snapshot(run_id)
                for event in snapshot:
                    await ws_manager.send_to(conn, event)
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(conn)
        await ws_manager.remove_consumer_if_empty(run_id)
