"""Tests for BacktestService orchestration — CRUD + lifecycle (Task 5.1)."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.pool = AsyncMock()
    return db


def _make_config(**overrides):
    base = {
        "starting_capital": 10000.0,
        "date_range_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "date_range_end": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "scan_source": {"mode": "date_range"},
        "simulation_interval": "5m",
        "leverage": 20,
        "capital_pct": 5.0,
        "take_profit_pct": 150.0,
        "stop_loss_pct": 100.0,
    }
    base.update(overrides)
    return base


class TestCreateBacktest:
    @pytest.mark.asyncio
    async def test_create_inserts_run_and_returns_id(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        run_id = "11111111-1111-1111-1111-111111111111"
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": run_id})

        # Patch the background launcher so create() doesn't actually run a backtest
        with patch.object(service, "_launch_background", new=AsyncMock()) as launch:
            result = await service.create_backtest(_make_config())

        assert result == run_id
        # An INSERT into backtest_runs must have happened, with status 'pending'
        insert_query = mock_db.pool.fetchrow.call_args[0][0]
        assert "INSERT INTO backtest_runs" in insert_query
        assert "pending" in insert_query.lower()  # status literal in the INSERT
        launch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_rejects_oversized_candle_estimate(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db)
        # 400 days × 288 candles/day at 5m > 105,120 cap → reject
        cfg = _make_config(
            date_range_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 5, tzinfo=timezone.utc),  # ~369 days
        )
        with pytest.raises(BacktestValidationError):
            await service.create_backtest(cfg)

    @pytest.mark.asyncio
    async def test_create_rate_limit_enforced(self, mock_db):
        from backend.services.backtest_service import (
            BacktestService, BacktestRateLimitError, _RATE_LIMIT_MAX,
        )
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "x"})
        with patch.object(service, "_launch_background", new=AsyncMock()):
            # First _RATE_LIMIT_MAX creates from the same client succeed.
            # (_launch_background is mocked so the slot isn't released by a real
            # background task — reset it each iteration to isolate the rate-limit check.)
            for _ in range(_RATE_LIMIT_MAX):
                service._active_slots = 0
                await service.create_backtest(_make_config(), client_id="1.2.3.4")
            # The next one is rejected by the rate limiter (before slot reservation)
            service._active_slots = 0
            with pytest.raises(BacktestRateLimitError):
                await service.create_backtest(_make_config(), client_id="1.2.3.4")
        # A different client is unaffected
        with patch.object(service, "_launch_background", new=AsyncMock()):
            service._active_slots = 0
            run_id = await service.create_backtest(_make_config(), client_id="9.9.9.9")
        assert run_id == "x"

    @pytest.mark.asyncio
    async def test_rate_limit_only_counts_successful_creates(self, mock_db):
        """A failed create (e.g. DB insert error) must NOT consume a rate token."""
        from backend.services.backtest_service import (
            BacktestService, BacktestRateLimitError, _RATE_LIMIT_MAX,
        )
        service = BacktestService(db=mock_db)
        # Every insert fails → create raises, no token recorded
        mock_db.pool.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        for _ in range(_RATE_LIMIT_MAX + 5):
            service._active_slots = 0
            with pytest.raises(RuntimeError):
                await service.create_backtest(_make_config(), client_id="5.5.5.5")
        # Budget untouched: a now-successful create still goes through
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "ok"})
        with patch.object(service, "_launch_background", new=AsyncMock()):
            service._active_slots = 0
            run_id = await service.create_backtest(_make_config(), client_id="5.5.5.5")
        assert run_id == "ok"


class TestGetBacktest:
    @pytest.mark.asyncio
    async def test_get_returns_run_with_downsampled_equity(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        run_id = "22222222-2222-2222-2222-222222222222"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # 5000-point equity curve → must be downsampled
        equity = [{"ts": (base + timedelta(minutes=i)).isoformat(), "equity": 10000.0 + i}
                  for i in range(5000)]
        mock_db.pool.fetchrow = AsyncMock(side_effect=[
            {"id": run_id, "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base},
            {"metrics": {"net_profit": 100.0}, "equity_curve": equity,
             "summary": {}, "warnings": []},
        ])

        result = await service.get_backtest(run_id)
        assert result["id"] == run_id
        assert result["status"] == "completed"
        # equity curve downsampled to <= ~2000 points
        assert len(result["results"]["equity_curve"]) <= 2000
        # LTTB preserves BOTH endpoints (first=10000, last=10000+4999)
        assert result["results"]["equity_curve"][0]["equity"] == 10000.0
        assert result["results"]["equity_curve"][-1]["equity"] == 10000.0 + 4999
        # metrics flow through _build_results
        assert result["results"]["metrics"]["net_profit"] == 100.0

    def test_downsample_preserves_max_drawdown_point(self):
        """The MAX-DRAWDOWN point (most-negative per-point drawdown_pct) must survive
        downsampling so the drawdown chart's visible trough matches the max_dd_pct
        metric tile. LTTB picks largest-triangle points by EQUITY and can drop a sharp
        drawdown that isn't an equity extreme.

        Critically this keys on drawdown_pct, NOT min equity: max_dd_pct is a
        peak-to-trough percentage, so the deepest %-drawdown point can sit at an
        unremarkable equity level (here: mid-way up a rising ramp) that LTTB discards,
        while the lowest-equity point is just the ramp's start (an endpoint LTTB always
        keeps). Keying the force-include on min-equity would therefore preserve a
        drawdown of ~0 and let the chart contradict the −77% tile — the exact failure
        this guard exists to prevent.
        """
        from backend.services.backtest_service import (
            BacktestService,
            _EQUITY_TARGET_POINTS,
        )
        # A high downsample ratio so LTTB aggressively drops non-extreme points.
        n = _EQUITY_TARGET_POINTS * 10
        # Smooth rising equity ramp 10000 → 110000 (so the min-equity point is the
        # START endpoint, which LTTB always keeps) with ~0 drawdown everywhere.
        curve = [{"ts": None, "equity": 10000.0 + 100000.0 * i / (n - 1), "drawdown_pct": -0.001}
                 for i in range(n)]
        # Bury the true max drawdown (−77%) at a mid-ramp index, leaving its equity ON
        # the ramp line (collinear → LTTB drops it). Its equity is NOT an extreme.
        deep_idx = 12345
        curve[deep_idx]["drawdown_pct"] = -77.0

        out = BacktestService._downsample_equity(curve)
        assert len(out) <= _EQUITY_TARGET_POINTS + 1
        # The −77% point must be force-included so the overlay trough matches the tile.
        # Under the old min-equity key it would be dropped (min equity = the kept
        # start endpoint at ~0% drawdown) and this would read ~-0.001.
        assert min(p.get("drawdown_pct") for p in out) == pytest.approx(-77.0), (
            "the deepest per-point drawdown (−77%) must survive downsampling; keying "
            "the force-include on min-equity instead of drawdown_pct loses it"
        )

    @pytest.mark.asyncio
    async def test_get_run_without_results(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        run_id = "33333333-3333-3333-3333-333333333333"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Run exists but no results row yet (e.g. still running) → results = None
        mock_db.pool.fetchrow = AsyncMock(side_effect=[
            {"id": run_id, "status": "running", "config": {}, "scan_source": {},
             "progress_pct": 40, "error_message": None, "started_at": base,
             "completed_at": None, "created_at": base},
            None,  # no backtest_results row
        ])
        result = await service.get_backtest(run_id)
        assert result["status"] == "running"
        assert result["results"] is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value=None)
        result = await service.get_backtest("00000000-0000-0000-0000-000000000000")
        assert result is None


class TestListBacktests:
    @pytest.mark.asyncio
    async def test_list_returns_runs(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": "a", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base},
        ])
        result = await service.list_backtests({})
        assert len(result) == 1
        assert result[0]["id"] == "a"

    @pytest.mark.asyncio
    async def test_list_filters_by_status(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(return_value=[])
        await service.list_backtests({"status": "running"})
        query = mock_db.pool.fetch.call_args[0][0]
        # Must add a WHERE status filter (not just have 'status' in the SELECT list)
        assert "where status = $1" in query.lower()
        # And bind the status value as a parameter
        assert mock_db.pool.fetch.call_args[0][1] == "running"

    @pytest.mark.asyncio
    async def test_list_no_filter_has_no_where(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetch = AsyncMock(return_value=[])
        await service.list_backtests({})
        query = mock_db.pool.fetch.call_args[0][0]
        assert "where status" not in query.lower()


class TestMarkStatus:
    @pytest.mark.asyncio
    async def test_guarded_update_skips_cancelled(self, mock_db):
        """guard_cancel=True (default) must add the AND status<>'cancelled' clause
        so a running/progress transition can't clobber a user cancel."""
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.execute = AsyncMock()
        await service._mark_status("r1", "running", started=True)  # default guard
        query = mock_db.pool.execute.call_args[0][0]
        assert "status <> 'cancelled'" in query

    @pytest.mark.asyncio
    async def test_unguarded_update_no_cancel_clause(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.execute = AsyncMock()
        await service._mark_status("r1", "cancelled", completed=True, guard_cancel=False)
        query = mock_db.pool.execute.call_args[0][0]
        assert "status <> 'cancelled'" not in query
        # status param is 'cancelled'
        assert mock_db.pool.execute.call_args[0][2] == "cancelled"


class TestCancelBacktest:
    @pytest.mark.asyncio
    async def test_cancel_sets_event_and_returns_true(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        run_id = "33333333-3333-3333-3333-333333333333"
        import threading
        ev = threading.Event()
        service._cancel_events[run_id] = ev
        mock_db.pool.fetchrow = AsyncMock(return_value={"status": "running"})
        mock_db.pool.execute = AsyncMock()

        result = await service.cancel_backtest(run_id)
        assert result is True
        assert ev.is_set()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value=None)
        result = await service.cancel_backtest("00000000-0000-0000-0000-000000000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_completed_raises_conflict(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestConflictError
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"status": "completed"})
        with pytest.raises(BacktestConflictError):
            await service.cancel_backtest("66666666-6666-6666-6666-666666666666")

    @pytest.mark.asyncio
    async def test_cancel_pending_sets_registered_event(self, mock_db):
        from backend.services.backtest_service import BacktestService
        import threading
        service = BacktestService(db=mock_db)
        run_id = "77777777-7777-7777-7777-777777777777"
        ev = threading.Event()
        service._cancel_events[run_id] = ev
        mock_db.pool.fetchrow = AsyncMock(return_value={"status": "pending"})
        mock_db.pool.execute = AsyncMock()
        result = await service.cancel_backtest(run_id)
        assert result is True
        assert ev.is_set()


