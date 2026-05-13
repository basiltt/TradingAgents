"""Async Bybit V5 REST API client for account data retrieval."""

from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import json
import logging
import random
import time
import uuid
from typing import Any

import aiohttp
from yarl import URL

logger = logging.getLogger(__name__)

_RATE_LIMIT_WINDOW = 5
_RATE_LIMIT_MAX = 550  # conservative: Bybit IP limit is 600/5s
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5


class BybitAPIError(Exception):
    def __init__(self, ret_code: int, ret_msg: str):
        self.ret_code = ret_code
        self.ret_msg = ret_msg
        super().__init__(f"Bybit API error {ret_code}: {ret_msg}")


class BybitClient:
    REST_ENDPOINTS = {
        "live": "https://api.bybit.com",
        "demo": "https://api-demo.bybit.com",
    }

    def __init__(self, api_key: str, api_secret: str, account_type: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = self.REST_ENDPOINTS.get(account_type, self.REST_ENDPOINTS["demo"])
        self._semaphore = asyncio.Semaphore(10)
        self._recv_window = "5000"
        self._request_timestamps: collections.deque = collections.deque()
        self._rate_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None
        self._time_offset_ms: int = 0
        self._time_synced: bool = False
        self._sync_lock = asyncio.Lock()
        self._last_sync_at: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _do_sync_time(self) -> None:
        """Internal: actually perform the time sync (no lock)."""
        try:
            session = await self._get_session()
            local_before = int(time.time() * 1000)
            async with session.get(f"{self._base_url}/v5/market/time", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
            local_after = int(time.time() * 1000)
            server_time = int(data.get("result", {}).get("timeNano", "0")) // 1_000_000
            if server_time > 0:
                local_mid = (local_before + local_after) // 2
                self._time_offset_ms = server_time - local_mid
                self._time_synced = True
                self._last_sync_at = time.monotonic()
                logger.info("Bybit time synced: offset=%dms", self._time_offset_ms)
        except Exception as e:
            logger.warning("Failed to sync Bybit server time: %s", e)

    async def _sync_time(self) -> None:
        """Sync local clock with Bybit server to compute timestamp offset."""
        async with self._sync_lock:
            await self._do_sync_time()

    def _sign(self, timestamp: int, params_str: str) -> str:
        sign_str = f"{timestamp}{self._api_key}{self._recv_window}{params_str}"
        return hmac.new(
            self._api_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, timestamp: int, params_str: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-SIGN": self._sign(timestamp, params_str),
            "X-BAPI-RECV-WINDOW": self._recv_window,
            "Content-Type": "application/json",
        }

    _SYNC_INTERVAL = 30  # re-sync offset every 30 seconds

    async def _ensure_time_synced(self) -> None:
        """Ensure time offset is fresh. Re-syncs if stale or never synced."""
        needs_sync = (
            not self._time_synced
            or (time.monotonic() - self._last_sync_at) > self._SYNC_INTERVAL
        )
        if not needs_sync:
            return
        async with self._sync_lock:
            needs_sync = (
                not self._time_synced
                or (time.monotonic() - self._last_sync_at) > self._SYNC_INTERVAL
            )
            if needs_sync:
                await self._do_sync_time()

    async def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None,
        *, retry_on_network_error: bool = True,
    ) -> dict[str, Any]:
        await self._ensure_time_synced()

        for attempt in range(_MAX_RETRIES):
            async with self._semaphore:
                await self._wait_for_rate_limit()
                timestamp = int(time.time() * 1000) + self._time_offset_ms

                if method == "GET" and params:
                    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
                    url = URL(f"{self._base_url}{path}?{query}", encoded=True)
                    headers = self._headers(timestamp, query)
                    request_kwargs: dict[str, Any] = {}
                elif method == "POST" and params:
                    body_str = json.dumps(params, separators=(",", ":"))
                    url = f"{self._base_url}{path}"
                    headers = self._headers(timestamp, body_str)
                    request_kwargs = {"data": body_str}
                else:
                    url = f"{self._base_url}{path}"
                    headers = self._headers(timestamp, "")
                    request_kwargs = {}

                try:
                    session = await self._get_session()
                    async with session.request(method, url, headers=headers, **request_kwargs) as resp:
                        data = await resp.json()
                        resp_headers = dict(resp.headers)
                except aiohttp.ClientError:
                    if not retry_on_network_error:
                        logger.error(f"Bybit network error on {path} (no retry for safety)")
                        raise BybitAPIError(-1, "Network error — order may or may not have been placed, check positions")
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        jitter = random.uniform(0, delay * 0.1)
                        total_delay = delay + jitter
                        logger.warning(f"Bybit network error on {path}, retrying in {total_delay:.2f}s (attempt {attempt + 1})")
                        await asyncio.sleep(total_delay)
                        continue
                    logger.error(f"Bybit network error on {path} after {_MAX_RETRIES} attempts")
                    raise BybitAPIError(-1, "Network error")

                ret_code = data.get("retCode", -1)
                ret_msg = str(data.get("retMsg", "")).lower()

                if ret_code == 10002 and attempt < _MAX_RETRIES - 1:
                    logger.warning(f"Bybit timestamp rejected on {path}, re-syncing clock (attempt {attempt + 1})")
                    await self._sync_time()
                    continue

                is_rate_limited = (
                    ret_code == 10006
                    or "rate limit" in ret_msg
                    or "too many" in ret_msg
                )
                if is_rate_limited and attempt < _MAX_RETRIES - 1:
                    delay = self._parse_reset_delay_from_headers(resp_headers) or (_RETRY_BASE_DELAY * (2 ** attempt))
                    jitter = random.uniform(0, delay * 0.1)
                    total_delay = delay + jitter
                    logger.warning(f"Rate limited on {path}, retrying in {total_delay:.2f}s (attempt {attempt + 1})")
                    await asyncio.sleep(total_delay)
                    continue

                if ret_code != 0:
                    ret_msg_raw = data.get("retMsg", "Unknown error")
                    logger.warning(f"Bybit API error on {path}: {ret_code} - {ret_msg_raw}")
                    raise BybitAPIError(ret_code, ret_msg_raw)

                return data.get("result", {})

        raise BybitAPIError(10006, "Rate limit exceeded after retries")

    @staticmethod
    def _parse_reset_delay_from_headers(headers: dict) -> float | None:
        """Extract delay from X-Bapi-Limit-Reset-Timestamp header."""
        reset_ts = headers.get("X-Bapi-Limit-Reset-Timestamp")
        if not reset_ts:
            return None
        try:
            reset_ms = int(reset_ts)
            now_ms = int(time.time() * 1000)
            delay = max((reset_ms - now_ms) / 1000.0, 0.1)
            return min(delay, 10.0)
        except (ValueError, TypeError):
            return None

    async def _wait_for_rate_limit(self) -> None:
        while True:
            async with self._rate_lock:
                now = time.monotonic()
                while self._request_timestamps and self._request_timestamps[0] < now - _RATE_LIMIT_WINDOW:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < _RATE_LIMIT_MAX:
                    self._request_timestamps.append(time.monotonic())
                    return
                sleep_time = self._request_timestamps[0] - (now - _RATE_LIMIT_WINDOW) + 0.1
                sleep_time = max(0.1, min(sleep_time, _RATE_LIMIT_WINDOW))
            await asyncio.sleep(sleep_time)

    async def test_connection(self) -> dict[str, Any]:
        try:
            await self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
            return {"success": True, "uid": None, "error": None}
        except BybitAPIError as e:
            return {"success": False, "uid": None, "error": e.ret_msg}

    async def get_wallet_balance(self) -> dict[str, Any]:
        result = await self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        account_list = result.get("list", [])
        if not account_list:
            return {
                "totalEquity": "0",
                "totalWalletBalance": "0",
                "totalAvailableBalance": "0",
                "totalPerpUPL": "0",
                "coin": [],
            }
        account = account_list[0]
        return {
            "totalEquity": account.get("totalEquity", "0"),
            "totalWalletBalance": account.get("totalWalletBalance", "0"),
            "totalAvailableBalance": account.get("totalAvailableBalance", "0"),
            "totalPerpUPL": account.get("totalPerpUPL", "0"),
            "accountIMRate": account.get("accountIMRate", "0"),
            "accountMMRate": account.get("accountMMRate", "0"),
            "coin": account.get("coin", []),
        }

    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": "linear", "settleCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
            del params["settleCoin"]

        result = await self._request("GET", "/v5/position/list", params)
        positions = result.get("list", [])
        return [
            {
                "symbol": p.get("symbol", ""),
                "side": p.get("side", ""),
                "size": p.get("size", "0"),
                "avgPrice": p.get("avgPrice", "0"),
                "markPrice": p.get("markPrice", "0"),
                "unrealisedPnl": p.get("unrealisedPnl", "0"),
                "leverage": p.get("leverage", "1"),
                "liqPrice": p.get("liqPrice", "0"),
                "takeProfit": p.get("takeProfit", ""),
                "stopLoss": p.get("stopLoss", ""),
                "positionIM": p.get("positionIM", "0"),
                "positionMM": p.get("positionMM", "0"),
                "positionIdx": int(p.get("positionIdx", 0)),
            }
            for p in positions
            if p.get("size", "0") != "0"
        ]

    async def get_open_orders(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/v5/order/realtime", {"category": "linear", "settleCoin": "USDT"})
        orders = result.get("list", [])
        return [
            {
                "orderId": o.get("orderId", ""),
                "symbol": o.get("symbol", ""),
                "side": o.get("side", ""),
                "orderType": o.get("orderType", ""),
                "qty": o.get("qty", "0"),
                "price": o.get("price", "0"),
                "orderStatus": o.get("orderStatus", ""),
                "createdTime": o.get("createdTime", ""),
                "triggerPrice": o.get("triggerPrice", ""),
                "stopOrderType": o.get("stopOrderType", ""),
            }
            for o in orders
        ]

    async def get_closed_pnl(
        self, start_time: int, end_time: int, limit: int = 100, cursor: str = ""
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "category": "linear",
            "settleCoin": "USDT",
            "startTime": str(start_time),
            "endTime": str(end_time),
            "limit": str(limit),
        }
        if cursor:
            params["cursor"] = cursor

        result = await self._request("GET", "/v5/position/closed-pnl", params)
        return {
            "list": result.get("list", []),
            "nextPageCursor": result.get("nextPageCursor", ""),
        }

    async def place_market_close_order(
        self, symbol: str, side: str, qty: str, position_idx: int = 0
    ) -> dict[str, Any]:
        """Place a market order to close a position.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            side: Position side ("Buy" or "Sell") — will be flipped for the close order.
            qty: Position size to close.
            position_idx: Position index from get_positions (0=One-Way, 1=Buy hedge, 2=Sell hedge).
        """
        close_side = "Sell" if side == "Buy" else "Buy"
        order_link_id = str(uuid.uuid4()).replace("-", "")[:32]
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": close_side,
            "orderType": "Market",
            "qty": qty,
            "reduceOnly": True,
            "positionIdx": position_idx,
            "orderLinkId": order_link_id,
        }

        try:
            result = await self._request(
                "POST", "/v5/order/create", params,
                retry_on_network_error=False,
            )
        except BybitAPIError as e:
            _is_pos_mode_err = (
                e.ret_code in (10001, 110043)
                or "position idx" in e.ret_msg.lower()
            )
            if _is_pos_mode_err and position_idx == 0:
                hedge_idx = 1 if close_side == "Sell" else 2
                logger.warning(
                    "Position mode mismatch for %s, retrying with positionIdx=%d",
                    symbol, hedge_idx,
                )
                params["positionIdx"] = hedge_idx
                result = await self._request(
                    "POST", "/v5/order/create", params,
                    retry_on_network_error=False,
                )
            else:
                raise

        return {
            "orderId": result.get("orderId", ""),
            "orderLinkId": result.get("orderLinkId", order_link_id),
        }

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        """Set leverage for a symbol. Silently succeeds if already at target leverage."""
        try:
            await self._request("POST", "/v5/position/set-leverage", {
                "category": "linear",
                "symbol": symbol,
                "buyLeverage": str(leverage),
                "sellLeverage": str(leverage),
            })
        except BybitAPIError as e:
            if e.ret_code == 110043:
                logger.debug("Leverage already at target for %s: %s", symbol, e.ret_msg)
                return {"status": "unchanged"}
            raise
        return {"status": "ok"}

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        take_profit: str | None = None,
        stop_loss: str | None = None,
    ) -> dict[str, Any]:
        """Place a market order with optional TP/SL.

        Uses orderLinkId for idempotency — if a network error occurs after
        Bybit accepts the order, a retry with the same orderLinkId won't
        create a duplicate.

        Args:
            symbol: Trading pair e.g. "BTCUSDT".
            side: "Buy" or "Sell".
            qty: Order quantity as string.
            take_profit: TP price as string, or None.
            stop_loss: SL price as string, or None.
        """
        order_link_id = str(uuid.uuid4()).replace("-", "")[:32]
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty,
            "positionIdx": 0,
            "orderLinkId": order_link_id,
        }
        if take_profit:
            params["takeProfit"] = take_profit
            params["tpTriggerBy"] = "MarkPrice"
        if stop_loss:
            params["stopLoss"] = stop_loss
            params["slTriggerBy"] = "MarkPrice"

        try:
            result = await self._request(
                "POST", "/v5/order/create", params,
                retry_on_network_error=False,
            )
        except BybitAPIError as e:
            _is_position_mode_err = (
                e.ret_code in (10001, 110043)
                or "position idx" in e.ret_msg.lower()
            )
            if _is_position_mode_err:
                hedge_side_idx = 1 if side == "Buy" else 2
                logger.warning(
                    "Position mode mismatch for %s (code %d), retrying with positionIdx=%d",
                    symbol, e.ret_code, hedge_side_idx,
                )
                params["positionIdx"] = hedge_side_idx
                result = await self._request(
                    "POST", "/v5/order/create", params,
                    retry_on_network_error=False,
                )
            else:
                raise

        return {
            "orderId": result.get("orderId", ""),
            "orderLinkId": result.get("orderLinkId", order_link_id),
        }

    async def get_mark_price(self, symbol: str) -> str:
        """Get the current mark price for a symbol."""
        result = await self._request("GET", "/v5/market/tickers", {
            "category": "linear",
            "symbol": symbol,
        })
        tickers = result.get("list", [])
        if not tickers:
            raise ValueError(f"No ticker data found for {symbol}")
        price = tickers[0].get("markPrice", "0")
        if not price or price == "0":
            raise ValueError(f"Mark price unavailable for {symbol}")
        return price

    async def get_instrument_info(self, symbol: str) -> dict[str, Any]:
        """Get instrument info (min qty, qty step, etc.)."""
        result = await self._request("GET", "/v5/market/instruments-info", {
            "category": "linear",
            "symbol": symbol,
        })
        instruments = result.get("list", [])
        if not instruments:
            raise ValueError(f"No instrument info found for {symbol}")
        return instruments[0]
