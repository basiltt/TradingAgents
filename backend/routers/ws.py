"""WebSocket endpoint — TASK-014."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

logger = logging.getLogger(__name__)


@router.websocket("/ws/v1/analysis/{run_id}")
async def analysis_ws(websocket: WebSocket, run_id: str):
    app = websocket.app
    ws_manager = app.state.ws_manager
    event_bus = app.state.event_bus
    db = app.state.db

    run = db.get_run(run_id)
    if not run:
        await websocket.accept()
        await websocket.send_json({"type": "error", "seq": 0, "message": "Run not found"})
        await websocket.close(code=4404, reason="Run not found")
        return

    await websocket.accept()
    conn = await ws_manager.connect(websocket, run_id)

    consumer_task = asyncio.create_task(_consume_events(event_bus, run_id, ws_manager))

    try:
        async for raw in websocket.iter_text():
            msg_type = await ws_manager.handle_message(conn, raw)
            if msg_type == "frame_too_large":
                await websocket.close(code=1009, reason="Frame too large")
                break
            elif msg_type == "replay":
                snapshot = event_bus.get_snapshot(run_id)
                for event in snapshot:
                    await ws_manager.send_to(conn, event)
    except WebSocketDisconnect:
        pass
    finally:
        consumer_task.cancel()
        await ws_manager.disconnect(conn)


async def _consume_events(event_bus, run_id: str, ws_manager):
    try:
        while True:
            event = await event_bus.drain(run_id)
            await ws_manager.broadcast(run_id, event)
    except asyncio.CancelledError:
        pass
