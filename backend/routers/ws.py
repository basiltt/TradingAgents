"""WebSocket endpoint — TASK-014."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

logger = logging.getLogger(__name__)


def _check_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    allowed_raw = os.environ.get("WEB_CORS_ORIGIN", "http://localhost:5173")
    allowed = {o.strip() for o in allowed_raw.split(",") if o.strip()}
    return origin in allowed


@router.websocket("/ws/v1/analysis/{run_id}")
async def analysis_ws(websocket: WebSocket, run_id: str):
    app = websocket.app
    ws_manager = app.state.ws_manager
    event_bus = app.state.event_bus
    db = app.state.db

    if not _check_origin(websocket):
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    run = db.get_run(run_id)
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
