"""Async Bybit V5 REST API client for account data retrieval."""

from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import aiohttp
from yarl import URL

logger = logging.getLogger(__name__)

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 110  # conservative: Bybit limit is 120, leave headroom
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

    async def _sync_time(self) -> None:
        """Sync local clock with Bybit server to compute timestamp offset."""
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
                logger.info("Bybit time synced: offset=%dms", self._time_offset_ms)
        except Exception as e:
            logger.warning("Failed to sync Bybit server time: %s", e)

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

    async def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._time_synced:
            await self._sync_time()

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
                except aiohttp.ClientError as e:
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(f"Bybit network error on {path}, retrying in {delay}s (attempt {attempt + 1})")
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"Bybit network error on {path} after {_MAX_RETRIES} attempts")
                    raise BybitAPIError(-1, "Network error")

                ret_code = data.get("retCode", -1)
                if ret_code == 10002 and attempt < _MAX_RETRIES - 1:
                    logger.warning(f"Bybit timestamp rejected on {path}, re-syncing clock (attempt {attempt + 1})")
                    await self._sync_time()
                    continue

                if ret_code == 10006 and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Rate limited on {path}, retrying in {delay}s (attempt {attempt + 1})")
                    await asyncio.sleep(delay)
                    continue

                if ret_code != 0:
                    ret_msg = data.get("retMsg", "Unknown error")
                    logger.warning(f"Bybit API error on {path}: {ret_code}")
                    raise BybitAPIError(ret_code, ret_msg)

                return data.get("result", {})

        raise BybitAPIError(10006, "Rate limit exceeded after retries")

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
            result = await self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
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
        self, symbol: str, side: str, qty: str
    ) -> dict[str, Any]:
        close_side = "Sell" if side == "Buy" else "Buy"
        params = {
            "category": "linear",
            "symbol": symbol,
            "side": close_side,
            "orderType": "Market",
            "qty": qty,
            "reduceOnly": True,
        }
        result = await self._request("POST", "/v5/order/create", params)
        return {
            "orderId": result.get("orderId", ""),
            "orderLinkId": result.get("orderLinkId", ""),
        }
