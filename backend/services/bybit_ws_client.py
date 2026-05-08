"""Async Bybit V5 Private WebSocket client for real-time account updates."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

WS_ENDPOINTS = {
    "live": "wss://stream.bybit.com/v5/private",
    "demo": "wss://stream-demo.bybit.com/v5/private",
}

RECONNECT_BASE = 2.0
RECONNECT_MAX = 30.0
PING_INTERVAL = 20.0


class BybitWSClient:
    """Maintains a single private WebSocket connection to Bybit for one account."""

    def __init__(
        self,
        account_id: str,
        api_key: str,
        api_secret: str,
        account_type: str,
        on_event: Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, None]],
    ):
        self._account_id = account_id
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = WS_ENDPOINTS.get(account_type, WS_ENDPOINTS["demo"])
        self._on_event = on_event
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._reconnect_delay = RECONNECT_BASE

    @property
    def account_id(self) -> str:
        return self._account_id

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._close_ws()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _close_ws(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"[WS:{self._account_id[:8]}] Connection error: {e}. "
                    f"Reconnecting in {self._reconnect_delay:.1f}s"
                )
            if not self._running:
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX)

    async def _connect_and_listen(self) -> None:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        self._ws = await asyncio.wait_for(
            self._session.ws_connect(self._url, heartbeat=None),
            timeout=15,
        )
        logger.info(f"[WS:{self._account_id[:8]}] Connected to Bybit private WS")

        await self._authenticate()
        await self._subscribe()
        self._reconnect_delay = RECONNECT_BASE

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
            await self._close_ws()

    def _generate_auth_signature(self) -> tuple[int, str]:
        expires = int(time.time() * 1000) + 5000
        sign_str = f"GET/realtime{expires}"
        signature = hmac.new(
            self._api_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        return expires, signature

    async def _authenticate(self) -> None:
        expires, signature = self._generate_auth_signature()
        auth_msg = {
            "op": "auth",
            "args": [self._api_key, expires, signature],
        }
        await self._ws.send_str(json.dumps(auth_msg))
        resp = await self._ws.receive(timeout=10)
        if resp.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSING):
            raise RuntimeError(f"WS closed during auth: {resp.type}")
        if resp.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(resp.data)
            if not data.get("success"):
                raise RuntimeError(f"Auth failed: {data.get('ret_msg', 'unknown')}")
            logger.debug(f"[WS:{self._account_id[:8]}] Authenticated")
        else:
            raise RuntimeError(f"Unexpected auth response type: {resp.type}")

    async def _subscribe(self) -> None:
        sub_msg = {
            "op": "subscribe",
            "args": ["wallet", "position", "execution", "order"],
        }
        await self._ws.send_str(json.dumps(sub_msg))

    async def _ping_loop(self) -> None:
        try:
            while self._running and self._ws and not self._ws.closed:
                await asyncio.sleep(PING_INTERVAL)
                if self._ws and not self._ws.closed:
                    await self._ws.send_str(json.dumps({"op": "ping"}))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[WS:{self._account_id[:8]}] Ping failed: {e}")
            if self._ws and not self._ws.closed:
                await self._ws.close()

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Ignore pong responses and subscription confirmations
        op = data.get("op")
        if op in ("pong", "subscribe", "auth"):
            return

        topic = data.get("topic", "")
        event_data = data.get("data")
        if not event_data:
            return

        if topic == "wallet":
            await self._handle_wallet(event_data)
        elif topic == "position":
            await self._handle_position(event_data)
        elif topic == "execution":
            await self._handle_execution(event_data)
        elif topic == "order":
            await self._handle_order(event_data)

    async def _handle_wallet(self, data: list[dict]) -> None:
        for wallet in data:
            total_equity = wallet.get("totalEquity", "")
            total_perp_upl = wallet.get("totalPerpUPL", "")
            if total_equity or total_perp_upl:
                event: dict[str, Any] = {}
                if total_equity:
                    event["totalEquity"] = total_equity
                if total_perp_upl:
                    event["totalPerpUPL"] = total_perp_upl
                await self._on_event(self._account_id, "wallet_update", event)

    async def _handle_position(self, data: list[dict]) -> None:
        for pos in data:
            await self._on_event(self._account_id, "position_update", {
                "symbol": pos.get("symbol", ""),
                "side": pos.get("side", ""),
                "size": pos.get("size", "0"),
                "unrealisedPnl": pos.get("unrealisedPnl", "0"),
                "positionValue": pos.get("positionValue", "0"),
            })

    async def _handle_execution(self, data: list[dict]) -> None:
        for exe in data:
            await self._on_event(self._account_id, "execution", {
                "symbol": exe.get("symbol", ""),
                "side": exe.get("side", ""),
                "qty": exe.get("execQty", "0"),
                "price": exe.get("execPrice", "0"),
                "execType": exe.get("execType", ""),
            })

    async def _handle_order(self, data: list[dict]) -> None:
        for order in data:
            await self._on_event(self._account_id, "order_update", {
                "symbol": order.get("symbol", ""),
                "side": order.get("side", ""),
                "orderStatus": order.get("orderStatus", ""),
                "qty": order.get("qty", "0"),
                "price": order.get("price", "0"),
            })
