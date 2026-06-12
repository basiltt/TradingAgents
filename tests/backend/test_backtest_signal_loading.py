"""Tests for backtest signal loading — verifies the query logic for loading
historical scan results as engine input signals."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


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
        timestamp and preserves live's stable per-scan input order."""
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
            # The loader must carry result.completed_at but not pre-rank candidates;
            # the engine does live's stable in-memory sort per scan.
            assert "sr.completed_at::timestamptz AS completed_at" in query
            assert "ORDER BY signal_time, sr.id" in query
            assert "ABS(sr.score) DESC" not in query

    @pytest.mark.asyncio
    async def test_loads_completed_at_without_sql_reranking(self, mock_db):
        """REGRESSION: SQL must not pick winners by score/id before the engine sees the
        scan. Live dedupes and stable-sorts the in-memory scan results; the loader
        therefore preserves insertion order and only provides completed_at fields."""
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
            # analysis_runs remains available for copied rows whose
            # scan_results.completed_at is NULL, but SQL must not pre-rank signals.
            assert "analysis_runs" in query
            assert "ar.run_id = sr.run_id" in query
            assert "sr.completed_at::timestamptz AS completed_at" in query
            assert "ORDER BY signal_time, sr.id" in query
            assert "ar.completed_at DESC" not in query

    @pytest.mark.asyncio
    async def test_analysis_completed_at_is_loaded_separately_from_result_completed_at(self, mock_db):
        """Rows with NULL scan_results.completed_at must keep completed_at NULL.

        analysis_completed_at is carried separately so the engine can reconstruct
        normal batch ranking without changing SQL ordering or post-scan recheck
        ranking.
        """
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        analysis_done = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(return_value=[{
            "id": 1,
            "ticker": "BTCUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": -8,
            "signal_time": datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
            "completed_at": None,
            "analysis_completed_at": analysis_done,
            "scan_id": "scan-1",
            "signal_source": "structured",
            "analysis_price": None,
        }])

        signals = await service._load_signals(
            {"mode": "schedule", "schedule_id": "sched-1"},
            (datetime(2026, 1, 1, tzinfo=timezone.utc),
             datetime(2026, 1, 2, tzinfo=timezone.utc)),
        )

        assert signals[0]["completed_at"] is None
        assert signals[0]["analysis_completed_at"] == analysis_done

    @pytest.mark.asyncio
    async def test_schedule_mode_retains_pre_activation_scans_but_tracks_matches(self, mock_db):
        """Pre-activation scans are RETAINED (fresh capital starts flat), while the
        match result is still computed so matched scans get live-clock timing anchors.

        Previously the loader dropped 'scan-before-dad' because its snapshot config did
        not contain the submitted selector. That made results non-monotonic. Now every
        scan in the window is simulated; the filter metadata reports zero scans dropped
        but still records which scans matched (matched_scan_count) for timing fidelity.
        """
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        old_time = datetime(2026, 6, 4, 19, 58, tzinfo=timezone.utc)
        dad_time = datetime(2026, 6, 4, 23, 21, tzinfo=timezone.utc)
        trend_time = datetime(2026, 6, 5, 2, 21, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-before-dad",
                    "started_at": datetime(2026, 6, 4, 18, 43, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 18, "max_trades": 3}]},
                },
                {
                    "scan_id": "scan-with-dad",
                    "started_at": datetime(2026, 6, 4, 21, 47, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 20, "max_trades": 3}]},
                },
                {
                    "scan_id": "scan-with-trend-default",
                    "started_at": datetime(2026, 6, 5, 0, 47, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{
                        "capital_pct": 20, "max_trades": 3, "strategy_cohort": "trend",
                    }]},
                },
            ],
            [
                {"id": 1, "ticker": "OLDUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": old_time, "scan_id": "scan-before-dad",
                 "signal_source": "structured", "analysis_price": None},
                {"id": 2, "ticker": "ARKMUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": dad_time, "scan_id": "scan-with-dad",
                 "signal_source": "structured", "analysis_price": None},
                {"id": 3, "ticker": "EIGENUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": trend_time, "scan_id": "scan-with-trend-default",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 20,
            "max_trades": 3,
        }

        signals = await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 4, tzinfo=timezone.utc),
             datetime(2026, 6, 5, tzinfo=timezone.utc)),
            config,
        )

        # ALL scans retained — the pre-activation scan is no longer dropped.
        assert [s["scan_id"] for s in signals] == [
            "scan-before-dad", "scan-with-dad", "scan-with-trend-default",
        ]
        assert [s["ticker"] for s in signals] == ["OLDUSDT", "ARKMUSDT", "EIGENUSDT"]
        # Nothing dropped, but matches are still tracked for timing anchors.
        assert config["_schedule_config_filter"]["filtered_scan_count"] == 0
        assert config["_schedule_config_filter"]["matched_scan_count"] == 2

    @pytest.mark.asyncio
    async def test_schedule_mode_keeps_full_window_for_hypothetical_config(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        ts = datetime(2026, 6, 4, 23, 21, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-1",
                    "started_at": datetime(2026, 6, 4, 18, 43, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 18, "max_trades": 3}]},
                }
            ],
            [
                {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": ts, "scan_id": "scan-1",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 25,
            "max_trades": 8,
        }

        signals = await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 4, tzinfo=timezone.utc),
             datetime(2026, 6, 5, tzinfo=timezone.utc)),
            config,
        )

        assert [s["scan_id"] for s in signals] == ["scan-1"]
        assert "_schedule_config_filter" not in config

    @pytest.mark.asyncio
    async def test_schedule_mode_keeps_all_scans_when_config_activates_midwindow(self, mock_db):
        """Fresh-capital schedule backtests must simulate the FULL requested window.

        REGRESSION: when the submitted config matched some scans (it went live
        mid-window), the loader used to DROP every earlier, non-matching scan and
        simulate only the matched tail. A from-scratch backtest starts flat, so the
        "don't inherit live positions from older scans" rationale does not apply —
        dropping the early scans silently discards days of signals and makes results
        non-monotonic (extending the end date can erase earlier profit). All scans in
        the window must be retained.
        """
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        pre_time = datetime(2026, 6, 4, 19, 58, tzinfo=timezone.utc)
        match1_time = datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)
        match2_time = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-pre-activation",
                    "started_at": datetime(2026, 6, 4, 18, 43, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 18, "max_trades": 3}]},
                },
                {
                    "scan_id": "scan-matched-1",
                    "started_at": datetime(2026, 6, 11, 8, 31, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 22, "max_trades": 3}]},
                },
                {
                    "scan_id": "scan-matched-2",
                    "started_at": datetime(2026, 6, 12, 0, 34, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 22, "max_trades": 3}]},
                },
            ],
            [
                {"id": 1, "ticker": "OLDUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": pre_time, "scan_id": "scan-pre-activation",
                 "signal_source": "structured", "analysis_price": None},
                {"id": 2, "ticker": "ARKMUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": match1_time, "scan_id": "scan-matched-1",
                 "signal_source": "structured", "analysis_price": None},
                {"id": 3, "ticker": "EIGENUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": match2_time, "scan_id": "scan-matched-2",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 22,
            "max_trades": 3,
        }

        signals = await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 4, tzinfo=timezone.utc),
             datetime(2026, 6, 12, tzinfo=timezone.utc)),
            config,
        )

        # The pre-activation scan must NOT be dropped.
        assert [s["scan_id"] for s in signals] == [
            "scan-pre-activation", "scan-matched-1", "scan-matched-2",
        ]
        # Nothing was filtered out of the window.
        assert config["_schedule_config_filter"]["filtered_scan_count"] == 0

    @pytest.mark.asyncio
    async def test_schedule_window_extension_is_monotonic(self, mock_db):
        """Extending date_range_end must only ADD scans, never remove earlier ones.

        Models the exact user-reported bug: run A ends just before the config went
        live (no scan matches -> full window); run B extends one day past activation
        (some scans match). Run B's scan set must be a superset of run A's — extending
        the window cannot retroactively delete the early, profitable scans.
        """
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        early = datetime(2026, 6, 4, 19, 58, tzinfo=timezone.utc)
        matched = datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)

        # Run A: window ends BEFORE activation -> only the early scan exists, no match.
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-early",
                    "started_at": datetime(2026, 6, 4, 18, 43, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 18, "max_trades": 3}]},
                },
            ],
            [
                {"id": 1, "ticker": "OLDUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": early, "scan_id": "scan-early",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config_a = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 22, "max_trades": 3,
        }
        signals_a = await service._load_signals(
            config_a["scan_source"],
            (datetime(2026, 6, 4, tzinfo=timezone.utc),
             datetime(2026, 6, 11, 6, 7, tzinfo=timezone.utc)),
            config_a,
        )
        scan_ids_a = {s["scan_id"] for s in signals_a}

        # Run B: window extends PAST activation -> early scan + matched scan.
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-early",
                    "started_at": datetime(2026, 6, 4, 18, 43, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 18, "max_trades": 3}]},
                },
                {
                    "scan_id": "scan-matched",
                    "started_at": datetime(2026, 6, 11, 8, 31, tzinfo=timezone.utc),
                    "config": {"auto_trade_configs": [{"capital_pct": 22, "max_trades": 3}]},
                },
            ],
            [
                {"id": 1, "ticker": "OLDUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": early, "scan_id": "scan-early",
                 "signal_source": "structured", "analysis_price": None},
                {"id": 2, "ticker": "ARKMUSDT", "direction": "sell", "confidence": "high",
                 "score": -8, "signal_time": matched, "scan_id": "scan-matched",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config_b = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 22, "max_trades": 3,
        }
        signals_b = await service._load_signals(
            config_b["scan_source"],
            (datetime(2026, 6, 4, tzinfo=timezone.utc),
             datetime(2026, 6, 12, 6, 7, tzinfo=timezone.utc)),
            config_b,
        )
        scan_ids_b = {s["scan_id"] for s in signals_b}

        # The earlier window's scans must all survive the extension.
        assert scan_ids_a.issubset(scan_ids_b), (
            f"window extension dropped earlier scans: {scan_ids_a - scan_ids_b}"
        )
        assert "scan-early" in scan_ids_b

    @pytest.mark.asyncio
    async def test_schedule_context_loads_account_free_adaptive_history(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "adaptive_blacklist_enabled": True,
            "max_same_sector": None,
        }
        history = [{
            "symbol": "XPINUSDT",
            "strategy_kind": "trend",
            "is_win": False,
            "closed_at": datetime(2026, 6, 9, 12, tzinfo=timezone.utc),
        }]
        service._load_adaptive_blacklist_history = AsyncMock(return_value=history)

        await service._prepare_live_selection_context(
            config,
            signals=[],
            date_range=(
                datetime(2026, 6, 9, tzinfo=timezone.utc),
                datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
        )

        assert config["_adaptive_blacklist_history"] == history
        service._load_adaptive_blacklist_history.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_adaptive_history_prefers_sanitized_copy_table(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        closed_at = datetime(2026, 6, 9, 12, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(return_value=[{
            "symbol": "XPINUSDT",
            "strategy_kind": "trend",
            "is_win": False,
            "closed_at": closed_at,
        }])

        rows = await service._load_adaptive_blacklist_history(
            {"adaptive_blacklist_lookback_hours": 48},
            (
                datetime(2026, 6, 9, tzinfo=timezone.utc),
                datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
        )

        assert rows == [{
            "symbol": "XPINUSDT",
            "is_win": False,
            "closed_at": closed_at,
            "strategy_kind": "trend",
        }]
        query = mock_db.pool.fetch.call_args.args[0]
        assert "backtest_adaptive_blacklist_history" in query
        assert "account_id" not in query

    @pytest.mark.asyncio
    async def test_schedule_mode_derives_account_free_selection_times_from_config_index(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        started = datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-1",
                    "started_at": started,
                    "completed_at": completed,
                    "config": {"auto_trade_configs": [
                        {"capital_pct": 10, "max_trades": 2},
                        {"capital_pct": 20, "max_trades": 3},
                        {"capital_pct": 30, "max_trades": 4},
                    ]},
                },
            ],
            [
                {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": completed, "scan_id": "scan-1",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 20,
            "max_trades": 3,
        }

        await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 5, tzinfo=timezone.utc),
             datetime(2026, 6, 6, tzinfo=timezone.utc)),
            config,
        )

        assert config["_schedule_config_filter"]["matched_config_indices"] == {"scan-1": 1}
        assert config["_schedule_selection_time_by_scan"] == {
            "scan-1": "2026-06-05T01:00:40+00:00"
        }
        assert config["_schedule_post_scan_recheck_time_by_scan"] == {
            "scan-1": "2026-06-05T01:01:15+00:00"
        }

    @pytest.mark.asyncio
    async def test_schedule_mode_anchors_recheck_to_successful_schedule_execution_end(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        started = datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
        execution_completed = datetime(2026, 6, 5, 1, 10, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-1",
                    "started_at": started,
                    "completed_at": completed,
                    "schedule_execution_status": "completed",
                    "schedule_execution_completed_at": execution_completed,
                    "config": {"auto_trade_configs": [
                        {"capital_pct": 10, "max_trades": 2},
                        {"capital_pct": 20, "max_trades": 3},
                        {"capital_pct": 30, "max_trades": 4},
                    ]},
                },
            ],
            [
                {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": completed, "scan_id": "scan-1",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 20,
            "max_trades": 3,
        }

        await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 5, tzinfo=timezone.utc),
             datetime(2026, 6, 6, tzinfo=timezone.utc)),
            config,
        )

        assert config["_schedule_selection_time_by_scan"] == {
            "scan-1": "2026-06-05T01:00:40+00:00"
        }
        assert config["_schedule_post_scan_recheck_time_by_scan"] == {
            "scan-1": "2026-06-05T01:09:20+00:00"
        }

    @pytest.mark.asyncio
    async def test_schedule_mode_keeps_scan_completion_recheck_for_failed_execution(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        started = datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
        execution_completed = datetime(2026, 6, 5, 1, 10, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [
                {
                    "scan_id": "scan-1",
                    "started_at": started,
                    "completed_at": completed,
                    "schedule_execution_status": "failed",
                    "schedule_execution_completed_at": execution_completed,
                    "config": {"auto_trade_configs": [
                        {"capital_pct": 10, "max_trades": 2},
                        {"capital_pct": 20, "max_trades": 3},
                        {"capital_pct": 30, "max_trades": 4},
                    ]},
                },
            ],
            [
                {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": completed, "scan_id": "scan-1",
                 "signal_source": "structured", "analysis_price": None},
            ],
        ])
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "capital_pct": 20,
            "max_trades": 3,
        }

        await service._load_signals(
            config["scan_source"],
            (datetime(2026, 6, 5, tzinfo=timezone.utc),
             datetime(2026, 6, 6, tzinfo=timezone.utc)),
            config,
        )

        assert config["_schedule_post_scan_recheck_time_by_scan"] == {
            "scan-1": "2026-06-05T01:01:15+00:00"
        }


