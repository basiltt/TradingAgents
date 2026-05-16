"""WebSocket endpoint for real-time trading account updates."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


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
    app = websocket.app

    if not _check_origin(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    ws_manager = getattr(app.state, "account_ws_manager", None)
    if ws_manager is None:
        await websocket.close(code=1011, reason="Accounts WS not available")
        return

    await websocket.accept()

    queue = ws_manager.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                except asyncio.TimeoutError:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Accounts WS closed: %s", e)
    finally:
        ws_manager.unsubscribe(queue)
