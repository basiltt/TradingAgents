"""Async Bybit V5 REST API client for account data retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


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
        async with self._semaphore:
            timestamp = int(time.time() * 1000)

            if method == "GET" and params:
                query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
                url = f"{self._base_url}{path}?{query}"
                headers = self._headers(timestamp, query)
            else:
                url = f"{self._base_url}{path}"
                query = ""
                headers = self._headers(timestamp, query)

            timeout = aiohttp.ClientTimeout(total=10)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.request(method, url, headers=headers) as resp:
                        data = await resp.json()
            except aiohttp.ClientError as e:
                logger.error(f"Bybit network error on {path}: {e}")
                raise BybitAPIError(-1, f"Network error: {e}")

            ret_code = data.get("retCode", -1)
            if ret_code != 0:
                ret_msg = data.get("retMsg", "Unknown error")
                logger.warning(f"Bybit API error on {path}: {ret_code} {ret_msg}")
                raise BybitAPIError(ret_code, ret_msg)

            return data.get("result", {})

    async def test_connection(self) -> dict[str, Any]:
        try:
            result = await self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
            account_list = result.get("list", [])
            uid = account_list[0].get("accountIMRate", "") if account_list else ""
            return {"success": True, "uid": uid, "error": None}
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
