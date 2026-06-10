"""WebSocket endpoint for real-time backtest progress (step-by-step stages).

Streams the per-stage events a running backtest emits (load signals → warm cache →
load klines → simulate → metrics → complete) for ONE run_id, so the UI can show
exactly what's happening instead of a bare spinner.

Mirrors ws_accounts.py: loopback-origin check, subscribe to the run's queue (which
replays the run's history first, so a late connector catches up), and a ping/pong
keepalive. Closes when the run reaches a terminal stage.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True  # Allow non-browser clients (monitoring, health checks)
    allowed = getattr(websocket.app.state, "cors_origins", None)
    if not allowed:
        return False
    return origin in set(allowed)


@router.websocket("/ws/v1/backtest/{run_id}")
async def backtest_progress_ws(websocket: WebSocket, run_id: str):
    app = websocket.app

    if not _check_origin(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    manager = getattr(app.state, "backtest_progress_manager", None)
    if manager is None:
        await websocket.close(code=1011, reason="Backtest progress not available")
        return

    await websocket.accept()

    queue = manager.subscribe(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
                # The run finished — flush the terminal event then close cleanly so
                # the client's reconnect logic doesn't keep re-opening a done run.
                if event.get("stage") in ("complete", "failed") and event.get("status") in ("done", "failed"):
                    break
            except asyncio.TimeoutError:
                # Keepalive: ping the client; if it's gone, the receive times out and
                # we break (same shape as ws_accounts).
                await websocket.send_json({"type": "ping"})
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                except asyncio.TimeoutError:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.debug("Backtest progress WS closed: %s", e)
    finally:
        manager.unsubscribe(run_id, queue)
