"""AI Manager Market Data Cache — provides indicator snapshots for open positions.

Fetches public market data (tickers, funding rates) from Bybit REST API
and computes lightweight indicators for the AI decision graph.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

import httpx

logger = logging.getLogger(__name__)

_BYBIT_BASE = "https://api.bybit.com"
_TICKER_ENDPOINT = "/v5/market/tickers"
_KLINE_ENDPOINT = "/v5/market/kline"
_REFRESH_INTERVAL = 15.0


class MarketDataCache:
    """Periodically fetches public market data for tracked symbols."""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._prev_data: Dict[str, Dict[str, Any]] = {}
        self._symbols: Set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._last_refresh: float = 0.0

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("MarketDataCache started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        logger.info("MarketDataCache stopped")

    def track_symbols(self, symbols: Set[str]) -> None:
        self._symbols |= symbols

    def untrack_symbols(self, symbols: Set[str]) -> None:
        self._symbols -= symbols
        for s in symbols:
            self._data.pop(s, None)
            self._prev_data.pop(s, None)

    def get_indicators(self, symbol: str) -> Dict[str, Any]:
        return self._data.get(symbol, {})

    def get_all_indicators(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._data)

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self._refresh()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Market data refresh failed", exc_info=True)
            await asyncio.sleep(_REFRESH_INTERVAL)

    async def _refresh(self) -> None:
        if not self._symbols or not self._client:
            return

        try:
            resp = await self._client.get(
                f"{_BYBIT_BASE}{_TICKER_ENDPOINT}",
                params={"category": "linear"},
            )
            resp.raise_for_status()
            tickers = resp.json().get("result", {}).get("list", [])
        except Exception:
            return

        ticker_map = {t["symbol"]: t for t in tickers if t.get("symbol") in self._symbols}

        self._prev_data = dict(self._data)
        now = time.time()

        for symbol in self._symbols:
            ticker = ticker_map.get(symbol)
            if not ticker:
                continue

            prev = self._prev_data.get(symbol, {})
            indicators: Dict[str, Any] = {}

            mark_price = _safe_float(ticker.get("markPrice"))
            indicators["mark_price"] = mark_price

            funding_rate = _safe_float(ticker.get("fundingRate"))
            indicators["funding_rate"] = funding_rate
            indicators["prev_funding_rate"] = prev.get("funding_rate")

            price_24h_pct = _safe_float(ticker.get("price24hPcnt"))
            indicators["price_24h_pct"] = price_24h_pct

            high_24h = _safe_float(ticker.get("highPrice24h"))
            low_24h = _safe_float(ticker.get("lowPrice24h"))
            if high_24h and low_24h and low_24h > 0:
                indicators["atr_14"] = (high_24h - low_24h) / 14.0  # Rough proxy; real ATR needs kline history

            turnover_24h = _safe_float(ticker.get("turnover24h"))
            indicators["volume_24h"] = turnover_24h

            last_price = _safe_float(ticker.get("lastPrice"))
            prev_price = prev.get("mark_price")
            if last_price and prev_price and prev_price > 0:
                elapsed = now - self._last_refresh if self._last_refresh else _REFRESH_INTERVAL
                if elapsed > 0:
                    indicators["pnl_velocity_30s"] = ((last_price - prev_price) / prev_price) * (30.0 / elapsed)

            self._data[symbol] = indicators

        self._last_refresh = now


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
