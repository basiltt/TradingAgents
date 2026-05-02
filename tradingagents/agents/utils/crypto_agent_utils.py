"""LangChain @tool wrappers for Bybit perpetual futures data.

Factory function ``make_crypto_tools`` returns bound tool instances with
shared cache, rate limiter, and circuit breaker.
"""

from __future__ import annotations

import html
import logging
from typing import Annotated

import pandas as pd
from langchain_core.tools import tool

from tradingagents.dataflows.bybit_data import (
    get_bybit_funding_rates,
    get_bybit_indicators,
    get_bybit_klines,
    get_bybit_open_interest,
    get_bybit_ticker,
    BybitRateLimiter,
    BybitCircuitBreaker,
)

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 50 * 1024


def _sanitize(raw: str) -> str:
    escaped = html.escape(raw, quote=False)
    if len(escaped) > _MAX_OUTPUT_BYTES:
        escaped = escaped[:_MAX_OUTPUT_BYTES] + "\n[truncated]"
    return f"<data>{escaped}</data>"


def _dates_to_ms(start_date: str, end_date: str) -> tuple[int, int]:
    start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
    return start_ts, end_ts


def make_crypto_tools(
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> list:
    @tool
    def get_crypto_klines(
        symbol: Annotated[str, "Bybit perpetual symbol, e.g. BTCUSDT"],
        interval: Annotated[str, "Kline interval: 15, 60, 240, or D"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Retrieve OHLCV kline data for a crypto perpetual futures contract."""
        start_ms, end_ms = _dates_to_ms(start_date, end_date)
        raw = get_bybit_klines(
            symbol, interval, start_ms, end_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        return _sanitize(raw)

    @tool
    def get_crypto_indicators(
        symbol: Annotated[str, "Bybit perpetual symbol"],
        interval: Annotated[str, "Kline interval"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Compute technical indicators (RSI, MACD, Bollinger, EMA) for a crypto perpetual."""
        start_ms, end_ms = _dates_to_ms(start_date, end_date)
        raw = get_bybit_indicators(
            symbol, interval, start_ms, end_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        return _sanitize(raw)

    @tool
    def get_funding_rates(
        symbol: Annotated[str, "Bybit perpetual symbol"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Retrieve funding rate history. Non-critical: returns unavailable message on failure."""
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            raw = get_bybit_funding_rates(
                symbol, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except Exception as exc:
            logger.warning("Funding rates unavailable for %s: %s", symbol, exc)
            return _sanitize(f"Data unavailable: {exc}")

    @tool
    def get_open_interest(
        symbol: Annotated[str, "Bybit perpetual symbol"],
        interval: Annotated[str, "OI interval: 5min, 15min, 30min, 1h, 4h, 1d"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Retrieve open interest history. Non-critical: returns unavailable message on failure."""
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            raw = get_bybit_open_interest(
                symbol, interval, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except Exception as exc:
            logger.warning("Open interest unavailable for %s: %s", symbol, exc)
            return _sanitize(f"Data unavailable: {exc}")

    @tool
    def get_crypto_ticker(
        symbol: Annotated[str, "Bybit perpetual symbol"],
    ) -> str:
        """Retrieve current ticker snapshot. Non-critical: returns unavailable message on failure."""
        try:
            raw = get_bybit_ticker(
                symbol,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except Exception as exc:
            logger.warning("Ticker unavailable for %s: %s", symbol, exc)
            return _sanitize(f"Data unavailable: {exc}")

    return [get_crypto_klines, get_crypto_indicators, get_funding_rates, get_open_interest, get_crypto_ticker]
