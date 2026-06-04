"""Dynamic sector classification service — CoinGecko + LLM + DB cache.

Provides get_sector(symbol) as a synchronous O(1) dict lookup (hot path)
and ensure_classified(symbols) as an async warm-up called at scan start.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

VALID_SECTORS = frozenset({"l1", "l2", "defi", "meme", "ai", "gaming", "infra", "exchange", "other"})

_SECTOR_TTL_HOURS = 168  # 7 days
_MAX_CLASSIFY_PER_BATCH = 50  # cap external calls per ensure_classified invocation

_LLM_SYSTEM_PROMPT = (
    "You are a cryptocurrency classification assistant. "
    "Given a trading symbol, classify it into exactly one sector. "
    "Respond with ONLY the sector name — no punctuation, no explanation."
)

# CoinGecko returns human-readable category strings.  Match via substring.
_CG_PATTERNS: list[tuple[str, str]] = [
    ("layer 1", "l1"), ("layer-1", "l1"), ("smart contract platform", "l1"),
    ("layer 2", "l2"), ("layer-2", "l2"), ("rollup", "l2"), ("scaling", "l2"),
    ("zero knowledge", "l2"),
    ("decentralized finance", "defi"), ("defi", "defi"), ("lending", "defi"),
    ("borrowing", "defi"), ("dex", "defi"), ("yield", "defi"),
    ("liquid staking", "defi"), ("amm", "defi"),
    ("meme", "meme"),
    ("artificial intelligence", "ai"), ("machine learning", "ai"),
    ("compute", "ai"), ("gpu", "ai"),
    ("gaming", "gaming"), ("metaverse", "gaming"), ("play-to-earn", "gaming"),
    ("gamefi", "gaming"),
    ("oracle", "infra"), ("storage", "infra"), ("interoperability", "infra"),
    ("cross-chain", "infra"), ("bridge", "infra"), ("data availability", "infra"),
    ("exchange", "exchange"), ("launchpad", "exchange"), ("cex token", "exchange"),
]


def _map_cg_categories(categories: list[str]) -> str | None:
    """Map CoinGecko category strings to our sector. First match wins."""
    for cat in categories:
        cat_lower = cat.lower()
        if cat_lower in ("cryptocurrency", "coin", "token"):
            continue
        for pattern, sector in _CG_PATTERNS:
            if pattern in cat_lower:
                return sector
    return None


class SectorService:
    """Hybrid sector classification: in-memory cache → DB → CoinGecko → LLM."""

    def __init__(self, db_pool: Any, llm_callable: Optional[Callable[..., Coroutine]] = None):
        self._pool = db_pool
        self._llm = llm_callable
        self._cache: dict[str, str] = {}

    async def load_cache(self) -> None:
        """Load all classified symbols from DB into memory. Call on startup."""
        try:
            rows = await self._pool.fetch("SELECT symbol, sector FROM symbol_sectors")
            self._cache = {row["symbol"]: row["sector"] for row in rows}
        except Exception:
            logger.warning("sector_service_load_cache_failed", exc_info=True)

        from backend.services.sector_map import _SECTOR_MAP
        for sym, sec in _SECTOR_MAP.items():
            self._cache.setdefault(sym, sec)
        logger.info("sector_service_cache_loaded", extra={"count": len(self._cache)})

    def get_sector(self, symbol: str) -> str:
        """Synchronous dict lookup — hot path. Never raises, never does I/O."""
        return self._cache.get(symbol, "other")

    async def ensure_classified(self, symbols: list[str]) -> None:
        """Pre-classify symbols not in cache or with stale DB entries."""
        to_classify: list[str] = []
        cached_symbols: list[str] = []

        for sym in symbols:
            if sym not in self._cache:
                to_classify.append(sym)
            else:
                cached_symbols.append(sym)

        # Check DB freshness for already-cached symbols
        if cached_symbols:
            try:
                rows = await self._pool.fetch(
                    "SELECT symbol FROM symbol_sectors "
                    "WHERE symbol = ANY($1) AND classified_at < NOW() - make_interval(hours => $2)",
                    cached_symbols, _SECTOR_TTL_HOURS,
                )
                to_classify.extend(row["symbol"] for row in rows)
            except Exception:
                pass

        if not to_classify:
            return

        # Cap external API calls per invocation to avoid rate-limit delays
        if len(to_classify) > _MAX_CLASSIFY_PER_BATCH:
            logger.info("sector_service_capping", extra={"total": len(to_classify), "cap": _MAX_CLASSIFY_PER_BATCH})
            to_classify = to_classify[:_MAX_CLASSIFY_PER_BATCH]

        logger.info("sector_service_classifying", extra={"count": len(to_classify)})
        for sym in to_classify:
            try:
                await self._classify_and_store(sym)
            except Exception:
                logger.debug("sector_classify_failed", extra={"symbol": sym}, exc_info=True)

    async def _classify_and_store(self, symbol: str) -> None:
        """Classify a single symbol via CoinGecko then LLM fallback."""
        sector = None
        source = "static"
        cg_cats = ""

        # Try CoinGecko first
        cg_result = await self._classify_via_coingecko(symbol)
        if cg_result:
            sector, cg_cats = cg_result
            source = "coingecko"

        # LLM fallback
        if not sector:
            sector = await self._classify_via_llm(symbol)
            source = "llm" if sector != "other" else "static"

        if not sector:
            sector = "other"
            source = "static"

        await self._store(symbol, sector, source, cg_cats)

    async def _classify_via_coingecko(self, symbol: str) -> tuple[str, str] | None:
        """Fetch CoinGecko categories and map to our sectors.

        Returns (sector, categories_string) on success, None on failure.
        """
        try:
            from tradingagents.dataflows.coingecko_data import get_coin_categories
            categories = await asyncio.to_thread(get_coin_categories, symbol)
            if not categories:
                return None
            sector = _map_cg_categories(categories)
            if not sector:
                return None
            cg_str = ", ".join(c for c in categories if c)
            return sector, cg_str
        except Exception:
            return None

    async def _classify_via_llm(self, symbol: str) -> str:
        """LLM classification fallback."""
        if not self._llm:
            return "other"
        try:
            clean_sym = symbol.replace("USDT", "").replace("PERP", "")
            prompt = (
                f"Classify the cryptocurrency '{clean_sym}' (trading as {symbol}) into exactly one sector:\n"
                "l1, l2, defi, meme, ai, gaming, infra, exchange, other\n"
                "Reply with ONLY the sector name."
            )
            result = await asyncio.wait_for(
                self._llm(_LLM_SYSTEM_PROMPT, prompt),
                timeout=15.0,
            )
            sector = result.strip().lower().rstrip(".")
            if sector in VALID_SECTORS:
                return sector
        except asyncio.TimeoutError:
            logger.debug("sector_llm_classify_timeout", extra={"symbol": symbol})
        except Exception:
            logger.debug("sector_llm_classify_failed", extra={"symbol": symbol}, exc_info=True)
        return "other"

    async def _store(self, symbol: str, sector: str, source: str, cg_categories: str = "") -> None:
        """Upsert into DB and update in-memory cache."""
        self._cache[symbol] = sector
        try:
            await self._pool.execute(
                "INSERT INTO symbol_sectors (symbol, sector, source, coingecko_categories, classified_at) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (symbol) DO UPDATE SET sector = $2, source = $3, "
                "coingecko_categories = $4, classified_at = $5",
                symbol, sector, source, cg_categories or None,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.warning("sector_store_failed", extra={"symbol": symbol}, exc_info=True)
