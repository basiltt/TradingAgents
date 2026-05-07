"""Async Bybit V5 REST API client for account data retrieval."""

from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import logging
import time
from typing import Any

import aiohttp

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
        for attempt in range(_MAX_RETRIES):
            async with self._semaphore:
                await self._wait_for_rate_limit()
                timestamp = int(time.time() * 1000)

                if method == "GET" and params:
                    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
                    url = f"{self._base_url}{path}?{query}"
                    headers = self._headers(timestamp, query)
                else:
                    url = f"{self._base_url}{path}"
                    query = ""
                    headers = self._headers(timestamp, query)

                try:
                    session = await self._get_session()
                    async with session.request(method, url, headers=headers) as resp:
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
        result = await self._request("GET", "/v5/order/realtime", {"category": "linear"})
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
