"""Kline Cache Service — fetch, store, and serve historical price data.

Manages the kline_cache PostgreSQL table (partitioned by month).
Fetches from Bybit public API on cache miss.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
# Bybit's kline endpoint accepts up to 1000 candles per page; using the max cuts
# request count 5x vs the old 200. _MAX_PAGES bounds a single fetch call as a
# runaway guard, but ensure_coverage now pages until the requested `start` is
# reached (see _fetch_klines_from_bybit) so a multi-day backfill is COMPLETE in
# one call rather than truncated at the newest ~1000 candles (the truncation that,
# combined with sealing, could permanently freeze a partial boundary day).
_PAGE_SIZE = 1000
# Safety cap on pages per fetch call. 60 × 1000 = 60k candles ≈ 208 days at 5m,
# comfortably above any single-symbol gap-run a backtest warms. A fetch needing
# more simply returns what it got; the unfetched tail stays an unsealed gap and is
# completed on a subsequent run (never wrongly sealed — see _seal_closed_days).
_MAX_PAGES = 60
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

        # Ensure partitions exist for all months in this batch
        months_seen: set[str] = set()
        for k in klines:
            open_time = k["open_time"]
            month_key = open_time.strftime("%Y_%m") if isinstance(open_time, datetime) else str(open_time)[:7].replace("-", "_")
            months_seen.add(month_key)
        for month_key in months_seen:
            await self._ensure_partition_exists(month_key)

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
        # Get all coverage records for the symbols + interval + date range.
        # `sealed` (v58) marks a closed day immutable: once sealed, its candle_count
        # is a FACT, never a refetch trigger — this is the RC-3 fix. We read it
        # defensively (COALESCE false) so the query also works pre-v58 / on a DB
        # where the column hasn't been added yet.
        query = """
            SELECT symbol, date, candle_count,
                   COALESCE(sealed, false) AS sealed
            FROM kline_cache_coverage
            WHERE symbol = ANY($1) AND interval = $2
              AND date >= $3 AND date <= $4
        """
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        rows = await self._db.pool.fetch(query, symbols, interval, start_date, end_date)

        # Map (symbol, date) → cached candle_count, and the set of SEALED days.
        # A date absent from the table has 0 count and is not sealed. Access `sealed`
        # defensively: a real pre-v58 DB (or a fake pool in older tests) may return a
        # row without the column — treat missing as not-sealed (the pre-fix behavior),
        # so the manifest is purely additive and never KeyErrors.
        counts: dict[str, dict[date, int]] = {}
        sealed: dict[str, set[date]] = {}
        for row in rows:
            counts.setdefault(row["symbol"], {})[row["date"]] = int(row["candle_count"] or 0)
            try:
                is_sealed = row["sealed"]
            except (KeyError, IndexError):
                is_sealed = False
            if is_sealed:
                sealed.setdefault(row["symbol"], set()).add(row["date"])

        # Candles per full day for this interval (1440 minutes / interval). Unknown
        # intervals fall back to 5m's 288 so a typo can't make every day look "complete".
        interval_min = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 5)
        per_day_full = max(1, 1440 // interval_min)

        def _expected_for(d: date) -> int:
            """Candles expected for day `d` within the requested [start, end] window.

            Interior days expect a full day. The FIRST and LAST day are clipped to the
            requested time-of-day, so a window ending mid-day (or starting mid-day) does
            not mark its boundary day as a perpetual gap. Clipping uses bar-count between
            the day's effective [lo, hi) span; a day fully inside the window expects the
            full per-day count.
            """
            day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            lo = max(day_start, start if isinstance(start, datetime) else day_start)
            hi = min(day_end, end if isinstance(end, datetime) else day_end)
            if hi <= lo:
                return 0
            span_min = (hi - lo).total_seconds() / 60.0
            # Number of bar OPENs in [lo, hi): floor(span / interval). A full day yields
            # per_day_full; a 6h tail yields 72 for 5m. Never exceed the full-day count.
            return min(per_day_full, max(0, int(span_min // interval_min)))

        # Generate expected dates
        expected_dates: list[date] = []
        current = start_date
        while current <= end_date:
            expected_dates.append(current)
            current += timedelta(days=1)

        # A date is a GAP when its cached candle_count is below the expected count for
        # that day (clipped to the requested window) AND it is not SEALED. Sealing
        # (v58) makes a closed day's count immutable: a sealed day with 144/288
        # candles is COMPLETE (the exchange had 144 bars), not a perpetual gap — this
        # is the RC-3 fix that stops re-downloading a fully-cached closed day on every
        # rerun. Unsealed days still use the count check (so a genuinely partial
        # forming day, or a pre-v58 short day, refetches once and then seals).
        gaps: dict[str, list[date]] = {}
        for sym in symbols:
            sym_counts = counts.get(sym, {})
            sym_sealed = sealed.get(sym, set())
            sym_gaps = [
                d for d in expected_dates
                if d not in sym_sealed and sym_counts.get(d, 0) < _expected_for(d)
            ]
            if sym_gaps:
                gaps[sym] = sym_gaps

        return gaps

    async def ensure_coverage(
        self,
        symbols: list[str],
        interval: str,
        start: datetime,
        end: datetime,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> dict[str, Any]:
        """Ensure kline data is cached for all symbols in the date range.

        Checks for gaps and fetches missing data from Bybit API. on_progress, when
        supplied, is called with an integer 0-100 reflecting how many of the gapped
        symbols have been processed — so a caller (the backtest) can surface warm-up
        progress instead of pinning its bar at 0% through a long fetch.

        Args:
            symbols: List of symbols needed.
            interval: Candle interval.
            start: Start of date range.
            end: End of date range.

        Returns:
            Stats dict: {cached: int, fetched: int, failed: int, symbols_with_gaps: list}
        """
        gaps = await self.get_coverage_gaps(symbols, interval, start, end)

        stats: dict[str, Any] = {
            "cached": len(symbols) - len(gaps),
            "fetched": 0,
            "failed": 0,
            "symbols_with_gaps": list(gaps.keys()),
        }

        if not gaps:
            return stats

        logger.info(
            "kline_coverage_gaps_found",
            extra={"gap_count": len(gaps), "symbols": list(gaps.keys())[:10]},
        )

        # Fill each gapped symbol from Bybit, fetching ONLY the span covering that
        # symbol's gap days — NOT the whole [start, end] window. Fetching the full range
        # every time is catastrophic once the partial-day fix marks the (always-
        # incomplete) current day as a gap: every symbol would refetch its entire history
        # on every run, making warm-up crawl. We fetch [min_gap_day, max_gap_day + 1d]
        # clipped to the requested window, so a single stale/partial day pulls only that
        # day, not months. Storing is idempotent (ON CONFLICT DO NOTHING). One symbol's
        # failure must not abort the rest, so each is isolated — a symbol the exchange
        # returns nothing for is counted failed (and its gap entry retained).
        still_missing: list[str] = []
        total_gaps = len(gaps)
        for idx, symbol in enumerate(gaps):
            gap_days = gaps[symbol]
            # Span the gap days only. lo = first gap day's 00:00 (clamped to start);
            # hi = last gap day's end-of-day (clamped to end) so the fetch is bounded.
            lo_day = min(gap_days)
            hi_day = max(gap_days)
            fetch_start = max(start, datetime(lo_day.year, lo_day.month, lo_day.day, tzinfo=timezone.utc))
            day_after_hi = datetime(hi_day.year, hi_day.month, hi_day.day, tzinfo=timezone.utc) + timedelta(days=1)
            fetch_end = min(end, day_after_hi)
            try:
                fetched = await self._fetch_klines_from_bybit(symbol, interval, fetch_start, fetch_end)
            except Exception:  # noqa: BLE001 — per-symbol isolation; network/parse errors
                logger.exception("kline_ensure_fetch_failed", extra={"symbol": symbol})
                fetched = []

            if not fetched:
                stats["failed"] += 1
                still_missing.append(symbol)
                continue

            await self.store_klines(symbol, interval, fetched)
            stats["fetched"] += 1

            if on_progress is not None and total_gaps:
                try:
                    on_progress(int(((idx + 1) / total_gaps) * 100))
                except Exception:  # noqa: BLE001 — progress is best-effort, never fatal
                    pass

        # symbols_with_gaps now reflects what's STILL uncovered after fetching, so
        # the caller (backtest pre-flight / cache_status) sees the true post-warmup
        # state rather than the pre-fetch gap list.
        stats["symbols_with_gaps"] = still_missing
        stats["cached"] = len(symbols) - len(still_missing)

        # SEAL fully-covered closed days in the window (RC-3 fix): once a day is below
        # the completion frontier AND has its full candle count, it is immutable — mark
        # it sealed so its candle_count is never re-evaluated again. Forming (current)
        # days are excluded (they keep refreshing until they close); PARTIAL days are
        # excluded by the candle_count guard inside _seal_closed_days (they stay gaps
        # and refetch). Seal ONLY symbols that did not still-miss this run, so a symbol
        # whose fetch failed/returned empty can't have its pre-existing partial rows
        # frozen (review SM-1). Best-effort: a seal failure must not fail the warm-up.
        sealable_symbols = [s for s in symbols if s not in set(still_missing)]
        try:
            if sealable_symbols:
                await self._seal_closed_days(sealable_symbols, interval, start, end)
            stats["sealed"] = True
        except Exception:  # noqa: BLE001 — sealing is an optimization, never fatal
            logger.warning("kline_seal_failed", extra={"interval": interval}, exc_info=False)
            stats["sealed"] = False

        return stats

    async def _seal_closed_days(
        self,
        symbols: list[str],
        interval: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Mark every FULLY-COVERED CLOSED day in [start, end] as sealed.

        A day is closed (immutable) when its end is at/below the completion frontier
        floor(now/T)*T. Sealing sets `sealed=true` so get_coverage_gaps stops
        re-checking that day's candle_count — the RC-3 fix.

        CRITICAL provenance guard (review SM-1): a day is sealed ONLY if its stored
        candle_count has reached the expected FULL-day count for the interval. This
        prevents permanently freezing a PARTIAL day — e.g. when a large backfill's
        oldest touched day stored only part of its candles. A still-partial day stays
        unsealed, remains a gap, and is completed on a later run (the same self-healing
        the pre-sealing code had), so the engine never silently walks fewer klines
        than a correct fetch would supply. (A genuinely short exchange day will not
        reach the full count and simply re-attempts until the fetch is authoritative;
        because _fetch_klines_from_bybit now pages to `start`, a day that stays short
        after a complete fetch is real no-data, and re-attempting it is cheap + bounded.)

        Returns the number of (symbol,date) cells sealed.
        """
        from backend.services.sealed_manifest import completion_frontier, day_is_closed

        frontier = completion_frontier(datetime.now(tz=timezone.utc), interval)
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        # Enumerate closed days in the window.
        closed_days: list[date] = []
        cur = start_date
        while cur <= end_date:
            if day_is_closed(cur, frontier):
                closed_days.append(cur)
            cur += timedelta(days=1)
        if not closed_days:
            return 0

        # Expected FULL-day candle count for this interval (288 for 5m). A day must
        # have at least this many stored candles to be sealed — the provenance guard.
        interval_min = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 5)
        per_day_full = max(1, 1440 // interval_min)

        # Seal only existing, not-yet-sealed, FULLY-COVERED coverage rows for these
        # closed days. The candle_count >= per_day_full guard is the SM-1 fix.
        result = await self._db.pool.execute(
            """
            UPDATE kline_cache_coverage
            SET sealed = true, sealed_at = now()
            WHERE symbol = ANY($1) AND interval = $2
              AND date = ANY($3) AND sealed = false
              AND candle_count >= $4
            """,
            symbols, interval, closed_days, per_day_full,
        )
        # asyncpg returns e.g. "UPDATE 12"; parse the affected-row count defensively.
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError):
            return 0

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

        # Upsert coverage records. Use GREATEST so the recorded count only ever GROWS:
        # store_klines inserts with ON CONFLICT DO NOTHING (it never deletes), so a later
        # partial store (e.g. a single backfilled candle, or a narrow gap-day refetch)
        # must NOT clobber a day that was already fully covered. The old
        # `candle_count = EXCLUDED.candle_count` overwrote 288 with the latest batch's
        # smaller count, making get_coverage_gaps see the day as a perpetual gap and
        # refetch it on every run.
        query = """
            INSERT INTO kline_cache_coverage (symbol, interval, date, candle_count, fetched_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (symbol, interval, date)
            DO UPDATE SET candle_count = GREATEST(kline_cache_coverage.candle_count, EXCLUDED.candle_count),
                          fetched_at = now()
        """
        records = [(symbol, interval, d, count) for d, count in date_counts.items()]
        await self._db.pool.executemany(query, records)

    async def _ensure_partition_exists(self, month_key: str) -> None:
        """Create a monthly partition for kline_cache if it doesn't exist.

        Args:
            month_key: Format "YYYY_MM" (e.g., "2026_01").
        """
        try:
            parts = month_key.split("_")
            year, month = int(parts[0]), int(parts[1])
            month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

            part_name = f"kline_cache_{month_key}"
            await self._db.pool.execute(f"""
                CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF kline_cache
                    FOR VALUES FROM ('{month_start.strftime('%Y-%m-%d')}')
                    TO ('{month_end.strftime('%Y-%m-%d')}')
            """)
        except Exception as e:
            # DuplicateTable is expected (race condition between concurrent backtests)
            # Other errors are logged but non-fatal — INSERT will fail with clearer message
            err_name = type(e).__name__
            if "Duplicate" not in err_name and "already exists" not in str(e):
                logger.warning("partition_create_failed", extra={"month_key": month_key, "error": str(e)[:200]})

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
        # Convert interval format: "1m" → "1", "5m" → "5", "1h" → "60", "4h" → "240"
        interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
        bybit_interval = interval_map.get(interval, interval)

        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_candles: list[list[str]] = []
        current_end = end_ms

        async with httpx.AsyncClient(timeout=30.0) as client:
            for _page in range(_MAX_PAGES):
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

                try:
                    data = resp.json()
                except (ValueError, Exception):
                    logger.error("kline_malformed_response", extra={"symbol": symbol, "body": resp.text[:200] if hasattr(resp, 'text') else ""})
                    break
                if data.get("retCode") != 0:
                    logger.error("kline_fetch_api_error", extra={"symbol": symbol, "retCode": data.get("retCode")})
                    break

                candles = data.get("result", {}).get("list", [])
                if not candles:
                    break

                all_candles.extend(candles)

                # Pagination: move end pointer to oldest candle in batch - 1
                try:
                    oldest_ts = int(candles[-1][0])  # Last in descending = oldest
                except (ValueError, IndexError):
                    break
                if oldest_ts <= start_ms:
                    break
                current_end = oldest_ts - 1

        if not all_candles:
            return []

        # Parse string arrays → dicts, reverse to ascending
        klines: list[dict[str, Any]] = []
        for candle in reversed(all_candles):
            try:
                if len(candle) < 6:
                    continue
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
            except (ValueError, IndexError, TypeError):
                logger.warning("kline_parse_skip", extra={"symbol": symbol, "candle": str(candle)[:100]})
                continue

        logger.debug(
            "kline_fetch_complete",
            extra={"symbol": symbol, "interval": interval, "candles": len(klines)},
        )
        return klines


_BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"

# Fallback for symbols we couldn't resolve (refresh failure, or a symbol beyond the
# instruments page). Chosen to be NO-OPs in the backtest engine: tick_size=0 disables
# TP/SL rounding and max_leverage=0 disables the leverage cap, so an unknown symbol
# behaves exactly as if no instrument info were supplied (rather than imposing a
# possibly-wrong tick/cap). qty_step/min_qty keep the engine's prior 0.001 behaviour.
_DEFAULT_INSTRUMENT_INFO = {
    "qty_step": 0.001,
    "min_qty": 0.001,
    "tick_size": 0.0,       # 0 → no TP/SL rounding for unresolved symbols
    "max_leverage": 0,      # 0 → no leverage cap for unresolved symbols
}


class InstrumentInfoCache:
    """In-memory cache of per-symbol instrument parameters.

    Refreshed from Bybit public API. Used by the backtest engine
    to enforce qty_step, min_qty, tick_size, and max_leverage per symbol.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, float]] = {}
        self._last_refresh: Optional[datetime] = None

    def get(self, symbol: str) -> Optional[dict[str, float]]:
        """Get instrument info for a symbol. Returns None if not cached. Always returns a COPY."""
        info = self._cache.get(symbol)
        return info.copy() if info is not None else None

    def get_or_default(self, symbol: str) -> dict[str, float]:
        """Get instrument info with conservative defaults for unknown symbols. Always returns a COPY."""
        info = self._cache.get(symbol)
        return info.copy() if info is not None else _DEFAULT_INSTRUMENT_INFO.copy()

    async def refresh(self) -> int:
        """Fetch all linear perpetual instrument info from Bybit.

        Returns:
            Number of instruments cached.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    _BYBIT_INSTRUMENTS_URL,
                    params={"category": "linear", "limit": "1000"},
                )
                if resp.status_code != 200:
                    logger.warning("instrument_fetch_failed", extra={"status": resp.status_code})
                    return 0

                data = resp.json()
                if data.get("retCode") != 0:
                    return 0

                instruments = data.get("result", {}).get("list", [])
                for inst in instruments:
                    symbol = inst.get("symbol", "")
                    if not symbol:
                        continue

                    lot_filter = inst.get("lotSizeFilter", {})
                    price_filter = inst.get("priceFilter", {})
                    lev_filter = inst.get("leverageFilter", {})

                    self._cache[symbol] = {
                        "qty_step": float(lot_filter.get("qtyStep", "0.001")),
                        "min_qty": float(lot_filter.get("minOrderQty", "0.001")),
                        "tick_size": float(price_filter.get("tickSize", "0.01")),
                        "max_leverage": int(float(lev_filter.get("maxLeverage", "25"))),
                    }

                self._last_refresh = datetime.now(tz=timezone.utc)
                logger.info("instrument_cache_refreshed", extra={"count": len(self._cache)})
                return len(self._cache)

        except Exception:
            logger.exception("instrument_cache_refresh_error")
            return 0
