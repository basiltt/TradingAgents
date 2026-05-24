"""LangChain @tool wrappers for crypto fundamentals, community, and derivatives data.

Hybrid approach: uses Bybit for price/volume/derivatives data (fast, generous rate limits)
and CoinGecko only for data Bybit cannot provide (market cap, supply, ATH/ATL, social).
"""

from __future__ import annotations

import logging
import re
import time as _time
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.coingecko_data import (
    get_coingecko_fundamentals_only,
    get_coingecko_community_data,
)
from tradingagents.dataflows.bybit_data import (
    get_bybit_derivatives_summary,
    get_bybit_orderbook,
    get_bybit_recent_trades,
    get_bybit_price_changes,
    project_funding_cost,
    get_bybit_funding_rates,
    InvalidSymbolError,
    BybitRateLimiter,
    BybitCircuitBreaker,
)

logger = logging.getLogger(__name__)

from tradingagents.agents.utils.tool_output import sanitize_tool_output as _sanitize


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
        """Retrieve comprehensive derivatives data from Bybit: OI, funding rates, long/short ratio, order book depth, CVD, whale trades, funding cost projection."""
        try:
            bybit_sym = _ensure_bybit_symbol(symbol)
            parts: list[str] = []

            # Core derivatives summary (OI, funding, L/S ratio, price changes)
            try:
                raw = get_bybit_derivatives_summary(
                    bybit_sym, cache=cache, limiter=limiter,
                    circuit_breaker=circuit_breaker, api_key=api_key, api_secret=api_secret,
                )
                parts.append(raw)
            except Exception as exc:
                parts.append(f"[Derivatives summary unavailable: {exc}]")

            # Order book depth + liquidity
            try:
                ob = get_bybit_orderbook(
                    bybit_sym, depth=50, cache=cache, limiter=limiter,
                    circuit_breaker=circuit_breaker, api_key=api_key, api_secret=api_secret,
                )
                ob_lines = ["\n## Order Book Depth"]
                ob_lines.append(f"Spread: {ob['spread_bps']:.2f} bps | Imbalance: {ob['imbalance_ratio']:+.4f}")
                ob_lines.append(f"Bid Depth: {ob['bid_depth']:.2f} | Ask Depth: {ob['ask_depth']:.2f}")
                if ob.get("wall_levels"):
                    ob_lines.append("Walls:")
                    for w in ob["wall_levels"][:5]:
                        ob_lines.append(f"  {w['side'].upper()} @ {w['price']} (size: {w['size']:.2f})")
                parts.append("\n".join(ob_lines))
            except Exception as exc:
                logger.debug("Order book unavailable for %s: %s", bybit_sym, exc)

            # Recent trades + CVD + whale detection
            try:
                trades = get_bybit_recent_trades(
                    bybit_sym, limit=500, cache=cache, limiter=limiter,
                    circuit_breaker=circuit_breaker, api_key=api_key, api_secret=api_secret,
                )
                cvd_lines = ["\n## Trade Flow (CVD & Whales)"]
                cvd_lines.append(f"CVD: {trades['cvd']:+.4f} | Buy Vol: {trades['buy_volume']:.2f} | Sell Vol: {trades['sell_volume']:.2f}")
                cvd_lines.append(f"Net Whale Flow: {trades['net_whale_flow']:+.4f} (threshold: {trades.get('whale_threshold_size', 0):.2f})")
                if trades.get("whale_trades"):
                    cvd_lines.append("Recent whale trades:")
                    for wt in trades["whale_trades"][:5]:
                        cvd_lines.append(f"  {wt['side']} {wt['size']:.4f} @ {wt['price']}")
                parts.append("\n".join(cvd_lines))
            except Exception as exc:
                logger.debug("Trade flow/CVD unavailable for %s: %s", bybit_sym, exc)

            # Funding cost projection
            try:
                now_ms = int(_time.time() * 1000)
                start_ms = now_ms - (7 * 24 * 60 * 60 * 1000)
                funding_text = get_bybit_funding_rates(
                    bybit_sym, start_ms, now_ms,
                    cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                    api_key=api_key, api_secret=api_secret,
                )
                # Parse rates from text format "  Timestamp: X, Rate: Y"
                rates = [float(m) for m in re.findall(r"Rate:\s*([-\d.]+)", funding_text)]
                if rates:
                    # Convert to CSV for project_funding_cost
                    csv_lines = ["timestamp,rate"] + [f"0,{r}" for r in rates]
                    proj = project_funding_cost("\n".join(csv_lines), hold_intervals=21)
                    if proj.get("total_rate") is not None:
                        fc_lines = ["\n## Funding Cost Projection (7-day hold)"]
                        fc_lines.append(f"Projected Cost: {proj.get('break_even_move_pct', 0):.4f}% of position")
                        fc_lines.append(f"Annualized: {proj.get('annualized_pct', 0):.2f}%")
                        fc_lines.append(f"Severity: {proj.get('severity', 'unknown')}")
                        if proj.get("severity") in ("elevated", "extreme"):
                            fc_lines.append("⚠ HIGH FUNDING: Holding cost is significant, factor into R:R")
                        parts.append("\n".join(fc_lines))
            except Exception as exc:
                logger.debug("Funding cost projection unavailable for %s: %s", bybit_sym, exc)

            return _sanitize("\n".join(parts))
        except InvalidSymbolError:
            return _sanitize(f"Symbol '{symbol}' is not available on Bybit linear perpetuals")
        except Exception as exc:
            logger.warning("Bybit derivatives data unavailable for %s: %s", symbol, exc)
            return _sanitize(f"[ERROR] Derivatives metrics unavailable: {exc}")

    return [get_crypto_market_data, get_crypto_community_data, get_crypto_derivatives_data]
