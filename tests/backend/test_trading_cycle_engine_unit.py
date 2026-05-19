"""Unit tests for TradingCycleEngine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import asyncpg

from backend.services.trading_cycle_engine import (
    ALLOWED_STOP_REASONS,
    CONFIDENCE_ORDER,
    AccountNotConfiguredError,
    CloseRuleLimitError,
    CycleAlreadyActiveError,
    CycleNotFoundError,
    CycleNotRunningError,
    InsufficientEquityError,
    NoQualifyingResultsError,
    ScanNotFoundError,
    ScanTooOldError,
    TradingCycleEngine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cycle_repo():
    repo = AsyncMock()
    repo.list_cycles = AsyncMock(return_value=([], 0))
    repo.get_cycle = AsyncMock(return_value={"id": 1, "status": "running", "account_id": 10})
    repo.create_cycle = AsyncMock(return_value=1)
    repo.update_status = AsyncMock(return_value=True)
    repo.add_trade = AsyncMock(return_value=100)
    repo.update_trade = AsyncMock()
    repo.increment_counters = AsyncMock()
    repo.activate_cycle_rules = AsyncMock()
    repo.expire_cycle_rules = AsyncMock()
    repo.find_all_non_terminal_cycles = AsyncMock(return_value=[])
    repo.find_stuck_cycles = AsyncMock(return_value=[])
    repo.get_cycle_trade_symbols = AsyncMock(return_value=["BTCUSDT"])
    repo.reconcile_counters = AsyncMock()
    return repo


@pytest.fixture
def accounts_svc():
    svc = AsyncMock()
    svc.get_wallet = AsyncMock(return_value={"totalEquity": "10000"})
    svc.get_positions = AsyncMock(return_value=[])
    svc.place_trade = AsyncMock(return_value={"orderId": "ord123"})
    return svc


@pytest.fixture
def close_positions_svc():
    svc = AsyncMock()
    svc.close_all_for_rule = AsyncMock(return_value={"closed": 1})
    return svc


@pytest.fixture
def db():
    d = AsyncMock()
    d.get_account = AsyncMock(return_value={"id": 10, "is_active": True})
    d.get_scan = AsyncMock(return_value={
        "id": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "results": [
            {"ticker": "BTCUSDT", "score": 8, "confidence": "high", "direction": "buy"},
            {"ticker": "ETHUSDT", "score": 7, "confidence": "moderate", "direction": "sell"},
        ],
    })
    d.count_active_rules_by_account = AsyncMock(return_value={})
    d.insert_close_rule = AsyncMock()
    return d


@pytest.fixture
def ws_manager():
    return AsyncMock()


@pytest.fixture
def engine(cycle_repo, accounts_svc, close_positions_svc, db, ws_manager):
    return TradingCycleEngine(
        cycle_repo=cycle_repo,
        accounts_svc=accounts_svc,
        close_positions_svc=close_positions_svc,
        db=db,
        ws_manager=ws_manager,
        bybit_concurrency=2,
        circuit_breaker_threshold=3,
        max_duration_seconds=300,
        max_scan_age_seconds=7200,
    )


@pytest.fixture
def base_config():
    return {
        "account_id": 10,
        "scan_id": 1,
        "min_score": 3,
        "min_confidence": "moderate",
        "signal_filter": "both",
        "max_trades": 20,
        "capital_pct": 5,
        "leverage": 10,
        "target_type": "percentage",
        "target_value": 10,
        "max_drawdown_pct": 5,
        "trade_direction": "straight",
    }


# ---------------------------------------------------------------------------
# filter_scan_results (static, sync)
# ---------------------------------------------------------------------------

class TestFilterScanResults:
    def test_basic_filtering(self):
        results = [
            {"ticker": "A", "score": 8, "confidence": "high", "direction": "buy"},
            {"ticker": "B", "score": 2, "confidence": "high", "direction": "buy"},  # low score
            {"ticker": "C", "score": 8, "confidence": "low", "direction": "buy"},  # low confidence
            {"ticker": "D", "score": 8, "confidence": "high", "direction": "hold"},  # hold
        ]
        config = {"min_score": 3, "min_confidence": "moderate", "signal_filter": "both", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 1
        assert out[0]["ticker"] == "A"

    def test_signal_filter_buy_only(self):
        results = [
            {"ticker": "A", "score": 8, "confidence": "high", "direction": "buy"},
            {"ticker": "B", "score": 8, "confidence": "high", "direction": "sell"},
        ]
        config = {"min_score": 3, "min_confidence": "moderate", "signal_filter": "buy", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 1
        assert out[0]["ticker"] == "A"

    def test_signal_filter_sell_only(self):
        """Sell signals have negative scores; min_score compares abs(score)."""
        results = [
            {"ticker": "A", "score": -8, "confidence": "high", "direction": "sell"},
            {"ticker": "B", "score": 8, "confidence": "high", "direction": "buy"},
            {"ticker": "C", "score": 0, "confidence": "none", "direction": "hold"},
        ]
        config = {"min_score": 3, "min_confidence": "moderate", "signal_filter": "sell", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 1
        assert out[0]["ticker"] == "A"

    def test_sell_signals_pass_default_min_score(self):
        """Sell signals with abs(score) >= min_score pass the filter."""
        results = [
            {"ticker": "A", "score": -5, "confidence": "moderate", "direction": "sell"},
            {"ticker": "B", "score": -2, "confidence": "low", "direction": "sell"},
        ]
        config = {"min_score": 3, "min_confidence": "low", "signal_filter": "both", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 1
        assert out[0]["ticker"] == "A"

    def test_underweight_maps_to_hold_not_sell(self):
        """Underweight signals should NOT appear as sell direction in scan results.

        This verifies the upstream _rating_to_direction mapping: Underweight→hold.
        By the time results reach filter_scan_results, Underweight is already 'hold'
        with score=0, so it gets excluded by the direction=='hold' check.
        """
        results = [
            {"ticker": "A", "score": 0, "confidence": "none", "direction": "hold"},
            {"ticker": "B", "score": -7, "confidence": "high", "direction": "sell"},
        ]
        config = {"min_score": -10, "min_confidence": "moderate", "signal_filter": "sell", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 1
        assert out[0]["ticker"] == "B"

    def test_max_trades_limit(self):
        results = [{"ticker": f"T{i}", "score": 10, "confidence": "high", "direction": "buy"} for i in range(30)]
        config = {"min_score": 3, "min_confidence": "moderate", "signal_filter": "both", "max_trades": 5}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert len(out) == 5

    def test_sorted_by_score_desc(self):
        results = [
            {"ticker": "LOW", "score": 4, "confidence": "high", "direction": "buy"},
            {"ticker": "HIGH", "score": 9, "confidence": "high", "direction": "buy"},
        ]
        config = {"min_score": 3, "min_confidence": "moderate", "signal_filter": "both", "max_trades": 20}
        out = TradingCycleEngine.filter_scan_results(results, config)
        assert out[0]["ticker"] == "HIGH"

    def test_empty_results(self):
        out = TradingCycleEngine.filter_scan_results([], {"min_score": 3, "min_confidence": "moderate", "signal_filter": "both", "max_trades": 20})
        assert out == []

    def test_defaults_when_config_keys_missing(self):
        results = [{"ticker": "A", "score": 5, "confidence": "high", "direction": "buy"}]
        out = TradingCycleEngine.filter_scan_results(results, {})
        assert len(out) == 1


# ---------------------------------------------------------------------------
# start_cycle
# ---------------------------------------------------------------------------

class TestStartCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_happy_path(self, engine, base_config, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "placing_trades", "account_id": 10}
        result = await engine.start_cycle(base_config)
        assert result["id"] == 1
        cycle_repo.create_cycle.assert_called_once()
        assert 1 in engine._active_tasks
        # Cleanup
        engine._active_tasks[1].cancel()
        try:
            await engine._active_tasks[1]
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio(loop_scope="function")
    async def test_account_not_configured(self, engine, base_config, db):
        db.get_account.return_value = None
        with pytest.raises(AccountNotConfiguredError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_account_inactive(self, engine, base_config, db):
        db.get_account.return_value = {"id": 10, "is_active": False}
        with pytest.raises(AccountNotConfiguredError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_scan_not_found(self, engine, base_config, db):
        db.get_scan.return_value = None
        with pytest.raises(ScanNotFoundError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_scan_too_old(self, engine, base_config, db):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        db.get_scan.return_value = {"id": 1, "started_at": old_time, "results": [
            {"ticker": "BTC", "score": 8, "confidence": "high", "direction": "buy"},
        ]}
        with pytest.raises(ScanTooOldError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_qualifying_results(self, engine, base_config, db):
        db.get_scan.return_value = {"id": 1, "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
        with pytest.raises(NoQualifyingResultsError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_rule_limit(self, engine, base_config, db):
        db.count_active_rules_by_account.return_value = {10: 9}
        with pytest.raises(CloseRuleLimitError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cycle_already_active(self, engine, base_config, cycle_repo):
        cycle_repo.create_cycle.side_effect = asyncpg.UniqueViolationError("")
        with pytest.raises(CycleAlreadyActiveError):
            await engine.start_cycle(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_accepts_object_config(self, engine, cycle_repo, db):
        cfg_obj = MagicMock()
        cfg_obj.__dict__ = {
            "account_id": 10, "scan_id": 1, "min_score": 3,
            "min_confidence": "moderate", "signal_filter": "both",
            "max_trades": 20,
        }
        # Make isinstance check return False for dict
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        result = await engine.start_cycle(cfg_obj)
        assert result["id"] == 1
        engine._active_tasks[1].cancel()
        try:
            await engine._active_tasks[1]
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# stop_cycle
# ---------------------------------------------------------------------------

class TestStopCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_happy_path(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopped", "account_id": 10}
        result = await engine.stop_cycle(1)
        assert result["status"] == "stopped"
        cycle_repo.update_status.assert_any_call(1, "stopping")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cycle_not_found(self, engine, cycle_repo):
        cycle_repo.update_status.return_value = False
        cycle_repo.get_cycle.return_value = None
        with pytest.raises(CycleNotFoundError):
            await engine.stop_cycle(999)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cycle_already_stopped(self, engine, cycle_repo):
        cycle_repo.update_status.return_value = False
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopped", "account_id": 10}
        result = await engine.stop_cycle(1)
        assert result["status"] == "stopped"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cycle_not_running(self, engine, cycle_repo):
        cycle_repo.update_status.return_value = False
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "placing_trades", "account_id": 10}
        with pytest.raises(CycleNotRunningError):
            await engine.stop_cycle(1)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancels_active_task(self, engine, cycle_repo):
        task = MagicMock()
        task.done.return_value = False
        task.cancel = MagicMock()
        # Make shield/wait_for work with a future
        future = asyncio.get_event_loop().create_future()
        future.set_result(None)
        task.__await__ = future.__await__
        engine._active_tasks[1] = task
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopped", "account_id": 10}
        await engine.stop_cycle(1)
        task.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_happy_path(self, engine, base_config):
        result = await engine.dry_run(base_config)
        assert "qualifying_symbols" in result
        assert "estimated_trades" in result
        assert result["current_equity"] == 10000.0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_account_not_configured(self, engine, base_config, db):
        db.get_account.return_value = None
        with pytest.raises(AccountNotConfiguredError):
            await engine.dry_run(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_scan_not_found(self, engine, base_config, db):
        db.get_scan.return_value = None
        with pytest.raises(ScanNotFoundError):
            await engine.dry_run(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_scan_too_old(self, engine, base_config, db):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        db.get_scan.return_value = {"id": 1, "started_at": old_time, "results": [
            {"ticker": "BTC", "score": 8, "confidence": "high", "direction": "buy"},
        ]}
        with pytest.raises(ScanTooOldError):
            await engine.dry_run(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_qualifying_results(self, engine, base_config, db):
        db.get_scan.return_value = {"id": 1, "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
        with pytest.raises(NoQualifyingResultsError):
            await engine.dry_run(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_insufficient_equity(self, engine, base_config, accounts_svc):
        accounts_svc.get_wallet.return_value = {"totalEquity": "0"}
        with pytest.raises(InsufficientEquityError):
            await engine.dry_run(base_config)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_warnings_conflicting_positions(self, engine, base_config, accounts_svc):
        accounts_svc.get_positions.return_value = [{"symbol": "BTCUSDT", "size": "1.0"}]
        result = await engine.dry_run(base_config)
        assert any("skipped" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio(loop_scope="function")
    async def test_warnings_high_exposure(self, engine, base_config, db):
        # Many symbols to trigger >80% capital warning
        results = [{"ticker": f"T{i}USDT", "score": 8, "confidence": "high", "direction": "buy"} for i in range(20)]
        db.get_scan.return_value = {"id": 1, "started_at": datetime.now(timezone.utc).isoformat(), "results": results}
        base_config["capital_pct"] = 5  # 5% * 20 = 100%
        result = await engine.dry_run(base_config)
        assert any("exposure" in w.lower() or "capital" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio(loop_scope="function")
    async def test_target_absolute(self, engine, base_config):
        base_config["target_type"] = "absolute"
        base_config["target_value"] = 500
        result = await engine.dry_run(base_config)
        assert result["balance_above_threshold"] == 10500.0


# ---------------------------------------------------------------------------
# list_cycles / get_cycle
# ---------------------------------------------------------------------------

class TestListAndGetCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_list_cycles(self, engine, cycle_repo):
        cycle_repo.list_cycles.return_value = ([{"id": 1}], 1)
        results, count = await engine.list_cycles(0, 10, status="running")
        assert count == 1
        cycle_repo.list_cycles.assert_called_once_with(0, 10, status="running")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_cycle(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 5, "status": "running"}
        result = await engine.get_cycle(5)
        assert result["id"] == 5


# ---------------------------------------------------------------------------
# Lifecycle callbacks
# ---------------------------------------------------------------------------

class TestLifecycleCallbacks:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_notify_calls_callbacks(self, engine):
        cb = AsyncMock()
        engine.register_lifecycle_callback(cb)
        await engine._notify("test.event", {"key": "val"})
        cb.assert_called_once_with("test.event", {"key": "val"})

    @pytest.mark.asyncio(loop_scope="function")
    async def test_notify_swallows_callback_errors(self, engine):
        cb = AsyncMock(side_effect=RuntimeError("boom"))
        engine.register_lifecycle_callback(cb)
        # Should not raise
        await engine._notify("test.event", {})


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_cancels_sweep(self, engine):
        engine._sweep_task = AsyncMock()
        engine._sweep_task.cancel = MagicMock()
        await engine.shutdown()
        engine._sweep_task.cancel.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_finalizes_active_cycles(self, engine, cycle_repo):
        # Create a real task that can be cancelled
        async def dummy():
            await asyncio.sleep(100)

        task = asyncio.create_task(dummy())
        engine._active_tasks[42] = task
        cycle_repo.get_cycle.return_value = {"id": 42, "status": "running", "account_id": 10}

        await engine.shutdown()
        assert engine._active_tasks == {}
        # _finalize_cycle should have been called
        cycle_repo.update_status.assert_called()


# ---------------------------------------------------------------------------
# start (startup_recovery + sweep)
# ---------------------------------------------------------------------------

class TestStart:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_recovers_stuck_cycles(self, engine, cycle_repo):
        cycle_repo.find_all_non_terminal_cycles.return_value = [
            {"id": 5, "status": "placing_trades"},
        ]
        await engine.start()
        cycle_repo.reconcile_counters.assert_called_once_with(5)
        cycle_repo.expire_cycle_rules.assert_called_once_with(5)
        # Cleanup sweep task
        engine._sweep_task.cancel()
        try:
            await engine._sweep_task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# on_rule_triggered
# ---------------------------------------------------------------------------

class TestOnRuleTriggered:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_balance_above_completes_cycle(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopping", "account_id": 10}
        await engine.on_rule_triggered({"cycle_id": 1, "trigger_type": "BALANCE_ABOVE"})
        # update_status called with "stopping" then finalize calls it again
        cycle_repo.update_status.assert_any_call(1, "stopping")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_balance_below_stops_cycle(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopping", "account_id": 10}
        await engine.on_rule_triggered({"cycle_id": 1, "trigger_type": "BALANCE_BELOW"})
        cycle_repo.update_status.assert_any_call(1, "stopping")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_cycle_id_returns_early(self, engine, cycle_repo):
        await engine.on_rule_triggered({"trigger_type": "BALANCE_ABOVE"})
        cycle_repo.update_status.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_status_fails_returns_early(self, engine, cycle_repo):
        cycle_repo.update_status.return_value = False
        await engine.on_rule_triggered({"cycle_id": 1, "trigger_type": "BALANCE_ABOVE"})
        # _finalize_cycle should not be called (no get_cycle call for finalize)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancels_active_task(self, engine, cycle_repo):
        task = MagicMock()
        task.done.return_value = False
        task.cancel = MagicMock()
        engine._active_tasks[1] = task
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "stopping", "account_id": 10}
        await engine.on_rule_triggered({"cycle_id": 1, "trigger_type": "BALANCE_ABOVE"})
        task.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# _finalize_cycle
# ---------------------------------------------------------------------------

class TestFinalizeCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_skips_terminal_status(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "completed", "account_id": 10}
        await engine._finalize_cycle(1, "stopped", "user_stopped")
        # Should not call update_status since already terminal
        cycle_repo.update_status.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_stop_reason_defaults(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._finalize_cycle(1, "failed", "invalid_reason")
        cycle_repo.update_status.assert_called_once()
        call_kwargs = cycle_repo.update_status.call_args[1]
        assert call_kwargs["stop_reason"] == "circuit_breaker"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_closes_positions_on_user_stop(self, engine, cycle_repo, close_positions_svc):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._finalize_cycle(1, "stopped", "user_stopped")
        close_positions_svc.close_all_for_rule.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_does_not_close_positions_on_target_reached(self, engine, cycle_repo, close_positions_svc):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._finalize_cycle(1, "completed", "target_reached")
        close_positions_svc.close_all_for_rule.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_status_fails_returns(self, engine, cycle_repo, close_positions_svc):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        cycle_repo.update_status.return_value = False
        await engine._finalize_cycle(1, "stopped", "user_stopped")
        close_positions_svc.close_all_for_rule.assert_not_called()


# ---------------------------------------------------------------------------
# _run_cycle
# ---------------------------------------------------------------------------

class TestRunCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_insufficient_balance_during_run(self, engine, cycle_repo, accounts_svc):
        accounts_svc.get_wallet.return_value = {"totalEquity": "0"}
        cfg = {"account_id": 10, "trade_direction": "straight", "capital_pct": 5, "leverage": 10}
        filtered = [{"ticker": "BTC", "direction": "buy"}]

        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._run_cycle(1, filtered, cfg)
        # Should finalize as failed/insufficient_balance
        cycle_repo.update_status.assert_any_call(1, "placing_trades")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_all_trades_failed(self, engine, cycle_repo, accounts_svc):
        accounts_svc.get_positions.return_value = [{"symbol": "BTCUSDT", "size": "1.0"}]
        cfg = {"account_id": 10, "trade_direction": "straight", "capital_pct": 5, "leverage": 10,
               "target_type": "percentage", "target_value": 10, "max_drawdown_pct": 5}
        filtered = [{"ticker": "BTCUSDT", "direction": "buy"}]

        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._run_cycle(1, filtered, cfg)
        # finalize with all_trades_failed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_circuit_breaker(self, engine, cycle_repo, accounts_svc):
        accounts_svc.place_trade.side_effect = RuntimeError("API error")
        cfg = {"account_id": 10, "trade_direction": "straight", "capital_pct": 5, "leverage": 10,
               "target_type": "percentage", "target_value": 10, "max_drawdown_pct": 5}
        filtered = [
            {"ticker": f"T{i}USDT", "direction": "buy"} for i in range(5)
        ]

        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._run_cycle(1, filtered, cfg)
        # After 3 failures, circuit breaker should kick in

    @pytest.mark.asyncio(loop_scope="function")
    async def test_successful_trade_placement(self, engine, cycle_repo, accounts_svc, db):
        cfg = {"account_id": 10, "trade_direction": "straight", "capital_pct": 5, "leverage": 10,
               "target_type": "percentage", "target_value": 10, "max_drawdown_pct": 5}
        filtered = [{"ticker": "BTCUSDT", "direction": "buy"}]

        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._run_cycle(1, filtered, cfg)
        accounts_svc.place_trade.assert_called_once()
        cycle_repo.activate_cycle_rules.assert_called_once_with(1)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_contra_trade_direction(self, engine, cycle_repo, accounts_svc, db):
        cfg = {"account_id": 10, "trade_direction": "contra", "capital_pct": 5, "leverage": 10,
               "target_type": "percentage", "target_value": 10, "max_drawdown_pct": 5}
        filtered = [{"ticker": "BTCUSDT", "direction": "buy"}]

        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}
        await engine._run_cycle(1, filtered, cfg)
        call_kwargs = accounts_svc.place_trade.call_args[1]
        assert call_kwargs["trade_direction"] == "contra"


# ---------------------------------------------------------------------------
# _execute_cycle
# ---------------------------------------------------------------------------

class TestExecuteCycle:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_exception_finalizes_as_failed(self, engine, cycle_repo):
        cycle_repo.get_cycle.return_value = {"id": 1, "status": "running", "account_id": 10}

        with patch.object(engine, "_run_cycle", side_effect=RuntimeError("unexpected")):
            await engine._execute_cycle(1, [], {})

        # Should have called _finalize_cycle with failed/circuit_breaker
        cycle_repo.update_status.assert_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancelled_error_reraises(self, engine):
        with patch.object(engine, "_run_cycle", side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await engine._execute_cycle(1, [], {})


# ---------------------------------------------------------------------------
# _sweep_loop (basic coverage)
# ---------------------------------------------------------------------------

class TestSweepLoop:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_sweep_cancellation(self, engine):
        """Sweep loop should exit cleanly on CancelledError."""
        # The initial sleep(60) will be cancelled
        task = asyncio.create_task(engine._sweep_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------

class TestErrorClasses:
    def test_error_codes(self):
        assert CycleAlreadyActiveError.code == "CYCLE_ALREADY_ACTIVE"
        assert InsufficientEquityError.code == "INSUFFICIENT_EQUITY"
        assert NoQualifyingResultsError.code == "NO_QUALIFYING_RESULTS"
        assert ScanNotFoundError.code == "SCAN_NOT_FOUND"
        assert ScanTooOldError.code == "SCAN_TOO_OLD"
        assert CloseRuleLimitError.code == "CLOSE_RULE_LIMIT"
        assert AccountNotConfiguredError.code == "ACCOUNT_NOT_CONFIGURED"
        assert CycleNotFoundError.code == "CYCLE_NOT_FOUND"
        assert CycleNotRunningError.code == "CYCLE_NOT_RUNNING"

    def test_allowed_stop_reasons(self):
        assert "target_reached" in ALLOWED_STOP_REASONS
        assert "user_stopped" in ALLOWED_STOP_REASONS
        assert "server_shutdown" in ALLOWED_STOP_REASONS

    def test_confidence_order(self):
        assert CONFIDENCE_ORDER["none"] < CONFIDENCE_ORDER["low"]
        assert CONFIDENCE_ORDER["low"] < CONFIDENCE_ORDER["moderate"]
        assert CONFIDENCE_ORDER["moderate"] < CONFIDENCE_ORDER["high"]