class TestDeleteBacktest:
    @pytest.mark.asyncio
    async def test_delete_completed_returns_true(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        run_id = "44444444-4444-4444-4444-444444444444"
        mock_db.pool.fetchrow = AsyncMock(return_value={"status": "completed"})
        mock_db.pool.execute = AsyncMock()
        result = await service.delete_backtest(run_id)
        assert result is True
        # DELETE issued
        assert any("DELETE" in str(c[0][0]).upper() for c in mock_db.pool.execute.call_args_list)

    @pytest.mark.asyncio
    async def test_delete_running_rejected(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestConflictError
        service = BacktestService(db=mock_db)
        run_id = "55555555-5555-5555-5555-555555555555"
        mock_db.pool.fetchrow = AsyncMock(return_value={"status": "running"})
        with pytest.raises(BacktestConflictError):
            await service.delete_backtest(run_id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value=None)
        result = await service.delete_backtest("00000000-0000-0000-0000-000000000000")
        assert result is False


class TestCompareBacktests:
    @pytest.mark.asyncio
    async def test_compare_valid_runs(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": "a", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base,
             "metrics": {"net_profit": 100.0}, "equity_curve": [], "summary": {}, "warnings": []},
            {"id": "b", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base,
             "metrics": {"net_profit": 200.0}, "equity_curve": [], "summary": {}, "warnings": []},
        ])
        result = await service.compare_backtests(["a", "b"])
        assert "runs" in result
        assert len(result["runs"]) == 2
        # The metrics must actually flow through _build_results (not just a shell dict)
        assert result["runs"][0]["id"] == "a"
        assert result["runs"][0]["results"]["metrics"]["net_profit"] == 100.0
        assert result["runs"][1]["results"]["metrics"]["net_profit"] == 200.0

    @pytest.mark.asyncio
    async def test_compare_too_few_ids_rejected(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db)
        with pytest.raises(BacktestValidationError):
            await service.compare_backtests(["only-one"])

    @pytest.mark.asyncio
    async def test_compare_too_many_ids_rejected(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db)
        with pytest.raises(BacktestValidationError):
            await service.compare_backtests(["a", "b", "c", "d", "e"])

    @pytest.mark.asyncio
    async def test_compare_incomplete_run_rejected(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": "a", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base,
             "metrics": {}, "equity_curve": [], "summary": {}, "warnings": []},
            {"id": "b", "status": "running", "config": {}, "scan_source": {},
             "progress_pct": 50, "error_message": None, "started_at": base,
             "completed_at": None, "created_at": base,
             "metrics": None, "equity_curve": None, "summary": None, "warnings": None},
        ])
        with pytest.raises(BacktestValidationError):
            await service.compare_backtests(["a", "b"])

    @pytest.mark.asyncio
    async def test_compare_missing_run_raises_not_found(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestNotFoundError
        service = BacktestService(db=mock_db)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Only "a" found; "b" missing → NotFound (maps to 404), not Validation (422)
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": "a", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": base,
             "completed_at": base, "created_at": base,
             "metrics": {}, "equity_curve": [], "summary": {}, "warnings": []},
        ])
        with pytest.raises(BacktestNotFoundError):
            await service.compare_backtests(["a", "b"])


