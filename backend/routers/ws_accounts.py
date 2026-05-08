"""WebSocket endpoint for real-time trading account updates."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/v1/accounts")
async def accounts_ws(websocket: WebSocket):
    app = websocket.app
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
                    pong = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                except asyncio.TimeoutError:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Accounts WS closed: %s", e)
    finally:
        ws_manager.unsubscribe(queue)
