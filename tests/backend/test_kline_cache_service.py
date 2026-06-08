"""Tests for KlineCacheService — kline data storage, retrieval, and gap detection."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_db():
    """Mock DB with asyncpg pool."""
    db = MagicMock()
    db.pool = AsyncMock()
    db.pool.fetch = AsyncMock(return_value=[])
    db.pool.execute = AsyncMock()
    db.pool.executemany = AsyncMock()
    db.pool.fetchval = AsyncMock(return_value=None)
    return db


class TestGetKlines:
    """Test reading klines from cache."""

    @pytest.mark.asyncio
    async def test_returns_klines_in_ascending_order(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        mock_db.pool.fetch.return_value = [
            {"open_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
             "open": 50000.0, "high": 50100.0, "low": 49900.0,
             "close": 50050.0, "volume": 100.0},
            {"open_time": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
             "open": 50050.0, "high": 50200.0, "low": 50000.0,
             "close": 50150.0, "volume": 80.0},
        ]

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        klines = await svc.get_klines("BTCUSDT", "5m", start, end)

        assert len(klines) == 2
        assert klines[0]["open_time"] < klines[1]["open_time"]
        assert klines[0]["close"] == 50050.0

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_data(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)
        klines = await svc.get_klines("XYZUSDT", "5m", start, end)
        assert klines == []


class TestStoreKlines:
    """Test storing klines to cache."""

    @pytest.mark.asyncio
    async def test_stores_klines_with_on_conflict(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        klines = [
            {"open_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
             "open": 50000.0, "high": 50100.0, "low": 49900.0,
             "close": 50050.0, "volume": 100.0},
        ]

        count = await svc.store_klines("BTCUSDT", "5m", klines)
        # Should have called executemany or execute
        assert mock_db.pool.executemany.called or mock_db.pool.execute.called


class TestGetCoverageGaps:
    """Test gap detection in cached kline data."""

    @pytest.mark.asyncio
    async def test_detects_missing_days(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        # Coverage table has data for Jan 1 and Jan 3, but NOT Jan 2
        mock_db.pool.fetch.return_value = [
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 1).date(), "candle_count": 288},
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 3).date(), "candle_count": 288},
        ]

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 3, 23, 59, tzinfo=timezone.utc)

        gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
        assert "BTCUSDT" in gaps
        assert len(gaps["BTCUSDT"]) > 0  # Should show Jan 2 as a gap

    @pytest.mark.asyncio
    async def test_no_gaps_when_fully_covered(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        # All 3 days covered
        mock_db.pool.fetch.return_value = [
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 1).date(), "candle_count": 288},
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 2).date(), "candle_count": 288},
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 3).date(), "candle_count": 288},
        ]

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 3, 23, 59, tzinfo=timezone.utc)

        gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
        assert gaps.get("BTCUSDT", []) == []

    @pytest.mark.asyncio
    async def test_partial_interior_day_is_a_gap(self, mock_db):
        """A fully-elapsed interior day with FEWER than the full candle count (e.g. 73 of
        288 for 5m) must be reported as a GAP, so ensure_coverage refetches the rest.

        Regression: get_coverage_gaps treated a date as covered if it appeared in the
        coverage table AT ALL, ignoring candle_count — so a partially-warmed day (73/288)
        was 'covered' and never refilled, and the backtest read a truncated series and
        fabricated fills on stale candles."""
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        mock_db.pool.fetch.return_value = [
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 1).date(), "candle_count": 288},
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 2).date(), "candle_count": 73},   # PARTIAL
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 3).date(), "candle_count": 288},
        ]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 3, 23, 59, tzinfo=timezone.utc)

        gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
        assert datetime(2026, 1, 2).date() in gaps.get("BTCUSDT", []), (
            "a 73/288 interior day must count as a gap, not 'covered'"
        )
        # The full days must NOT be flagged.
        assert datetime(2026, 1, 1).date() not in gaps.get("BTCUSDT", [])
        assert datetime(2026, 1, 3).date() not in gaps.get("BTCUSDT", [])

    @pytest.mark.asyncio
    async def test_partial_end_day_clipped_to_requested_time_is_not_a_gap(self, mock_db):
        """The END day is legitimately partial when the window ends mid-day: a backtest
        to 06:00 only needs that day's candles up to 06:00 (72 for 5m). A day with >= the
        clipped expected count must NOT be a perpetual gap (else every run refetches its
        last day forever)."""
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        # End at 06:00 → expected for the end day = 6h * 12 = 72 candles (5m). We have 72.
        mock_db.pool.fetch.return_value = [
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 1).date(), "candle_count": 288},
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 2).date(), "candle_count": 72},
        ]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, 6, 0, tzinfo=timezone.utc)

        gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
        assert gaps.get("BTCUSDT", []) == [], (
            "the end day clipped to the requested time was fully covered (72/72) but was "
            f"flagged as a gap: {gaps}"
        )


class TestEnsureCoverage:
    """Test the ensure_coverage orchestration method."""

    @pytest.mark.asyncio
    async def test_returns_stats_dict(self, mock_db):
        from backend.services.kline_cache_service import KlineCacheService
        svc = KlineCacheService(db=mock_db)

        # Mock: no gaps (fully cached)
        mock_db.pool.fetch.return_value = [
            {"symbol": "BTCUSDT", "date": datetime(2026, 1, 1).date(), "candle_count": 288},
        ]

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)

        stats = await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)
        assert "cached" in stats or "fetched" in stats

    @pytest.mark.asyncio
    async def test_fetches_and_stores_when_gap_exists(self, mock_db):
        """When a symbol has a coverage gap, ensure_coverage must fetch the
        missing klines from Bybit and store them — not silently no-op.

        Regression: ensure_coverage was a stub that computed gaps, logged, and
        returned fetched=0 without ever calling the (working) fetcher, leaving the
        kline cache with no writer and every backtest failing coverage pre-flight.
        """
        from backend.services.kline_cache_service import KlineCacheService

        svc = KlineCacheService(db=mock_db)

        # Coverage table is EMPTY → the whole range is a gap.
        mock_db.pool.fetch.return_value = []

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)

        fetched_candles = [
            {"open_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
             "open": 50000.0, "high": 50100.0, "low": 49900.0,
             "close": 50050.0, "volume": 100.0},
            {"open_time": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
             "open": 50050.0, "high": 50200.0, "low": 50000.0,
             "close": 50150.0, "volume": 80.0},
        ]

        with patch.object(
            svc, "_fetch_klines_from_bybit",
            new=AsyncMock(return_value=fetched_candles),
        ) as mock_fetch, patch.object(
            svc, "store_klines",
            new=AsyncMock(return_value=len(fetched_candles)),
        ) as mock_store:
            stats = await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)

        # It must have actually fetched the missing symbol...
        mock_fetch.assert_awaited()
        assert mock_fetch.await_args.args[0] == "BTCUSDT"
        # ...and persisted what it fetched...
        mock_store.assert_awaited()
        assert mock_store.await_args.args[0] == "BTCUSDT"
        # ...and reported a non-zero fetched count.
        assert stats["fetched"] >= 1
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_records_failure_when_fetch_returns_nothing(self, mock_db):
        """A symbol the exchange returns no data for is counted as failed, not
        silently dropped (so the caller can surface a real coverage problem)."""
        from backend.services.kline_cache_service import KlineCacheService

        svc = KlineCacheService(db=mock_db)
        mock_db.pool.fetch.return_value = []  # full gap

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)

        with patch.object(
            svc, "_fetch_klines_from_bybit",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            svc, "store_klines", new=AsyncMock(return_value=0),
        ) as mock_store:
            stats = await svc.ensure_coverage(["DEADUSDT"], "5m", start, end)

        assert stats["fetched"] == 0
        assert stats["failed"] == 1
        mock_store.assert_not_awaited()
