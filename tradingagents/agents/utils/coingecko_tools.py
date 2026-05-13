"""LangChain @tool wrappers for crypto fundamentals, community, and derivatives data.

Hybrid approach: uses Bybit for price/volume/derivatives data (fast, generous rate limits)
and CoinGecko only for data Bybit cannot provide (market cap, supply, ATH/ATL, social).
"""

from __future__ import annotations

import html
import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.coingecko_data import (
    get_coingecko_fundamentals_only,
    get_coingecko_community_data,
)
from tradingagents.dataflows.bybit_data import (
    get_bybit_derivatives_summary,
    get_bybit_price_changes,
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


def _ensure_bybit_symbol(symbol: str) -> str:
    """Ensure symbol is in Bybit linear perpetual format (e.g. BTCUSDT).

    CoinGecko tools receive symbols like 'BTC', 'BTCUSDT', 'BTCUSD', or 'ETHPERP'.
    Bybit linear perpetuals are exclusively USDT-margined.
    """
    upper = symbol.upper().strip()
    # Strip known non-USDT suffixes
    for suffix in ("PERP",):
        if upper.endswith(suffix):
            upper = upper[:-len(suffix)]
            break
    # Already correct format
    if upper.endswith("USDT"):
        return upper
    # "BTCUSD" or "BTCUSDC" → replace suffix with USDT
    if upper.endswith("USDC"):
        upper = upper[:-4]
    elif upper.endswith("USD"):
        upper = upper[:-3]
    return upper + "USDT"


def make_coingecko_tools(
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> list:
    @tool
    def get_crypto_market_data(
        symbol: Annotated[str, "Crypto symbol, e.g. BTCUSDT or BTC"],
    ) -> str:
        """Retrieve market fundamentals: market cap, supply, ATH/ATL, FDV, description (CoinGecko) + price changes (Bybit)."""
        parts: list[str] = []

        # CoinGecko: only market cap, supply, ATH/ATL, FDV, description
        try:
            fundamentals = get_coingecko_fundamentals_only(symbol)
            parts.append(fundamentals)
        except Exception as exc:
            logger.warning("CoinGecko fundamentals unavailable for %s: %s", symbol, exc)
            parts.append(f"[ERROR] CoinGecko fundamentals unavailable: {exc}")

        # Bybit: price change percentages (24h, 7d, 14d, 30d, 60d, 200d, 1y)
        try:
            bybit_sym = _ensure_bybit_symbol(symbol)
            changes = get_bybit_price_changes(
                bybit_sym, cache=cache, limiter=limiter,
                circuit_breaker=circuit_breaker, api_key=api_key, api_secret=api_secret,
            )
            if changes:
                parts.append("\n## Price Changes (from Bybit)")
                parts.append("| Period | Change % |")
                parts.append("|--------|----------|")
                for period, pct in changes.items():
                    parts.append(f"| {period} | {pct}% |" if pct is not None else f"| {period} | N/A |")
        except InvalidSymbolError:
            logger.info("Symbol %s not on Bybit, skipping price changes", symbol)
        except Exception as exc:
            logger.warning("Bybit price changes unavailable for %s: %s", symbol, exc)
            parts.append(f"\n[ERROR] Bybit price changes unavailable: {exc}")

        return _sanitize("\n".join(parts))

    @tool
    def get_crypto_community_data(
        symbol: Annotated[str, "Crypto symbol, e.g. BTCUSDT or BTC"],
    ) -> str:
        """Retrieve community and social metrics: Twitter followers, Reddit activity, developer stats, sentiment."""
        try:
            raw = get_coingecko_community_data(symbol)
            return _sanitize(raw)
        except Exception as exc:
            logger.warning("CoinGecko community data unavailable for %s: %s", symbol, exc)
            return _sanitize(f"[ERROR] Community metrics unavailable: {exc}")

    @tool
    def get_crypto_derivatives_data(
        symbol: Annotated[str, "Crypto symbol, e.g. BTCUSDT or BTC"],
    ) -> str:
        """Retrieve derivatives data from Bybit: open interest, funding rates, long/short ratio, price changes."""
        try:
            bybit_sym = _ensure_bybit_symbol(symbol)
            raw = get_bybit_derivatives_summary(
                bybit_sym, cache=cache, limiter=limiter,
                circuit_breaker=circuit_breaker, api_key=api_key, api_secret=api_secret,
            )
            return _sanitize(raw)
        except InvalidSymbolError:
            return _sanitize(f"Symbol '{symbol}' is not available on Bybit linear perpetuals")
        except Exception as exc:
            logger.warning("Bybit derivatives data unavailable for %s: %s", symbol, exc)
            return _sanitize(f"[ERROR] Derivatives metrics unavailable: {exc}")

    return [get_crypto_market_data, get_crypto_community_data, get_crypto_derivatives_data]
