"""WebSocket endpoint for real-time trading account updates."""

from __future__ import annotations

import asyncio
import json
import logging

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


@router.websocket("/ws/v1/accounts")
async def accounts_ws(websocket: WebSocket):
    ws_manager = getattr(websocket.app.state, "account_ws_manager", None)
    if not ws_manager:
        await websocket.accept()
        await websocket.close(code=4503, reason="Accounts feature not enabled")
        return

    if not _check_origin(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    await websocket.accept()
    queue = ws_manager.subscribe()
    if queue is None:
        await websocket.close(code=4429, reason="Too many connections")
        return

    async def _send_events():
        try:
            while True:
                msg = await queue.get()
                await websocket.send_text(json.dumps(msg))
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass
        except Exception:
            pass

    send_task = asyncio.create_task(_send_events())
    ping_task = asyncio.create_task(_ping_loop(websocket))

    try:
        async for raw in websocket.iter_text():
            if raw.strip() == "pong":
                continue
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        ping_task.cancel()
        ws_manager.unsubscribe(queue)


async def _ping_loop(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except (asyncio.CancelledError, Exception):
        pass
