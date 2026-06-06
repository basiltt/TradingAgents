"""Tests for BacktestService background execution (Task 5.2): cancel, timeout,
concurrency, memory limits, startup recovery, results persistence, paginated trades."""

import pytest
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.pool = AsyncMock()
    return db


def _wire_transaction(mock_db):
    """Wire pool.acquire() -> conn (async ctx mgr) -> conn.transaction() (async ctx mgr).

    Returns the mock connection so callers can assert on conn.execute/executemany.
    """
    conn = AsyncMock()
    # conn.transaction() returns an async context manager
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    # pool.acquire() returns an async context manager yielding conn
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_db.pool.acquire = MagicMock(return_value=acquire_cm)
    return conn


def _make_config(**overrides):
    base = {
        "starting_capital": 10000.0,
        "date_range_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "date_range_end": datetime(2026, 1, 3, tzinfo=timezone.utc),
        "scan_source": {"mode": "date_range"},
        "simulation_interval": "5m",
        "leverage": 20, "capital_pct": 5.0,
        "take_profit_pct": 150.0, "stop_loss_pct": 100.0,
    }
    base.update(overrides)
    return base


def _marked_status(mock_db, status: str) -> bool:
    """True if any pool.execute call set backtest_runs.status to `status`.

    _mark_status issues UPDATE backtest_runs SET status = $2 ... with positional
    args (query, run_id, status, ...). Checking the status PARAMETER (args[2])
    rather than substring-matching the joined repr avoids false positives from a
    `WHERE status <> 'cancelled'` guard clause in an unrelated update.
    """
    for c in mock_db.pool.execute.call_args_list:
        args = c.args
        if args and "UPDATE backtest_runs SET status" in str(args[0]):
            if len(args) >= 3 and args[2] == status:
                return True
    return False


class TestMemoryLimit:
    @pytest.mark.asyncio
    async def test_memory_reject_large_range(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db)
        # 400 days at 5m → ~115k candles > 105,120 cap
        cfg = _make_config(
            date_range_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 2, 5, tzinfo=timezone.utc),
        )
        with pytest.raises(BacktestValidationError):
            await service.create_backtest(cfg)

    @pytest.mark.asyncio
    async def test_memory_allows_reasonable_range(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "x"})
        with patch.object(service, "_launch_background", new=AsyncMock()):
            # 30 days at 5m → ~8640 candles, well under cap
            cfg = _make_config(
                date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            )
            run_id = await service.create_backtest(cfg)
        assert run_id == "x"

    def test_estimate_candles_by_interval(self):
        from backend.services.backtest_service import BacktestService
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 11, tzinfo=timezone.utc)  # 10 days
        # 5m: 10 × 288 = 2880; 1h: 10 × 24 = 240; 4h: 10 × 6 = 60
        assert BacktestService._estimate_candles(
            {"date_range_start": start, "date_range_end": end, "simulation_interval": "5m"}) == 2880
        assert BacktestService._estimate_candles(
            {"date_range_start": start, "date_range_end": end, "simulation_interval": "1h"}) == 240
        assert BacktestService._estimate_candles(
            {"date_range_start": start, "date_range_end": end, "simulation_interval": "4h"}) == 60

    @pytest.mark.asyncio
    async def test_memory_boundary_exactly_365_days_accepted(self, mock_db):
        """Exactly _MAX_CANDLES (365d × 288 = 105,120) must be ACCEPTED (> not >=)."""
        from backend.services.backtest_service import BacktestService, _MAX_CANDLES
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "ok"})
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cfg = _make_config(date_range_start=start, date_range_end=start + timedelta(days=365))
        # 365 days × 288 = 105,120 = _MAX_CANDLES exactly → must NOT reject (strict >)
        assert service._estimate_candles(cfg) == _MAX_CANDLES
        with patch.object(service, "_launch_background", new=AsyncMock()):
            run_id = await service.create_backtest(cfg)
        assert run_id == "ok"