class TestBuildFineKlines:
    """_build_fine_klines fetches 1m only for actual trades' entry+exit bars, via the
    direct Bybit fetch (bypassing the coverage table), never persisting (no store)."""

    def _svc_with_cache(self, mock_db, one_minute_candles):
        from backend.services.backtest_service import BacktestService
        cache = MagicMock()
        cache._fetch_klines_from_bybit = AsyncMock(return_value=one_minute_candles)
        cache.store_klines = AsyncMock()
        cache.get_klines = AsyncMock()
        return BacktestService(db=mock_db, kline_cache=cache), cache

    @pytest.mark.asyncio
    async def test_no_trades_returns_empty(self, mock_db):
        svc, cache = self._svc_with_cache(mock_db, [])
        out = await svc._build_fine_klines(_make_config(), [])
        assert out == {}
        cache._fetch_klines_from_bybit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetches_and_buckets_by_bar_epoch(self, mock_db):
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        entry_bar = base + timedelta(minutes=5)   # 12:05
        exit_bar = base + timedelta(minutes=20)    # 12:20
        # 1m candles spanning both bars + neighbours
        ones = []
        for m in range(-5, 35):
            ones.append({"open_time": base + timedelta(minutes=5 + m), "open": 1.0,
                         "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
        svc, cache = self._svc_with_cache(mock_db, ones)
        trades = [{"symbol": "BTCUSDT", "entry_time": entry_bar + timedelta(seconds=30),
                   "exit_time": exit_bar + timedelta(seconds=10)}]
        out = await svc._build_fine_klines(_make_config(), trades)
        assert "BTCUSDT" in out
        # entry bar (12:05) bucket present, keyed by its epoch
        assert int(entry_bar.timestamp()) in out["BTCUSDT"]
        # the entry bar's FORWARD neighbour (12:10) is also fetched — a non-bar-aligned
        # signal fills at the NEXT bar's open, so the real entry bar may be the next one.
        assert int((entry_bar + timedelta(minutes=5)).timestamp()) in out["BTCUSDT"]
        # exit bar (12:20) bucket present
        assert int(exit_bar.timestamp()) in out["BTCUSDT"]
        # each bucket holds 5 one-minute candles, sorted
        eb = out["BTCUSDT"][int(entry_bar.timestamp())]
        assert len(eb) == 5
        assert eb == sorted(eb, key=lambda c: c["open_time"])
        # NEVER persists 1m (would re-poison the coverage table)
        cache.store_klines.assert_not_awaited()
        # used the direct fetch path, not get_klines/ensure_coverage
        cache._fetch_klines_from_bybit.assert_awaited()
        cache.get_klines.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_failure_omits_symbol(self, mock_db):
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        svc, cache = self._svc_with_cache(mock_db, [])
        cache._fetch_klines_from_bybit = AsyncMock(side_effect=RuntimeError("net"))
        trades = [{"symbol": "BTCUSDT", "entry_time": base, "exit_time": base + timedelta(minutes=20)}]
        out = await svc._build_fine_klines(_make_config(), trades)
        assert out == {}  # symbol omitted, fail-soft

    @pytest.mark.asyncio
    async def test_no_cache_returns_empty(self, mock_db):
        from backend.services.backtest_service import BacktestService
        svc = BacktestService(db=mock_db, kline_cache=None)
        out = await svc._build_fine_klines(_make_config(), [{"symbol": "X",
            "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "exit_time": None}])
        assert out == {}
