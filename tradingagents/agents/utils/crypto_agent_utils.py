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
    get_bybit_orderbook,
    get_bybit_recent_trades,
    get_bybit_ticker,
    get_volatility_metrics,
    compute_correlation,
    InvalidSymbolError,
    BybitRateLimiter,
    BybitCircuitBreaker,
)

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 50 * 1024


def _sanitize(raw: str) -> str:
    if len(raw) > _MAX_OUTPUT_CHARS:
        raw = raw[:_MAX_OUTPUT_CHARS] + "\n[truncated]"
    escaped = html.escape(raw, quote=False)
    return f"<data>{escaped}</data>"


def _dates_to_ms(start_date: str, end_date: str) -> tuple[int, int]:
    start_ts = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date, tz="UTC").timestamp() * 1000)
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
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            raw = get_bybit_klines(
                symbol, interval, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.exception("get_crypto_klines failed for %s", symbol)
            return f"Error fetching kline data for {symbol}: {exc}"

    @tool
    def get_crypto_indicators(
        symbol: Annotated[str, "Bybit perpetual symbol"],
        interval: Annotated[str, "Kline interval"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Compute technical indicators (RSI, MACD, Bollinger, EMA) for a crypto perpetual."""
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            raw = get_bybit_indicators(
                symbol, interval, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.exception("get_crypto_indicators failed for %s", symbol)
            return f"Error computing indicators for {symbol}: {exc}"

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
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Funding rates unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: funding rate data could not be retrieved")

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
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Open interest unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: open interest data could not be retrieved")

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
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Ticker unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: ticker data could not be retrieved")

    @tool
    def get_order_book_depth(
        symbol: Annotated[str, "Bybit perpetual symbol, e.g. BTCUSDT"],
    ) -> str:
        """Retrieve order book depth: spread, bid/ask imbalance, wall levels, and liquidity assessment."""
        try:
            import json
            data = get_bybit_orderbook(
                symbol, depth=50,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            lines = [f"Order Book Depth for {symbol}:"]
            lines.append(f"  Spread: {data['spread_bps']:.2f} bps")
            lines.append(f"  Bid Depth: {data['bid_depth']:.2f} | Ask Depth: {data['ask_depth']:.2f}")
            lines.append(f"  Imbalance Ratio: {data['imbalance_ratio']:+.4f} (positive = more bids)")
            if data.get("wall_levels"):
                lines.append("  Significant walls:")
                for w in data["wall_levels"]:
                    lines.append(f"    {w['side'].upper()} wall at {w['price']} (size: {w['size']:.2f})")
            return _sanitize("\n".join(lines))
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Order book unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: order book data could not be retrieved")

    @tool
    def get_recent_trades_cvd(
        symbol: Annotated[str, "Bybit perpetual symbol, e.g. BTCUSDT"],
    ) -> str:
        """Retrieve recent trades analysis: CVD (buy vs sell pressure), whale trades (>95th percentile size), net flow."""
        try:
            data = get_bybit_recent_trades(
                symbol, limit=500,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            lines = [f"Recent Trades & CVD for {symbol}:"]
            lines.append(f"  Trade Count: {data['trade_count']}")
            lines.append(f"  Buy Volume: {data['buy_volume']:.4f} | Sell Volume: {data['sell_volume']:.4f}")
            lines.append(f"  CVD (net buying pressure): {data['cvd']:+.4f}")
            lines.append(f"  Net Whale Flow: {data['net_whale_flow']:+.4f} (threshold: {data.get('whale_threshold_size', 0):.2f})")
            if data.get("whale_trades"):
                lines.append("  Recent whale trades:")
                for wt in data["whale_trades"][:5]:
                    lines.append(f"    {wt['side']} {wt['size']:.4f} @ {wt['price']}")
            return _sanitize("\n".join(lines))
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Recent trades unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: recent trades data could not be retrieved")

    @tool
    def get_btc_eth_correlation(
        symbol: Annotated[str, "Bybit perpetual symbol (NOT BTC or ETH themselves)"],
        interval: Annotated[str, "Kline interval: 15, 60, 240, or D"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Compute correlation and beta of symbol returns vs BTC and ETH. Use to assess cross-asset risk."""
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            data = compute_correlation(
                symbol, interval, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            lines = [f"Cross-Asset Correlation for {symbol}:"]
            btc_corr = data.get("btc_corr")
            eth_corr = data.get("eth_corr")
            btc_beta = data.get("btc_beta")
            eth_beta = data.get("eth_beta")
            lines.append(f"  BTC Correlation: {btc_corr if btc_corr is not None else 'N/A'}")
            lines.append(f"  BTC Beta: {btc_beta if btc_beta is not None else 'N/A'}")
            lines.append(f"  ETH Correlation: {eth_corr if eth_corr is not None else 'N/A'}")
            lines.append(f"  ETH Beta: {eth_beta if eth_beta is not None else 'N/A'}")
            if btc_beta and btc_beta > 1.5:
                lines.append("  ⚠ HIGH BETA: This coin amplifies BTC moves significantly")
            return _sanitize("\n".join(lines))
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Correlation unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: correlation data could not be retrieved")

    @tool
    def get_volatility_regime(
        symbol: Annotated[str, "Bybit perpetual symbol"],
        interval: Annotated[str, "Kline interval: 15, 60, 240, or D"],
        start_date: Annotated[str, "Start date yyyy-mm-dd"],
        end_date: Annotated[str, "End date yyyy-mm-dd"],
    ) -> str:
        """Assess current volatility regime (Low/Normal/High) with ATR, realized vol, and position sizing guidance."""
        try:
            start_ms, end_ms = _dates_to_ms(start_date, end_date)
            raw = get_bybit_klines(
                symbol, interval, start_ms, end_ms,
                cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                api_key=api_key, api_secret=api_secret,
            )
            data = get_volatility_metrics(raw)
            lines = [f"Volatility Regime for {symbol}:"]
            lines.append(f"  ATR(14): {data.get('atr_14', 'N/A')}")
            lines.append(f"  Realized Vol 24h: {data.get('rv_24h', 'N/A')}")
            lines.append(f"  Realized Vol 7d: {data.get('rv_7d', 'N/A')}")
            lines.append(f"  Bollinger Width: {data.get('bb_width', 'N/A')}")
            regime = data.get("volatility_regime", "Normal")
            lines.append(f"  Regime: {regime}")
            size_mult = {"Low": "1.2x (can size up)", "Normal": "1.0x (standard)", "High": "0.6x (reduce size)"}.get(regime, "1.0x")
            lines.append(f"  Position Size Multiplier: {size_mult}")
            if regime == "High":
                lines.append("  ⚠ HIGH VOLATILITY: Wider stops needed, smaller position size recommended")
            return _sanitize("\n".join(lines))
        except InvalidSymbolError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Volatility regime unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: volatility data could not be retrieved")

    return [get_crypto_klines, get_crypto_indicators, get_funding_rates, get_open_interest, get_crypto_ticker,
            get_order_book_depth, get_recent_trades_cvd, get_btc_eth_correlation, get_volatility_regime]