class TestStartupRecovery:
    @pytest.mark.asyncio
    async def test_recover_marks_stale_running_as_failed(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.execute = AsyncMock(return_value="UPDATE 3")
        count = await service.recover_stale_runs()
        assert count == 3
        query = mock_db.pool.execute.call_args[0][0]
        assert "failed" in query.lower()
        assert "running" in query.lower() and "pending" in query.lower()

    @pytest.mark.asyncio
    async def test_recover_zero_when_none_stale(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.execute = AsyncMock(return_value="UPDATE 0")
        count = await service.recover_stale_runs()
        assert count == 0


class TestExecution:
    @pytest.mark.asyncio
    async def test_successful_run_persists_and_completes(self, mock_db):
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        mock_db.pool.executemany = AsyncMock()
        conn = _wire_transaction(mock_db)

        sim_result = SimulationResult(
            trades=[{"symbol": "BTCUSDT", "side": "Buy", "entry_price": 50000.0,
                     "exit_price": 51000.0, "qty": 0.1, "leverage": 20,
                     "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "exit_time": datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                     "pnl": 100.0, "pnl_pct": 2.0, "fees_paid": 2.0,
                     "close_reason": "tp"}],
            equity_curve=[{"ts": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(), "equity": 10100.0}],
            metrics={"net_profit": 100.0},
            warnings=[],
            filter_stats={"signals_total": 1},
        )

        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[
            {"ticker": "BTCUSDT", "signal_time": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        ])):
            with patch.object(service, "_load_klines", new=AsyncMock(return_value={
                "BTCUSDT": [{"open_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "close": 50000.0}]
            })):
                with patch("backend.services.backtest_engine.BacktestEngine.run", return_value=sim_result):
                    # Reserve a slot up front so the finally's release is OBSERVABLE
                    # (1 -> 0). Without this, 0 -> 0 can't distinguish release from leak.
                    service._active_slots = 1
                    await service._execute_backtest("run-1", _make_config())

        # Status: 'running' via pool.execute; 'completed' now flips inside the
        # persist transaction (conn), so the invariant results⟺completed is atomic.
        running = " ".join(str(c[0]) for c in mock_db.pool.execute.call_args_list)
        assert "running" in running
        conn_calls = " ".join(str(c[0][0]) for c in conn.execute.call_args_list)
        assert "backtest_results" in conn_calls
        assert "completed" in conn_calls  # status flip is in the same transaction
        conn.executemany.assert_awaited()
        # Persisted trade record has Decimal-converted numerics (asyncpg NUMERIC)
        from decimal import Decimal
        records = conn.executemany.call_args[0][1]
        assert isinstance(records[0][3], Decimal)  # entry_price
        assert records[0][3] == Decimal("50000.0")
        # slot released after completion (1 -> 0)
        assert service._active_slots == 0

    @pytest.mark.asyncio
    async def test_max_same_sector_emits_not_enforced_warning(self, mock_db):
        """max_same_sector needs the IO-bound sector service the pure engine can't
        call, so the backtest does not enforce it. When the user sets it, the
        service must append a 'max_same_sector_not_enforced' warning so results
        aren't silently misleading (live trading DOES enforce the limit)."""
        from unittest.mock import patch, AsyncMock
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        _wire_transaction(mock_db)

        captured = {}

        async def fake_persist(run_id, result):
            captured["warnings"] = list(result.warnings or [])

        sim_result = SimulationResult(
            trades=[], equity_curve=[{"ts": None, "equity": 10000.0}],
            metrics={"net_profit": 0.0}, warnings=[], filter_stats={},
        )
        cfg = _make_config(max_same_sector=2)
        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[
            {"ticker": "BTCUSDT", "signal_time": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        ])):
            with patch.object(service, "_load_klines", new=AsyncMock(return_value={
                "BTCUSDT": [{"open_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "close": 50000.0}]
            })):
                with patch("backend.services.backtest_engine.BacktestEngine.run", return_value=sim_result):
                    with patch.object(service, "_persist_results", side_effect=fake_persist):
                        with patch.object(service, "_attach_buy_hold", new=AsyncMock()):
                            await service._execute_backtest("run-1", cfg)

        assert "max_same_sector_not_enforced" in captured["warnings"]

    @pytest.mark.asyncio
    async def test_persist_json_safes_equity_curve(self, mock_db):
        """_persist_results must route the equity curve through _json_safe: raw
        datetimes become ISO-8601 with a 'T' separator (Safari-parseable) and any
        non-finite equity becomes None (so a NaN/Inf can't emit invalid JSON that
        asyncpg would reject). Guards the engine→persistence serialization."""
        import json
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        conn = _wire_transaction(mock_db)

        sim_result = SimulationResult(
            trades=[],
            equity_curve=[
                {"ts": datetime(2026, 1, 1, tzinfo=timezone.utc), "equity": 10000.0, "drawdown_pct": 0.0},
                {"ts": datetime(2026, 1, 2, tzinfo=timezone.utc), "equity": float("inf"), "drawdown_pct": -5.0},
            ],
            metrics={"net_profit": 0.0},
            warnings=[],
            filter_stats={},
        )
        await service._persist_results("run-1", sim_result)

        # The results INSERT positional args: (query, run_id, metrics_json,
        # equity_json, summary_json, warnings_json) → equity_curve is index 3.
        results_call = next(
            c for c in conn.execute.call_args_list if "backtest_results" in str(c[0][0])
        )
        equity_json = results_call[0][3]
        parsed = json.loads(equity_json)
        # Datetime serialized with the 'T' separator (not "2026-01-01 00:00:00").
        assert parsed[0]["ts"] == "2026-01-01T00:00:00+00:00"
        # Non-finite equity coerced to None (no literal Infinity in the JSON).
        assert parsed[1]["equity"] is None
        assert "Infinity" not in equity_json

    @pytest.mark.asyncio
    async def test_failed_run_records_error(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()

        with patch.object(service, "_load_signals", new=AsyncMock(side_effect=RuntimeError("boom"))):
            await service._execute_backtest("run-err", _make_config())

        # status param must be 'failed' (not just the literal appearing somewhere)
        assert _marked_status(mock_db, "failed")
        # The stored error_message is sanitized (no raw "boom") but names the phase.
        # Find the failed-status update and inspect its error param.
        failed_calls = [c for c in mock_db.pool.execute.call_args_list
                        if c.args and "UPDATE backtest_runs SET status" in str(c.args[0])
                        and len(c.args) >= 3 and c.args[2] == "failed"]
        assert failed_calls
        all_params = " ".join(str(c.args) for c in failed_calls)
        assert "simulation" in all_params  # phase recorded
        assert "boom" not in all_params    # raw exception text NOT leaked to the user

    @pytest.mark.asyncio
    async def test_cancelled_before_slot_marks_cancelled(self, mock_db):
        from backend.services.backtest_service import BacktestService
        from backend.services.backtest_engine import BacktestCancelled
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()

        # Pre-set the cancel event so the run is cancelled before acquiring a slot
        with patch.object(service, "_load_signals", new=AsyncMock(side_effect=BacktestCancelled())):
            await service._execute_backtest("run-cancel", _make_config())

        # Assert the STATUS PARAM was 'cancelled' (not just the literal appearing in
        # a `WHERE status <> 'cancelled'` guard clause of some other update).
        assert _marked_status(mock_db, "cancelled")

    @pytest.mark.asyncio
    async def test_timeout_marks_failed_with_timeout_message(self, mock_db):
        """When the timeout fires (timed_out set) and the engine raises
        BacktestCancelled, the run is marked FAILED with the time-limit message
        (distinct from a user cancel which marks 'cancelled')."""
        from backend.services.backtest_service import BacktestService
        from backend.services.backtest_engine import BacktestCancelled
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()

        # Patch Timer so it fires its callback IMMEDIATELY and synchronously (the
        # callback sets timed_out + cancel_event). The engine then raises
        # BacktestCancelled, and the handler must see timed_out → 'failed'+timeout.
        class _InstantTimer:
            def __init__(self, delay, fn):
                self._fn = fn
            def start(self):
                self._fn()  # fire now: sets timed_out and cancel_event
            def cancel(self):
                pass
            daemon = True

        def _engine_run(config, signals, klines, cancel_event, on_progress, instrument_info=None):
            raise BacktestCancelled()  # cancel_event already set by the instant timer

        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[])):
            with patch("backend.services.backtest_service.threading.Timer", _InstantTimer):
                with patch("backend.services.backtest_engine.BacktestEngine.run", side_effect=_engine_run):
                    await service._execute_backtest("run-timeout", _make_config())

        assert _marked_status(mock_db, "failed")
        failed = [c for c in mock_db.pool.execute.call_args_list
                  if c.args and "UPDATE backtest_runs SET status" in str(c.args[0])
                  and len(c.args) >= 3 and c.args[2] == "failed"]
        joined = " ".join(str(c.args) for c in failed)
        assert "time limit" in joined.lower()

    @pytest.mark.asyncio
    async def test_cancel_before_event_registered_honored(self, mock_db):
        from backend.services.backtest_service import BacktestService
        import threading
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        # Simulate create_backtest having registered + cancel having fired in the gap
        ev = threading.Event()
        ev.set()
        service._cancel_events["run-x"] = ev

        with patch.object(service, "_load_signals", new=AsyncMock()) as load:
            await service._execute_backtest("run-x", _make_config())
        # Short-circuited: signals never loaded, status param set to cancelled
        load.assert_not_awaited()
        assert _marked_status(mock_db, "cancelled")
        assert service._active_slots == 0  # slot released

    @pytest.mark.asyncio
    async def test_persist_failure_after_engine_recorded_as_persistence_error(self, mock_db):
        """If persistence fails AFTER the engine succeeds, the error message must
        say 'persistence' (not masquerade as a simulation failure)."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        # pool.acquire raises → persist fails
        mock_db.pool.acquire = MagicMock(side_effect=RuntimeError("db gone"))

        sim_result = SimulationResult(
            trades=[], equity_curve=[], metrics={"net_profit": 0.0},
            warnings=[], filter_stats={},
        )
        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[])):
            with patch("backend.services.backtest_engine.BacktestEngine.run", return_value=sim_result):
                await service._execute_backtest("run-p", _make_config())

        # The failure error must indicate the persistence phase
        calls = " ".join(str(c) for c in mock_db.pool.execute.call_args_list)
        assert "failed" in calls
        assert "persistence" in calls

    @pytest.mark.asyncio
    async def test_late_cancel_after_engine_done_completes_not_cancelled(self, mock_db):
        """A cancel that lands after the engine finished must NOT leave a
        cancelled-with-results run — completion flips status inside the persist
        transaction (atomic, no cancel guard), so results⟺completed holds."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        conn = _wire_transaction(mock_db)
        sim_result = SimulationResult(trades=[], equity_curve=[], metrics={},
                                      warnings=[], filter_stats={})
        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[])):
            with patch("backend.services.backtest_engine.BacktestEngine.run", return_value=sim_result):
                await service._execute_backtest("run-late", _make_config())
        # The completed UPDATE happens inside the transaction (conn) and must NOT
        # carry the cancel guard — completion wins over a late cancel.
        completed_calls = [c for c in conn.execute.call_args_list
                           if "completed" in str(c[0][0])]
        assert completed_calls, "expected a completed-status update in the transaction"
        assert "status <> 'cancelled'" not in str(completed_calls[-1][0][0])

    @pytest.mark.asyncio
    async def test_persist_retried_once_on_transient_failure(self, mock_db):
        """A transient persist failure is retried once (idempotent) before failing."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.execute = AsyncMock()
        # First _persist_results raises, second succeeds
        call_count = {"n": 0}

        async def flaky_persist(run_id, result):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient blip")
            # second call succeeds (no-op)

        sim_result = SimulationResult(trades=[], equity_curve=[], metrics={},
                                      warnings=[], filter_stats={})
        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[])):
            with patch.object(service, "_persist_results", side_effect=flaky_persist):
                with patch("backend.services.backtest_engine.BacktestEngine.run", return_value=sim_result):
                    await service._execute_backtest("run-retry", _make_config())
        # Persist attempted twice; the second succeeds so the run is NOT marked failed.
        assert call_count["n"] == 2
        calls = " ".join(str(c) for c in mock_db.pool.execute.call_args_list)
        assert "failed" not in calls  # the retry succeeded → no failure mark
        assert service._active_slots == 0  # slot released


class TestBuyHoldAndCoverage:
    """Phase 4 carry-forward: buy&hold/excess_return; Task 5.3 kline coverage guard."""

    @pytest.mark.asyncio
    async def test_attach_buy_hold_adds_excess_return(self, mock_db):
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        kc = MagicMock()
        # BTC 50000 -> 55000 = +10% over the window
        kc.get_klines = AsyncMock(return_value=[
            {"open_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "close": 50000.0},
            {"open_time": datetime(2026, 1, 2, tzinfo=timezone.utc), "close": 55000.0},
        ])
        service = BacktestService(db=mock_db, kline_cache=kc)
        result = SimulationResult(
            trades=[], equity_curve=[],
            metrics={"net_profit_pct": 25.0},  # strategy +25%
            warnings=[], filter_stats={},
        )
        await service._attach_buy_hold(_make_config(), result)
        assert abs(result.metrics["buy_hold_return_pct"] - 10.0) < 0.01
        # excess = strategy 25% - buy&hold 10% = 15%
        assert abs(result.metrics["excess_return"] - 15.0) < 0.01

    @pytest.mark.asyncio
    async def test_attach_buy_hold_no_cache_yields_none(self, mock_db):
        """No benchmark data → fields are None (N/A), NOT a misleading flat 0%."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db, kline_cache=None)
        result = SimulationResult(trades=[], equity_curve=[],
                                  metrics={"net_profit_pct": 5.0}, warnings=[], filter_stats={})
        await service._attach_buy_hold(_make_config(), result)
        assert result.metrics["buy_hold_return_pct"] is None
        assert result.metrics["buy_hold_final_value"] is None
        assert result.metrics["excess_return"] is None

    @pytest.mark.asyncio
    async def test_attach_buy_hold_fetch_error_is_best_effort(self, mock_db):
        """A BTC kline fetch error must NOT fail the backtest — fields go None."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        kc = MagicMock()
        kc.get_klines = AsyncMock(side_effect=RuntimeError("db hiccup"))
        service = BacktestService(db=mock_db, kline_cache=kc)
        result = SimulationResult(trades=[], equity_curve=[],
                                  metrics={"net_profit_pct": 5.0}, warnings=[], filter_stats={})
        # Must not raise
        await service._attach_buy_hold(_make_config(), result)
        assert result.metrics["buy_hold_return_pct"] is None
        assert result.metrics["excess_return"] is None

    def test_coverage_guard_rejects_when_over_20pct_missing(self):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        signals = [{"ticker": s} for s in ["A", "B", "C", "D", "E"]]
        # 2/5 = 40% missing > 20% → reject
        klines = {"A": [{"x": 1}], "B": [{"x": 1}], "C": [{"x": 1}], "D": [], "E": []}
        with pytest.raises(BacktestValidationError):
            BacktestService._check_kline_coverage(signals, klines)

    def test_coverage_guard_passes_when_under_20pct_missing(self):
        from backend.services.backtest_service import BacktestService
        signals = [{"ticker": s} for s in ["A", "B", "C", "D", "E"]]
        # 1/5 = 20% missing, NOT > 20% → ok (boundary)
        klines = {"A": [{"x": 1}], "B": [{"x": 1}], "C": [{"x": 1}], "D": [{"x": 1}], "E": []}
        BacktestService._check_kline_coverage(signals, klines)  # no raise

    def test_coverage_guard_empty_signals_noop(self):
        from backend.services.backtest_service import BacktestService
        BacktestService._check_kline_coverage([], {})  # no raise

    def test_total_kline_budget_rejects_many_symbols_long_range(self):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        # 200 symbols × 365 days × 288 candles/day ≈ 21M candles > 3M budget
        config = {
            "date_range_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "date_range_end": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "simulation_interval": "5m",
        }
        signals = [{"ticker": f"SYM{i}"} for i in range(200)]
        with pytest.raises(BacktestValidationError):
            BacktestService._check_total_kline_budget(config, signals)

    def test_total_kline_budget_passes_reasonable(self):
        from backend.services.backtest_service import BacktestService
        # 5 symbols × 30 days × 288 = ~43k candles, well under 3M
        config = {
            "date_range_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "date_range_end": datetime(2026, 1, 31, tzinfo=timezone.utc),
            "simulation_interval": "5m",
        }
        signals = [{"ticker": f"SYM{i}"} for i in range(5)]
        BacktestService._check_total_kline_budget(config, signals)  # no raise

    @pytest.mark.asyncio
    async def test_coverage_failure_surfaces_clean_message(self, mock_db):
        """A coverage BacktestValidationError must be surfaced as its clean message,
        not mangled into a 'simulation error: ...' string."""
        from backend.services.backtest_service import BacktestService
        kc = MagicMock()
        # Signal for BTCUSDT but kline returns empty → 100% missing → coverage fails
        kc.get_klines = AsyncMock(return_value=[])
        service = BacktestService(db=mock_db, kline_cache=kc)
        mock_db.pool.execute = AsyncMock()
        with patch.object(service, "_load_signals", new=AsyncMock(return_value=[
            {"ticker": "BTCUSDT", "signal_time": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        ])):
            await service._execute_backtest("run-cov", _make_config())
        calls = " ".join(str(c) for c in mock_db.pool.execute.call_args_list)
        assert "failed" in calls
        assert "Insufficient kline data" in calls
        # NOT mangled with the generic prefix
        assert "simulation error" not in calls


class TestPerTradeStripping:
    @pytest.mark.asyncio
    async def test_per_trade_stripped_from_metrics_jsonb(self, mock_db):
        """per_trade must NOT be stored in the metrics JSONB (it lives in backtest_trades)."""
        import json
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db)
        conn = _wire_transaction(mock_db)
        result = SimulationResult(
            trades=[], equity_curve=[],
            metrics={"net_profit": 100.0, "per_trade": [{"index": 0, "pnl": 100.0}]},
            warnings=[], filter_stats={},
        )
        await service._persist_results("run-1", result)
        # The metrics JSON written to backtest_results must NOT contain per_trade
        results_call = next(c for c in conn.execute.call_args_list
                            if "backtest_results" in str(c[0][0]))
        metrics_json = results_call[0][2]  # $2 = metrics
        assert "per_trade" not in metrics_json
        assert "net_profit" in metrics_json


class TestSlotManagement:
    @pytest.mark.asyncio
    async def test_slot_counter_starts_at_zero(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        assert service._active_slots == 0
        assert service.has_free_slot() is True

    @pytest.mark.asyncio
    async def test_has_free_slot_false_when_full(self, mock_db):
        from backend.services.backtest_service import BacktestService, _MAX_CONCURRENT
        service = BacktestService(db=mock_db, kline_cache=None)
        service._active_slots = _MAX_CONCURRENT
        assert service.has_free_slot() is False
        service._active_slots = _MAX_CONCURRENT - 1
        assert service.has_free_slot() is True

    @pytest.mark.asyncio
    async def test_create_raises_busy_when_full(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestBusyError, _MAX_CONCURRENT
        service = BacktestService(db=mock_db, kline_cache=None)
        service._active_slots = _MAX_CONCURRENT  # all slots taken
        with pytest.raises(BacktestBusyError):
            await service.create_backtest(_make_config())

    @pytest.mark.asyncio
    async def test_create_reserves_and_releases_slot(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "x"})
        with patch.object(service, "_launch_background", new=AsyncMock()):
            await service.create_backtest(_make_config())
        # Slot reserved (not yet released — background task owns it now)
        assert service._active_slots == 1

    @pytest.mark.asyncio
    async def test_create_releases_slot_on_insert_failure(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        with pytest.raises(RuntimeError):
            await service.create_backtest(_make_config())
        # Slot released since the background task never took ownership
        assert service._active_slots == 0

    @pytest.mark.asyncio
    async def test_create_keeps_slot_and_token_after_successful_launch(self, mock_db):
        """After a successful launch the background task owns the slot (stays at 1,
        released later by its own finally, NOT by create), and the rate-limit token is
        consumed — a successful create counts against the client's window."""
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.fetchrow = AsyncMock(return_value={"id": "x"})
        with patch.object(service, "_launch_background", new=AsyncMock()):
            await service.create_backtest(_make_config(), client_id="c1")
        # Slot still reserved (1) — the task's finally will release it later, NOT create.
        assert service._active_slots == 1
        # The successful create consumed exactly one rate-limit token.
        assert len(service._create_history.get("c1", [])) == 1

    @pytest.mark.asyncio
    async def test_create_refunds_rate_token_on_insert_failure(self, mock_db):
        """A create that fails before launch (DB error) must refund its rate-limit
        token so the rejected attempt doesn't count against the client's window."""
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        mock_db.pool.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        with pytest.raises(RuntimeError):
            await service.create_backtest(_make_config(), client_id="c1")
        # Slot released AND token refunded — a failed attempt burns neither.
        assert service._active_slots == 0
        assert len(service._create_history.get("c1", [])) == 0

    @pytest.mark.asyncio
    async def test_rate_limit_reserve_is_atomic_no_overshoot(self, mock_db):
        """The rate-limit token is reserved+consumed SYNCHRONOUSLY (no await between
        the window check and the record), so concurrent creates from one client can't
        both pass a stale check and over-admit. Regression guard for the TOCTOU where
        the window was checked before the INSERT await but recorded only after it.

        Tested at the reserve primitive (slots are a separate, smaller cap that would
        otherwise mask the rate limit): exactly _RATE_LIMIT_MAX reservations succeed,
        the next is rejected, and a refund frees exactly one slot in the window.
        """
        from backend.services.backtest_service import (
            BacktestService, _RATE_LIMIT_MAX, BacktestRateLimitError,
        )
        service = BacktestService(db=mock_db, kline_cache=None)

        tokens = []
        for _ in range(_RATE_LIMIT_MAX):
            tokens.append(service._reserve_create_token("burst"))
        assert len(service._create_history["burst"]) == _RATE_LIMIT_MAX
        # The (_RATE_LIMIT_MAX + 1)-th reservation must be rejected — the window is full.
        with pytest.raises(BacktestRateLimitError):
            service._reserve_create_token("burst")
        # Refunding one token frees exactly one slot; a new reservation then succeeds.
        service._refund_create_token("burst", tokens[0])
        assert len(service._create_history["burst"]) == _RATE_LIMIT_MAX - 1
        service._reserve_create_token("burst")  # no raise
        assert len(service._create_history["burst"]) == _RATE_LIMIT_MAX

    @pytest.mark.asyncio
    async def test_busy_create_refunds_rate_token(self, mock_db):
        """A create rejected for BUSY slots (not rate) must refund its rate token so
        the rejected attempt doesn't count against the client's window."""
        from backend.services.backtest_service import (
            BacktestService, _MAX_CONCURRENT, BacktestBusyError,
        )
        service = BacktestService(db=mock_db, kline_cache=None)
        service._active_slots = _MAX_CONCURRENT  # all slots taken
        with pytest.raises(BacktestBusyError):
            await service.create_backtest(_make_config(), client_id="c1")
        # Busy rejection refunded the token — only successful creates count.
        assert len(service._create_history.get("c1", [])) == 0


class TestPersistResults:
    @pytest.mark.asyncio
    async def test_trade_numerics_converted_to_decimal(self, mock_db):
        """Float prices/pnl must be converted to Decimal for asyncpg NUMERIC columns."""
        from decimal import Decimal
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db)
        conn = _wire_transaction(mock_db)

        result = SimulationResult(
            trades=[{"symbol": "BTCUSDT", "side": "Buy", "entry_price": 50000.5,
                     "exit_price": 51000.25, "qty": 0.1, "leverage": 20,
                     "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "exit_time": datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                     "pnl": 100.13, "pnl_pct": 2.0, "fees_paid": 2.0, "close_reason": "tp"}],
            equity_curve=[], metrics={}, warnings=[], filter_stats={},
        )
        await service._persist_results("run-1", result)

        # executemany records: entry_price/exit_price/qty/pnl must be Decimal
        records = conn.executemany.call_args[0][1]
        row = records[0]
        # indices: 3=entry_price, 4=exit_price, 5=qty, 9=pnl
        assert isinstance(row[3], Decimal) and row[3] == Decimal("50000.5")
        assert isinstance(row[4], Decimal)
        assert isinstance(row[5], Decimal)
        assert isinstance(row[9], Decimal)

    @pytest.mark.asyncio
    async def test_persist_coerces_non_finite_trade_numerics_to_none(self, mock_db):
        """A non-finite trade numeric (NaN/Infinity) must persist as NULL, not
        Decimal('Infinity'/'NaN') — the latter is rejected by a NUMERIC column on
        PostgreSQL < 14, which would abort the whole persist transaction and LOSE a
        completed simulation. The engine guards its divisors, but _num is the
        persistence boundary and must self-defend."""
        from decimal import Decimal
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db)
        conn = _wire_transaction(mock_db)
        result = SimulationResult(
            trades=[{"symbol": "BTCUSDT", "side": "Buy", "entry_price": 50000.0,
                     "exit_price": 51000.0, "qty": 0.1, "leverage": 20,
                     "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "exit_time": datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                     "pnl": float("inf"), "pnl_pct": float("nan"),
                     "mfe_pct": float("-inf"), "mae_pct": 1.0,
                     "fees_paid": 2.0, "close_reason": "tp"}],
            equity_curve=[], metrics={}, warnings=[], filter_stats={},
        )
        await service._persist_results("run-1", result)
        records = conn.executemany.call_args[0][1]
        row = records[0]
        # Column order: ...9=pnl, 10=pnl_pct, 11=fees_paid, 12=close_reason,
        # 13=mfe_pct, 14=mae_pct. inf/nan/-inf → None; the finite mae stays Decimal.
        assert row[9] is None    # pnl = inf
        assert row[10] is None   # pnl_pct = nan
        assert row[13] is None   # mfe_pct = -inf
        assert isinstance(row[14], Decimal) and row[14] == Decimal("1")  # mae_pct = 1.0

    @pytest.mark.asyncio
    async def test_persist_deletes_old_trades_for_idempotency(self, mock_db):
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db)
        conn = _wire_transaction(mock_db)
        result = SimulationResult(trades=[], equity_curve=[], metrics={}, warnings=[], filter_stats={})
        await service._persist_results("run-1", result)
        # A DELETE of prior trades must precede insert (idempotency)
        calls = " ".join(str(c[0][0]) for c in conn.execute.call_args_list)
        assert "DELETE FROM backtest_trades" in calls

    @pytest.mark.asyncio
    async def test_persist_flips_status_completed_in_same_transaction(self, mock_db):
        """results + status='completed' must commit atomically (one transaction)
        so a status-write failure can't leave results-with-status=failed."""
        from backend.services.backtest_service import BacktestService
        from backend.schemas.backtest_schemas import SimulationResult
        service = BacktestService(db=mock_db)
        conn = _wire_transaction(mock_db)
        result = SimulationResult(trades=[], equity_curve=[], metrics={"net_profit": 1.0},
                                  warnings=[], filter_stats={})
        await service._persist_results("run-1", result)
        calls = [str(c[0][0]) for c in conn.execute.call_args_list]
        joined = " ".join(calls)
        # Both the results upsert AND the completed status flip run on the txn conn
        assert "backtest_results" in joined
        assert any("status = 'completed'" in c for c in calls)


