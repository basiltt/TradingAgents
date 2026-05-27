"""AI Manager Market Data Cache — provides indicator snapshots for open positions.

Fetches public market data (tickers, klines) from Bybit REST API
and computes technical indicators for the AI decision graph.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set

import httpx

logger = logging.getLogger(__name__)

_BYBIT_BASE = "https://api.bybit.com"
_TICKER_ENDPOINT = "/v5/market/tickers"
_KLINE_ENDPOINT = "/v5/market/kline"
_OI_ENDPOINT = "/v5/market/open-interest"
_REFRESH_INTERVAL = 15.0
_KLINE_REFRESH_INTERVAL = 60.0  # Klines refresh every 60s (1m candles)
_KLINE_LIMIT = 50  # Fetch last 50 candles for indicator computation


class MarketDataCache:
    """Periodically fetches public market data for tracked symbols."""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._prev_data: Dict[str, Dict[str, Any]] = {}
        self._kline_data: Dict[str, List[List[float]]] = {}  # symbol -> [[ts, o, h, l, c, vol], ...]
        self._symbols: Set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._kline_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._last_refresh: float = 0.0
        self._last_kline_refresh: float = 0.0

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._refresh_loop())
        self._kline_task = asyncio.create_task(self._kline_refresh_loop())
        logger.info("MarketDataCache started")

    async def stop(self) -> None:
        for t in [self._task, self._kline_task]:
            if t:
                t.cancel()
                try:
                    await t
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
            self._kline_data.pop(s, None)

    def get_indicators(self, symbol: str) -> Dict[str, Any]:
        return self._data.get(symbol, {})

    def get_all_indicators(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._data)

    # --- Ticker refresh loop ---

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self._refresh_tickers()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Market data ticker refresh failed", exc_info=True)
            await asyncio.sleep(_REFRESH_INTERVAL)

    async def _refresh_tickers(self) -> None:
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
            indicators["high_24h"] = high_24h
            indicators["low_24h"] = low_24h

            turnover_24h = _safe_float(ticker.get("turnover24h"))
            indicators["volume_24h"] = turnover_24h

            open_interest = _safe_float(ticker.get("openInterest"))
            indicators["open_interest"] = open_interest

            last_price = _safe_float(ticker.get("lastPrice"))
            prev_price = prev.get("mark_price")
            if last_price and prev_price and prev_price > 0:
                elapsed = now - self._last_refresh if self._last_refresh else _REFRESH_INTERVAL
                if elapsed > 0:
                    indicators["pnl_velocity_30s"] = ((last_price - prev_price) / prev_price) * (30.0 / elapsed)

            # Carry forward prev_rsi_14 for threshold-crossover detection
            indicators["prev_rsi_14"] = prev.get("rsi_14")

            # Merge kline-derived indicators
            kline_indicators = self._compute_kline_indicators(symbol)
            indicators.update(kline_indicators)

            # Compute candle body from most recent kline for volatility spike detection
            kline_candles = self._kline_data.get(symbol)
            if kline_candles and len(kline_candles) >= 1:
                last_candle = kline_candles[-1]
                indicators["candle_1m_body"] = last_candle[4] - last_candle[1]  # close - open

            self._data[symbol] = indicators

        self._last_refresh = now

    # --- Kline refresh loop ---

    async def _kline_refresh_loop(self) -> None:
        while True:
            try:
                await self._refresh_klines()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Market data kline refresh failed", exc_info=True)
            await asyncio.sleep(_KLINE_REFRESH_INTERVAL)

    async def _refresh_klines(self) -> None:
        if not self._symbols or not self._client:
            return

        for symbol in list(self._symbols):
            try:
                resp = await self._client.get(
                    f"{_BYBIT_BASE}{_KLINE_ENDPOINT}",
                    params={
                        "category": "linear",
                        "symbol": symbol,
                        "interval": "5",  # 5-minute candles
                        "limit": _KLINE_LIMIT,
                    },
                )
                resp.raise_for_status()
                raw_list = resp.json().get("result", {}).get("list", [])
                # Bybit returns [[ts, open, high, low, close, volume, turnover], ...] newest first
                candles = []
                for c in reversed(raw_list):
                    try:
                        candles.append([
                            float(c[0]),  # timestamp
                            float(c[1]),  # open
                            float(c[2]),  # high
                            float(c[3]),  # low
                            float(c[4]),  # close
                            float(c[5]),  # volume
                        ])
                    except (IndexError, ValueError, TypeError):
                        continue
                if candles:
                    self._kline_data[symbol] = candles
            except Exception:
                continue
            # Rate limit: stagger between symbols
            await asyncio.sleep(0.2)

        self._last_kline_refresh = time.time()

    def _compute_kline_indicators(self, symbol: str) -> Dict[str, Any]:
        """Compute EMA, RSI, ATR from kline data."""
        candles = self._kline_data.get(symbol)
        if not candles or len(candles) < 21:
            return {}

        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]

        indicators: Dict[str, Any] = {}

        # EMA-9 and EMA-21
        ema_9 = _compute_ema(closes, 9)
        ema_21 = _compute_ema(closes, 21)
        if ema_9 is not None:
            indicators["ema_9"] = ema_9
        if ema_21 is not None:
            indicators["ema_21"] = ema_21

        # Trend strength: (EMA9 - EMA21) / EMA21
        if ema_9 is not None and ema_21 is not None and ema_21 > 0:
            indicators["ema_trend_strength"] = (ema_9 - ema_21) / ema_21

        # RSI-14
        rsi = _compute_rsi(closes, 14)
        if rsi is not None:
            indicators["rsi_14"] = rsi

        # ATR-14
        atr = _compute_atr(highs, lows, closes, 14)
        if atr is not None:
            indicators["atr_14"] = atr

        # Conflicting signal detection: EMA trend vs RSI divergence
        if ema_9 is not None and ema_21 is not None and rsi is not None:
            ema_bullish = ema_9 > ema_21
            rsi_overbought = rsi >= 70
            rsi_oversold = rsi <= 30
            if (ema_bullish and rsi_overbought) or (not ema_bullish and rsi_oversold):
                indicators["conflicting"] = True

        return indicators


# --- Indicator computation helpers ---


def _compute_ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _compute_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(abs(diff) if diff < 0 else 0.0)

    if len(gains) < period:
        return None

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    if len(highs) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period
    return atr


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
