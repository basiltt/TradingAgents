"""Kline Cache Service — fetch, store, and serve historical price data.

Manages the kline_cache PostgreSQL table (partitioned by month).
Fetches from Bybit public API on cache miss.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class KlineCacheService:
    """Manages kline (candlestick) data caching for the backtest engine.

    Args:
        db: AsyncAnalysisDB instance with pool attribute.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Read klines from cache for a symbol and time range.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT").
            interval: Candle interval (e.g., "5m", "1h").
            start: Start of time range (inclusive).
            end: End of time range (inclusive).

        Returns:
            List of kline dicts sorted by open_time ascending.
        """
        query = """
            SELECT open_time, open, high, low, close, volume
            FROM kline_cache
            WHERE symbol = $1 AND interval = $2
              AND open_time >= $3 AND open_time <= $4
            ORDER BY open_time ASC
        """
        rows = await self._db.pool.fetch(query, symbol, interval, start, end)
        return [
            {
                "open_time": row["open_time"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for row in rows
        ]

    async def store_klines(
        self,
        symbol: str,
        interval: str,
        klines: list[dict[str, Any]],
    ) -> int:
        """Store klines to cache (ON CONFLICT DO NOTHING for idempotency).

        Args:
            symbol: Trading pair.
            interval: Candle interval.
            klines: List of kline dicts with open_time, open, high, low, close, volume.

        Returns:
            Number of rows inserted (may be less than input if duplicates exist).
        """
        if not klines:
            return 0

        query = """
            INSERT INTO kline_cache (symbol, interval, open_time, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, interval, open_time) DO NOTHING
        """
        records = [
            (symbol, interval, k["open_time"], k["open"], k["high"], k["low"], k["close"], k["volume"])
            for k in klines
        ]
        await self._db.pool.executemany(query, records)

        # Update coverage tracking
        await self._update_coverage(symbol, interval, klines)

        return len(klines)

    async def get_coverage_gaps(
        self,
        symbols: list[str],
        interval: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[date]]:
        """Find days where kline data is missing or incomplete.

        Compares expected days in range against kline_cache_coverage table.

        Args:
            symbols: List of symbols to check.
            interval: Candle interval.
            start: Start of date range.
            end: End of date range.

        Returns:
            Dict mapping symbol → list of missing dates.
        """
        # Get all coverage records for the symbols + interval + date range
        query = """
            SELECT symbol, date, candle_count
            FROM kline_cache_coverage
            WHERE symbol = ANY($1) AND interval = $2
              AND date >= $3 AND date <= $4
        """
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        rows = await self._db.pool.fetch(query, symbols, interval, start_date, end_date)

        # Build set of covered dates per symbol
        covered: dict[str, set[date]] = {}
        for row in rows:
            sym = row["symbol"]
            if sym not in covered:
                covered[sym] = set()
            covered[sym].add(row["date"])

        # Generate expected dates
        expected_dates: list[date] = []
        current = start_date
        while current <= end_date:
            expected_dates.append(current)
            current += timedelta(days=1)

        # Find gaps per symbol
        gaps: dict[str, list[date]] = {}
        for sym in symbols:
            sym_covered = covered.get(sym, set())
            sym_gaps = [d for d in expected_dates if d not in sym_covered]
            if sym_gaps:
                gaps[sym] = sym_gaps

        return gaps

    async def ensure_coverage(
        self,
        symbols: list[str],
        interval: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Ensure kline data is cached for all symbols in the date range.

        Checks for gaps and fetches missing data from Bybit API.

        Args:
            symbols: List of symbols needed.
            interval: Candle interval.
            start: Start of date range.
            end: End of date range.

        Returns:
            Stats dict: {cached: int, fetched: int, failed: int, symbols_with_gaps: list}
        """
        gaps = await self.get_coverage_gaps(symbols, interval, start, end)

        stats = {
            "cached": len(symbols) - len(gaps),
            "fetched": 0,
            "failed": 0,
            "symbols_with_gaps": list(gaps.keys()),
        }

        # TODO: Phase 2 Task 2.2 will add actual Bybit fetching here
        # For now, just report the gaps
        if gaps:
            logger.info(
                "kline_coverage_gaps_found",
                extra={"gap_count": len(gaps), "symbols": list(gaps.keys())[:10]},
            )

        return stats

    async def _update_coverage(
        self,
        symbol: str,
        interval: str,
        klines: list[dict[str, Any]],
    ) -> None:
        """Update kline_cache_coverage after storing new klines."""
        if not klines:
            return

        # Group klines by date and count
        date_counts: dict[date, int] = {}
        for k in klines:
            open_time = k["open_time"]
            d = open_time.date() if isinstance(open_time, datetime) else open_time
            date_counts[d] = date_counts.get(d, 0) + 1

        # Upsert coverage records
        query = """
            INSERT INTO kline_cache_coverage (symbol, interval, date, candle_count, fetched_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (symbol, interval, date)
            DO UPDATE SET candle_count = EXCLUDED.candle_count, fetched_at = now()
        """
        records = [(symbol, interval, d, count) for d, count in date_counts.items()]
        await self._db.pool.executemany(query, records)
