"""Bybit private WebSocket client for real-time account updates."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

_WS_ENDPOINTS = {
    "live": "wss://stream.bybit.com/v5/private",
    "demo": "wss://stream-demo.bybit.com/v5/private",
}

_RECONNECT_BASE = 2.0
_RECONNECT_MAX = 30.0
_PING_INTERVAL = 20.0
_PONG_TIMEOUT = 45.0  # force reconnect if no message received within this window
_RECV_WINDOW = "5000"


class BybitWSClient:
    """Connects to Bybit private WebSocket and streams wallet/position/order updates."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_type: str,
        on_event: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        account_id: str = "",
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = _WS_ENDPOINTS.get(account_type, _WS_ENDPOINTS["demo"])
        self._on_event = on_event
        self._account_id = account_id
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._running = False
        self._reconnect_delay = _RECONNECT_BASE
        self._last_msg_at: float = 0.0

    def _auth_payload(self) -> dict[str, Any]:
        expires = int((time.time() + 10) * 1000)
        sign_str = f"GET/realtime{expires}"
        signature = hmac.new(
            self._api_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {"op": "auth", "args": [self._api_key, expires, signature]}

    def _subscribe_payload(self) -> dict[str, Any]:
        return {
            "op": "subscribe",
            "args": ["wallet", "position", "execution", "order"],
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Bybit WS error: %s, reconnecting in %.1fs", e, self._reconnect_delay, extra={"account_id": self._account_id})

            if not self._running:
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, _RECONNECT_MAX) * (0.75 + random.random() * 0.5)

    async def _connect_and_listen(self) -> None:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        if self._ws and not self._ws.closed:
            await self._ws.close()

        self._ws = await asyncio.wait_for(
            self._session.ws_connect(self._url, heartbeat=None, timeout=aiohttp.ClientWSTimeout(ws_close=15)),
            timeout=20,
        )
        logger.info("Bybit WS connected to %s", self._url, extra={"account_id": self._account_id})

        assert self._ws is not None
        await self._ws.send_json(self._auth_payload())
        auth_resp = await self._ws.receive_json(timeout=10)
        if not auth_resp.get("success"):
            logger.error("Bybit WS auth failed: %s", auth_resp.get("ret_msg"))
            await self._ws.close()
            return

        await self._ws.send_json(self._subscribe_payload())
        self._reconnect_delay = _RECONNECT_BASE
        self._last_msg_at = time.monotonic()
        logger.info("Bybit WS authenticated and subscribed", extra={"account_id": self._account_id})

        self._ping_task = asyncio.create_task(self._ping_loop())

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        finally:
            if self._ping_task and not self._ping_task.done():
                self._ping_task.cancel()

    async def _ping_loop(self) -> None:
        try:
            while self._running and self._ws and not self._ws.closed:
                await asyncio.sleep(_PING_INTERVAL)
                if self._ws and not self._ws.closed:
                    if self._last_msg_at and (time.monotonic() - self._last_msg_at) > _PONG_TIMEOUT:
                        logger.warning("Bybit WS stale (no message in %.0fs), forcing reconnect", _PONG_TIMEOUT)
                        await self._ws.close()
                        break
                    await self._ws.send_json({"op": "ping"})
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("ping_loop_error", exc_info=True)

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        self._last_msg_at = time.monotonic()

        if data.get("op") == "pong" or data.get("ret_msg") == "pong":
            return

        topic = data.get("topic", "")
        if not topic:
            return

        event_data = data.get("data", [])
        if not event_data:
            return

        if topic == "wallet":
            await self._emit_wallet(event_data)
        elif topic == "position":
            await self._emit_positions(event_data)
        elif topic == "execution":
            await self._emit_executions(event_data)
        elif topic == "order":
            await self._emit_orders(event_data)

    async def _safe_emit(self, event: dict[str, Any]) -> None:
        """Call the event callback, catching exceptions to protect the WS loop."""
        try:
            await self._on_event(event)
        except Exception:
            logger.exception("on_event callback failed for event type=%s", event.get("type"))

    async def _emit_wallet(self, data: list[dict]) -> None:
        for account in data:
            coins = account.get("coin", [])
            total_equity = account.get("totalEquity", "0")
            total_wallet_balance = account.get("totalWalletBalance", "0")
            total_perp_upl = account.get("totalPerpUPL", "0")
            await self._safe_emit({
                "type": "wallet_update",
                "data": {
                    "totalEquity": total_equity,
                    "totalPerpUPL": total_perp_upl,
                    "totalWalletBalance": total_wallet_balance,
                    "coins": coins,
                },
            })

    async def _emit_positions(self, data: list[dict]) -> None:
        for pos in data:
            await self._safe_emit({
                "type": "position_update",
                "data": {
                    "symbol": pos.get("symbol", ""),
                    "side": pos.get("side", ""),
                    "size": pos.get("size", "0"),
                    "unrealisedPnl": pos.get("unrealisedPnl", "0"),
                    "cumRealisedPnl": pos.get("cumRealisedPnl", "0"),
                    "markPrice": pos.get("markPrice", "0"),
                    "avgPrice": pos.get("entryPrice", "0"),
                    "leverage": pos.get("leverage", "0"),
                    "liqPrice": pos.get("liqPrice", "0"),
                    "createdTime": pos.get("createdTime", ""),
                    "updatedTime": pos.get("updatedTime", ""),
                    "trailingStop": pos.get("trailingStop", "0"),
                    "takeProfit": pos.get("takeProfit", ""),
                    "stopLoss": pos.get("stopLoss", ""),
                    "positionValue": pos.get("positionValue", "0"),
                },
            })

    async def _emit_executions(self, data: list[dict]) -> None:
        for ex in data:
            await self._safe_emit({
                "type": "execution",
                "data": {
                    "symbol": ex.get("symbol", ""),
                    "side": ex.get("side", ""),
                    "qty": ex.get("execQty", "0"),
                    "price": ex.get("execPrice", "0"),
                    "execType": ex.get("execType", ""),
                },
            })

    async def _emit_orders(self, data: list[dict]) -> None:
        for order in data:
            await self._safe_emit({
                "type": "order_update",
                "data": {
                    "orderId": order.get("orderId", ""),
                    "symbol": order.get("symbol", ""),
                    "side": order.get("side", ""),
                    "orderStatus": order.get("orderStatus", ""),
                    "qty": order.get("qty", "0"),
                    "price": order.get("price", "0"),
                },
            })