class TestLiveSelectionContext:
    @pytest.mark.asyncio
    async def test_schedule_mode_uses_submitted_config_without_account_history(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(return_value=[])
        mock_db.pool.fetchrow = AsyncMock()
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "leverage": 10,
            "direction": "straight",
            "execution_mode": "batch",
            "adaptive_blacklist_enabled": True,
            "strategy_cohort": None,
            "max_same_sector": None,
        }

        await service._prepare_live_selection_context(
            config,
            [{"ticker": "BTCUSDT", "scan_id": "scan-1"}],
            (
                datetime(2026, 6, 5, tzinfo=timezone.utc),
                datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
        )

        assert "_live_replay_account_id" not in config
        assert "_selection_time_by_scan" not in config
        assert "_live_selection_by_scan" not in config
        assert config["_adaptive_blacklist_history"] == []
        assert "_selector_config_by_scan" not in config
        mock_db.pool.fetchrow.assert_not_called()
        query = mock_db.pool.fetch.call_args.args[0]
        assert "backtest_adaptive_blacklist_history" in query
        assert "trades" not in query
        assert "debug_" not in query

    @pytest.mark.asyncio
    async def test_schedule_mode_loads_only_sector_reference_data_when_needed(self, mock_db):
        from backend.services.backtest_service import BacktestService

        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(side_effect=[
            [{"symbol": "BTCUSDT", "sector": "layer1"}],
            [],
        ])
        mock_db.pool.fetchrow = AsyncMock()
        config = {
            "scan_source": {"mode": "schedule", "schedule_id": "sched-1"},
            "leverage": 10,
            "execution_mode": "batch",
            "adaptive_blacklist_enabled": True,
            "max_same_sector": 1,
        }

        await service._prepare_live_selection_context(
            config,
            [{"ticker": "BTCUSDT", "scan_id": "scan-1"}],
            (
                datetime(2026, 6, 5, tzinfo=timezone.utc),
                datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
        )

        assert config["_sector_map"]["BTCUSDT"] == "layer1"
        assert "_selector_config_by_scan" not in config
        assert config["_adaptive_blacklist_history"] == []
        mock_db.pool.fetchrow.assert_not_called()
        queries = "\n".join(call.args[0] for call in mock_db.pool.fetch.call_args_list)
        assert "symbol_sectors" in queries
        assert "backtest_adaptive_blacklist_history" in queries
        assert "FROM scans" not in queries
        assert "trades" not in queries
        assert "debug_" not in queries
        assert "signal_performance" not in queries


