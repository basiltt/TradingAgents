"""LangChain @tool wrappers for CoinGecko crypto fundamentals and community data.

Factory function ``make_coingecko_tools`` returns bound tool instances.
"""

from __future__ import annotations

import html
import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.coingecko_data import (
    get_coingecko_market_data,
    get_coingecko_community_data,
)

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 50 * 1024


def _sanitize(raw: str) -> str:
    if len(raw) > _MAX_OUTPUT_CHARS:
        raw = raw[:_MAX_OUTPUT_CHARS] + "\n[truncated]"
    escaped = html.escape(raw, quote=False)
    return f"<data>{escaped}</data>"


def make_coingecko_tools() -> list:
    @tool
    def get_crypto_market_data(
        symbol: Annotated[str, "Crypto symbol, e.g. BTCUSDT or BTC"],
    ) -> str:
        """Retrieve market fundamentals: market cap, volume, supply, ATH/ATL, price changes."""
        try:
            raw = get_coingecko_market_data(symbol)
            return _sanitize(raw)
        except Exception as exc:
            logger.warning("CoinGecko market data unavailable for %s: %s", symbol, exc)
            return _sanitize("Data unavailable: market fundamentals could not be retrieved")

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
            return _sanitize("Data unavailable: community metrics could not be retrieved")

    return [get_crypto_market_data, get_crypto_community_data]