class TestCacheStatus:
    @pytest.mark.asyncio
    async def test_cache_status_ready_when_no_gaps(self, mock_db):
        from backend.services.backtest_service import BacktestService
        kc = MagicMock()
        kc.get_coverage_gaps = AsyncMock(return_value={})
        service = BacktestService(db=mock_db, kline_cache=kc)
        result = await service.cache_status(
            ["BTCUSDT", "ETHUSDT"], "5m",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        assert result["ready"] is True
        assert result["symbols_cached"] == 2
        assert result["symbols_with_gaps"] == []

    @pytest.mark.asyncio
    async def test_cache_status_not_ready_with_gaps(self, mock_db):
        from backend.services.backtest_service import BacktestService
        kc = MagicMock()
        kc.get_coverage_gaps = AsyncMock(return_value={"ETHUSDT": [("2026-01-01", "2026-01-02")]})
        service = BacktestService(db=mock_db, kline_cache=kc)
        result = await service.cache_status(
            ["BTCUSDT", "ETHUSDT"], "5m",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        assert result["ready"] is False
        assert "ETHUSDT" in result["symbols_with_gaps"]

    @pytest.mark.asyncio
    async def test_warmup_rejects_oversized_range(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        kc = MagicMock()
        kc.ensure_coverage = AsyncMock(return_value={})
        service = BacktestService(db=mock_db, kline_cache=kc)
        # 200 symbols × 365 days × 288 ≈ 21M > 3M budget
        with pytest.raises(BacktestValidationError):
            await service.warmup_cache(
                [f"S{i}" for i in range(200)], "5m",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        kc.ensure_coverage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_warmup_reasonable_request_proceeds(self, mock_db):
        from backend.services.backtest_service import BacktestService
        kc = MagicMock()
        kc.ensure_coverage = AsyncMock(return_value={"cached": 2, "fetched": 0, "failed": 0})
        service = BacktestService(db=mock_db, kline_cache=kc)
        stats = await service.warmup_cache(
            ["BTCUSDT", "ETHUSDT"], "5m",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        assert stats["cached"] == 2
        kc.ensure_coverage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_warmup_no_cache_raises(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        service = BacktestService(db=mock_db, kline_cache=None)
        with pytest.raises(BacktestValidationError):
            await service.warmup_cache(["BTCUSDT"], "5m",
                                       datetime(2026, 1, 1, tzinfo=timezone.utc),
                                       datetime(2026, 1, 2, tzinfo=timezone.utc))

    @pytest.mark.asyncio
    async def test_warmup_bad_range_raises(self, mock_db):
        from backend.services.backtest_service import BacktestService, BacktestValidationError
        kc = MagicMock()
        kc.ensure_coverage = AsyncMock()
        service = BacktestService(db=mock_db, kline_cache=kc)
        # end <= start
        with pytest.raises(BacktestValidationError):
            await service.warmup_cache(["BTCUSDT"], "5m",
                                       datetime(2026, 1, 2, tzinfo=timezone.utc),
                                       datetime(2026, 1, 1, tzinfo=timezone.utc))
        kc.ensure_coverage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_status_no_cache_not_ready(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db, kline_cache=None)
        result = await service.cache_status(
            ["BTCUSDT", "ETHUSDT"], "5m",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        assert result["ready"] is False
        assert result["symbols_cached"] == 0
        assert set(result["symbols_with_gaps"]) == {"BTCUSDT", "ETHUSDT"}


class TestPaginatedTrades:
    @pytest.mark.asyncio
    async def test_get_trades_paginated(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db.pool.fetchrow = AsyncMock(return_value={"n": 120})
        mock_db.pool.fetch = AsyncMock(return_value=[
            {"id": 1, "symbol": "BTCUSDT", "side": "Buy", "entry_price": 50000.0,
             "exit_price": 51000.0, "qty": 0.1, "leverage": 20, "entry_time": base,
             "exit_time": base, "pnl": 100.0, "pnl_pct": 2.0, "fees_paid": 2.0,
             "close_reason": "tp", "mfe_pct": 5.0, "mae_pct": -1.0,
             "signal_score": 8, "signal_confidence": "high", "scan_id": "s1"},
        ])
        result = await service.get_backtest_trades("run-1", page=2, limit=50)
        assert result["total"] == 120
        assert result["page"] == 2
        assert len(result["trades"]) == 1
        assert result["trades"][0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_trades_filters_by_side(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"n": 0})
        mock_db.pool.fetch = AsyncMock(return_value=[])
        await service.get_backtest_trades("run-1", side="Buy", close_reason="tp")
        # both filters appear in the WHERE clause
        count_query = mock_db.pool.fetchrow.call_args[0][0]
        assert "side =" in count_query and "close_reason =" in count_query

    @pytest.mark.asyncio
    async def test_get_trades_rejects_bad_sort_column(self, mock_db):
        from backend.services.backtest_service import BacktestService
        service = BacktestService(db=mock_db)
        mock_db.pool.fetchrow = AsyncMock(return_value={"n": 0})
        mock_db.pool.fetch = AsyncMock(return_value=[])
        # A SQL-injection sort_by must be ignored (falls back to entry_time)
        await service.get_backtest_trades("run-1", sort_by="pnl; DROP TABLE backtest_trades")
        list_query = mock_db.pool.fetch.call_args[0][0]
        assert "DROP TABLE" not in list_query
        assert "ORDER BY entry_time" in list_query
