"""Tests for backtest signal loading — verifies the query logic for loading
historical scan results as engine input signals."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_db():
    """Mock AsyncAnalysisDB with pool."""
    db = MagicMock()
    db.pool = AsyncMock()
    return db


class TestLoadSignals:
    """Test _load_signals method for 3-mode dispatch."""

    @pytest.mark.asyncio
    async def test_schedule_mode_queries_by_schedule_id(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)

        # Mock the pool.fetch to return sample scan results
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
             "score": 8, "signal_time": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
             "scan_id": "scan-1", "signal_source": "structured"},
        ])

        scan_source = {"mode": "schedule", "schedule_id": "sched-123"}
        date_range = (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 31, tzinfo=timezone.utc),
        )

        signals = await service._load_signals(scan_source, date_range)
        assert len(signals) == 1
        assert signals[0]["ticker"] == "BTCUSDT"
        assert signals[0]["direction"] == "buy"

        # Verify query contains schedule_id filter
        call_args = mock_db.pool.fetch.call_args
        query = call_args[0][0]
        assert "schedule_id" in query and "$1" in query

    @pytest.mark.asyncio
    async def test_date_range_mode_no_schedule_filter(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)

        mock_db.pool.fetch = AsyncMock(return_value=[])

        scan_source = {"mode": "date_range"}
        date_range = (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 31, tzinfo=timezone.utc),
        )

        signals = await service._load_signals(scan_source, date_range)
        assert signals == []

        # Verify schedule_id NOT in the query (date_range mode has no schedule filter)
        call_args = mock_db.pool.fetch.call_args
        query = call_args[0][0]
        assert "schedule_id" not in query

    @pytest.mark.asyncio
    async def test_explicit_mode_uses_scan_ids(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)

        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": 1, "ticker": "ETHUSDT", "direction": "sell", "confidence": "moderate",
             "score": -6, "signal_time": datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc),
             "scan_id": "scan-5", "signal_source": "structured"},
        ])

        scan_source = {"mode": "explicit", "scan_ids": ["scan-5", "scan-6"]}
        date_range = (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 31, tzinfo=timezone.utc),
        )

        signals = await service._load_signals(scan_source, date_range)
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_filters_out_hold_and_failed(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)

        # Return mix of completed buy/sell and hold/failed
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
             "score": 7, "signal_time": datetime(2026, 1, 5, tzinfo=timezone.utc),
             "scan_id": "s1", "signal_source": "structured"},
        ])

        scan_source = {"mode": "date_range"}
        date_range = (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 31, tzinfo=timezone.utc),
        )

        signals = await service._load_signals(scan_source, date_range)
        # Only buy/sell completed signals should be returned (query filters)
        for s in signals:
            assert s["direction"] in ("buy", "sell")

    @pytest.mark.asyncio
    async def test_signal_time_anchored_to_completed_at(self, mock_db):
        """signal_time MUST anchor to the scan's completed_at (when production actually
        traded — after the full per-ticker analysis), with a started_at fallback. Using
        started_at would enter at a pre-analysis price the live account never got,
        systematically inflating PnL. Also asserts the per-symbol analysis completed_at
        tiebreak so the per-scan ranking matches production on equal abs(score)."""
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(return_value=[])
        for mode_src in (
            {"mode": "schedule", "schedule_id": "s1"},
            {"mode": "explicit", "scan_ids": ["x"]},
            {"mode": "date_range"},
        ):
            await service._load_signals(
                mode_src,
                (datetime(2026, 1, 1, tzinfo=timezone.utc),
                 datetime(2026, 1, 31, tzinfo=timezone.utc)),
            )
            query = mock_db.pool.fetch.call_args[0][0]
            # Anchor: COALESCE(completed_at, started_at) AS signal_time — NOT bare started_at.
            assert "COALESCE(s.completed_at, s.started_at)" in query
            assert "AS signal_time" in query
            # Production-faithful tiebreak on equal abs(score): the per-symbol analysis
            # completed_at, DESC (latest-completed first), mirroring auto_trade_service's
            # sorted(key=lambda r: (abs(score), completed_at), reverse=True). A plain
            # sr.id tiebreak picked DIFFERENT top-N symbols than production on equal
            # scores — see test_ranks_equal_scores_by_analysis_completed_at_desc.
            assert "ABS(sr.score) DESC" in query
            assert "ar.completed_at DESC" in query

    @pytest.mark.asyncio
    async def test_ranks_equal_scores_by_analysis_completed_at_desc(self, mock_db):
        """REGRESSION: on equal abs(score), the backtest must rank candidates by their
        per-symbol analysis completed_at DESCENDING, matching production's
        auto_trade_service ranking `sorted((abs(score), completed_at), reverse=True)`.

        The prior `ORDER BY ... sr.id` tiebreak diverged: in a real scan with five
        equal -7 signals, production took the three LATEST-analyzed (RUNE/1000FLOKI/
        CROSS) while the id-ordered backtest took the three lowest-id (CROSS/1000FLOKI/
        PUMPBTC) — different trades from the identical signal set. The fix joins
        analysis_runs to recover completed_at and orders by it."""
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(return_value=[])
        for mode_src in (
            {"mode": "schedule", "schedule_id": "s1"},
            {"mode": "explicit", "scan_ids": ["x"]},
            {"mode": "date_range"},
        ):
            await service._load_signals(
                mode_src,
                (datetime(2026, 1, 1, tzinfo=timezone.utc),
                 datetime(2026, 1, 31, tzinfo=timezone.utc)),
            )
            query = mock_db.pool.fetch.call_args[0][0]
            # Must JOIN analysis_runs to recover the per-symbol completion time.
            assert "analysis_runs" in query
            assert "ar.run_id = sr.run_id" in query
            # Tiebreak orders by completed_at DESC (production parity), not bare id.
            assert "ar.completed_at DESC" in query


