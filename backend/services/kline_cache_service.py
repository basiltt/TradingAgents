"""Kline Cache Service — fetch, store, and serve historical price data.

Manages the kline_cache PostgreSQL table (partitioned by month).
Fetches from Bybit public API on cache miss.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
_PAGE_SIZE = 200
_MAX_PAGES = 5
_MAX_RETRIES = 3


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

    async def _fetch_klines_from_bybit(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch klines from Bybit public API with pagination and retry.

        Bybit returns candles in DESCENDING order (newest first).
        We reverse to ascending before returning.

        Response format: result.list → arrays of 7 STRING elements:
        [timestamp_ms, open, high, low, close, volume, turnover]

        Pagination: end-pointer based (set end = min_timestamp - 1 to get older).
        Max 5 pages × 200 = 1000 candles per call.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT").
            interval: Candle interval (e.g., "5", "15", "60", "240", "D").
            start: Start time (inclusive).
            end: End time (inclusive).

        Returns:
            List of kline dicts sorted ascending by open_time.
        """
        # Convert interval format: "5m" → "5", "1h" → "60", "4h" → "240"
        interval_map = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
        bybit_interval = interval_map.get(interval, interval)

        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_candles: list[list[str]] = []
        current_end = end_ms

        async with httpx.AsyncClient(timeout=30.0) as client:
            for page in range(_MAX_PAGES):
                if current_end <= start_ms:
                    break

                params = {
                    "category": "linear",
                    "symbol": symbol,
                    "interval": bybit_interval,
                    "start": str(start_ms),
                    "end": str(current_end),
                    "limit": str(_PAGE_SIZE),
                }

                # Retry loop
                resp = None
                for attempt in range(_MAX_RETRIES):
                    try:
                        resp = await client.get(_BYBIT_KLINE_URL, params=params)
                        if resp.status_code == 200:
                            break
                        if resp.status_code in (429, 500, 502, 503, 504):
                            delay = (attempt + 1) ** 2  # 1s, 4s, 9s
                            logger.warning(
                                "kline_fetch_retry",
                                extra={"symbol": symbol, "status": resp.status_code, "attempt": attempt + 1},
                            )
                            await asyncio.sleep(delay)
                        else:
                            break  # Non-retryable error
                    except (httpx.TimeoutException, httpx.ConnectError) as e:
                        delay = (attempt + 1) ** 2
                        logger.warning("kline_fetch_error", extra={"symbol": symbol, "error": str(e)[:100]})
                        await asyncio.sleep(delay)

                if resp is None or resp.status_code != 200:
                    logger.error("kline_fetch_failed", extra={"symbol": symbol, "interval": interval})
                    break

                data = resp.json()
                if data.get("retCode") != 0:
                    logger.error("kline_fetch_api_error", extra={"symbol": symbol, "retCode": data.get("retCode")})
                    break

                candles = data.get("result", {}).get("list", [])
                if not candles:
                    break

                all_candles.extend(candles)

                # Pagination: move end pointer to oldest candle in batch - 1
                oldest_ts = int(candles[-1][0])  # Last in descending = oldest
                if oldest_ts <= start_ms:
                    break
                current_end = oldest_ts - 1

        if not all_candles:
            return []

        # Parse string arrays → dicts, reverse to ascending
        klines: list[dict[str, Any]] = []
        for candle in reversed(all_candles):
            ts_ms = int(candle[0])
            # Filter: only include candles within requested range
            if ts_ms < start_ms or ts_ms > end_ms:
                continue
            klines.append({
                "open_time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            })

        logger.debug(
            "kline_fetch_complete",
            extra={"symbol": symbol, "interval": interval, "candles": len(klines)},
        )
        return klines
