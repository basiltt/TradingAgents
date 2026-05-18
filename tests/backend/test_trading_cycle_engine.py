"""Tests for TradingCycleEngine."""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from backend.services.trading_cycle_engine import (
    TradingCycleEngine,
    NoQualifyingResultsError,
    ScanNotFoundError,
    ScanTooOldError,
    InsufficientEquityError,
    AccountNotConfiguredError,
    CycleNotFoundError,
    CycleNotRunningError,
)


def _make_engine(
    repo=None, accounts=None, close_svc=None, db=None, ws=None
):
    mock_db = db or AsyncMock()
    return TradingCycleEngine(
        cycle_repo=repo or AsyncMock(),
        accounts_svc=accounts or AsyncMock(),
        close_positions_svc=close_svc or AsyncMock(),
        db=mock_db,
        ws_manager=ws,
        bybit_concurrency=2,
        circuit_breaker_threshold=3,
        max_scan_age_seconds=7200,
    )


class TestFilterScanResults:
    def test_filter_by_score(self):
        results = [
            {"ticker": "A", "direction": "buy", "confidence": "high", "score": 1},
            {"ticker": "B", "direction": "buy", "confidence": "high", "score": 5},
            {"ticker": "C", "direction": "sell", "confidence": "high", "score": 7},
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 3, "min_confidence": "none", "signal_filter": "both", "max_trades": 20}
        )
        assert len(filtered) == 2
        assert filtered[0]["ticker"] == "C"

    def test_filter_by_confidence(self):
        results = [
            {"ticker": "A", "direction": "buy", "confidence": "low", "score": 5},
            {"ticker": "B", "direction": "buy", "confidence": "high", "score": 5},
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 0, "min_confidence": "moderate", "signal_filter": "both", "max_trades": 20}
        )
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "B"

    def test_filter_by_signal(self):
        results = [
            {"ticker": "A", "direction": "buy", "confidence": "high", "score": 5},
            {"ticker": "B", "direction": "sell", "confidence": "high", "score": 5},
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 0, "min_confidence": "none", "signal_filter": "buy", "max_trades": 20}
        )
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "A"

    def test_filter_excludes_hold(self):
        results = [
            {"ticker": "A", "direction": "hold", "confidence": "high", "score": 5},
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 0, "min_confidence": "none", "signal_filter": "both", "max_trades": 20}
        )
        assert len(filtered) == 0

    def test_filter_caps_max_trades(self):
        results = [
            {"ticker": f"T{i}", "direction": "buy", "confidence": "high", "score": 5}
            for i in range(10)
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 0, "min_confidence": "none", "signal_filter": "both", "max_trades": 3}
        )
        assert len(filtered) == 3


class TestStartCycle:
    @pytest.mark.asyncio
    async def test_account_not_configured(self):
        db = AsyncMock()
        db.get_account.return_value = None
        engine = _make_engine(db=db)
        with pytest.raises(AccountNotConfiguredError):
            await engine.start_cycle({"account_id": "x", "scan_id": "s1"})

    @pytest.mark.asyncio
    async def test_scan_not_found(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        db.get_scan.return_value = None
        engine = _make_engine(db=db)
        with pytest.raises(ScanNotFoundError):
            await engine.start_cycle({"account_id": "x", "scan_id": "s1"})


class TestDryRun:
    @pytest.mark.asyncio
    async def test_returns_qualifying(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        db.get_scan.return_value = {
            "scan_id": "s1", "started_at": datetime.now(timezone.utc).isoformat(),
            "results": [
                {"ticker": "BTC", "direction": "buy", "confidence": "high", "score": 8},
                {"ticker": "ETH", "direction": "sell", "confidence": "low", "score": 2},
            ],
        }
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "1000"}
        accounts.get_positions.return_value = []

        engine = _make_engine(db=db, accounts=accounts)
        result = await engine.dry_run({
            "account_id": "x", "scan_id": "s1",
            "min_score": 3, "min_confidence": "moderate",
            "signal_filter": "both", "max_trades": 5,
            "capital_pct": 10, "target_type": "percentage",
            "target_value": 10, "max_drawdown_pct": 5,
        })
        assert result["qualifying_symbols"] == ["BTC"]
        assert result["estimated_trades"] == 1
        assert result["current_equity"] == 1000.0

    @pytest.mark.asyncio
    async def test_warns_existing_position(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        db.get_scan.return_value = {
            "scan_id": "s1", "started_at": datetime.now(timezone.utc).isoformat(),
            "results": [
                {"ticker": "BTC", "direction": "buy", "confidence": "high", "score": 8},
            ],
        }
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "1000"}
        accounts.get_positions.return_value = [{"symbol": "BTC", "size": "1.0"}]

        engine = _make_engine(db=db, accounts=accounts)
        result = await engine.dry_run({
            "account_id": "x", "scan_id": "s1",
            "min_score": 3, "min_confidence": "none",
            "signal_filter": "both", "max_trades": 5,
            "capital_pct": 10, "target_type": "percentage",
            "target_value": 10, "max_drawdown_pct": 5,
        })
        assert any("Existing positions" in w for w in result["warnings"])
        assert result["estimated_trades"] == 0


class TestStopCycle:
    @pytest.mark.asyncio
    async def test_not_found(self):
        repo = AsyncMock()
        repo.update_status.return_value = False
        repo.get_cycle.return_value = None
        engine = _make_engine(repo=repo)
        with pytest.raises(CycleNotFoundError):
            await engine.stop_cycle(999)

    @pytest.mark.asyncio
    async def test_already_completed_returns_cycle(self):
        repo = AsyncMock()
        repo.update_status.return_value = False
        repo.get_cycle.return_value = {"id": 1, "status": "completed"}
        engine = _make_engine(repo=repo)
        result = await engine.stop_cycle(1)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_not_running(self):
        repo = AsyncMock()
        repo.update_status.return_value = False
        repo.get_cycle.return_value = {"id": 1, "status": "pending"}
        engine = _make_engine(repo=repo)
        with pytest.raises(CycleNotRunningError):
            await engine.stop_cycle(1)


class TestOnRuleTriggered:
    @pytest.mark.asyncio
    async def test_target_reached(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "stopping"}
        db = AsyncMock()
        engine = _make_engine(repo=repo, db=db)
        await engine.on_rule_triggered({
            "cycle_id": 1, "trigger_type": "BALANCE_ABOVE",
        })
        repo.update_status.assert_any_call(1, "stopping")


class TestShutdown:
    @pytest.mark.asyncio
    async def test_marks_active_failed(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.get_cycle_trade_symbols.return_value = ["BTC"]
        close_svc = AsyncMock()
        close_svc.close_all_for_rule.return_value = {"total": 0, "closed": 0, "failed": 0, "results": []}
        engine = _make_engine(repo=repo, close_svc=close_svc)
        engine._active_tasks[1] = asyncio.create_task(asyncio.sleep(999))
        await engine.shutdown()
        repo.update_status.assert_called()
        args = repo.update_status.call_args
        assert args[0][1] == "failed"


class TestFilterScanResultsEdge:
    def test_empty_input(self):
        filtered = TradingCycleEngine.filter_scan_results(
            [], {"min_score": 0, "min_confidence": "none", "signal_filter": "both", "max_trades": 20}
        )
        assert filtered == []

    def test_all_filtered_out(self):
        results = [
            {"ticker": "A", "direction": "buy", "confidence": "low", "score": 1},
        ]
        filtered = TradingCycleEngine.filter_scan_results(
            results, {"min_score": 9, "min_confidence": "high", "signal_filter": "both", "max_trades": 20}
        )
        assert filtered == []


class TestStartCycleErrors:
    @pytest.mark.asyncio
    async def test_scan_too_old(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        db.get_scan.return_value = {
            "scan_id": "s1", "started_at": old_time,
            "results": [
                {"ticker": "BTC", "direction": "buy", "confidence": "high", "score": 8},
            ],
        }
        repo = AsyncMock()
        engine = _make_engine(db=db, repo=repo)
        with pytest.raises(ScanTooOldError):
            await engine.start_cycle({
                "account_id": "x", "scan_id": "s1",
                "min_score": 3, "min_confidence": "none",
                "signal_filter": "both", "max_trades": 5,
            })

    @pytest.mark.asyncio
    async def test_no_qualifying_results(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        db.get_scan.return_value = {
            "scan_id": "s1", "started_at": datetime.now(timezone.utc).isoformat(),
            "results": [
                {"ticker": "A", "direction": "hold", "confidence": "low", "score": 1},
            ],
        }
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "1000"}
        repo = AsyncMock()
        engine = _make_engine(db=db, accounts=accounts, repo=repo)
        with pytest.raises(NoQualifyingResultsError):
            await engine.start_cycle({
                "account_id": "x", "scan_id": "s1",
                "min_score": 5, "min_confidence": "high",
                "signal_filter": "both", "max_trades": 5,
            })

    @pytest.mark.asyncio
    async def test_insufficient_equity_dry_run(self):
        db = AsyncMock()
        db.get_account.return_value = {"id": "x", "is_active": 1}
        db.get_scan.return_value = {
            "scan_id": "s1", "started_at": datetime.now(timezone.utc).isoformat(),
            "results": [
                {"ticker": "BTC", "direction": "buy", "confidence": "high", "score": 8},
            ],
        }
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "0"}
        engine = _make_engine(db=db, accounts=accounts)
        with pytest.raises(InsufficientEquityError):
            await engine.dry_run({
                "account_id": "x", "scan_id": "s1",
                "min_score": 3, "min_confidence": "none",
                "signal_filter": "both", "max_trades": 5,
                "capital_pct": 10, "target_type": "percentage",
                "target_value": 10, "max_drawdown_pct": 5,
            })


class TestOnRuleTriggeredEdge:
    @pytest.mark.asyncio
    async def test_balance_below_triggers_stopped(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "stopping"}
        engine = _make_engine(repo=repo)
        await engine.on_rule_triggered({
            "cycle_id": 1, "trigger_type": "BALANCE_BELOW",
        })
        repo.update_status.assert_any_call(1, "stopping")
        final_call = [c for c in repo.update_status.call_args_list if len(c[0]) >= 2 and c[0][1] == "stopped"]
        assert len(final_call) == 1

    @pytest.mark.asyncio
    async def test_no_cycle_id_returns_early(self):
        repo = AsyncMock()
        engine = _make_engine(repo=repo)
        await engine.on_rule_triggered({"trigger_type": "BALANCE_ABOVE"})
        repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_status_fails_returns_early(self):
        repo = AsyncMock()
        repo.update_status.return_value = False
        engine = _make_engine(repo=repo)
        await engine.on_rule_triggered({
            "cycle_id": 1, "trigger_type": "BALANCE_ABOVE",
        })
        repo.get_cycle.assert_not_called()


class TestExecuteCycle:
    @pytest.mark.asyncio
    async def test_successful_trade_placement(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.add_trade.return_value = 1
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "placing_trades"}
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "1000"}
        accounts.get_positions.return_value = []
        accounts.place_trade.return_value = {"orderId": "ord123"}
        db = AsyncMock()
        engine = _make_engine(repo=repo, accounts=accounts, db=db)
        await engine._run_cycle(
            1,
            [{"ticker": "BTC", "direction": "buy", "confidence": "high", "score": 8}],
            {"account_id": "x", "trade_direction": "straight", "leverage": 10,
             "capital_pct": 5, "max_drawdown_pct": 5, "target_type": "percentage",
             "target_value": 10},
        )
        accounts.place_trade.assert_called_once()
        repo.update_trade.assert_called()

    @pytest.mark.asyncio
    async def test_zero_equity_finalizes_failed(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "placing_trades"}
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "0"}
        engine = _make_engine(repo=repo, accounts=accounts)
        await engine._run_cycle(1, [{"ticker": "BTC", "direction": "buy"}],
                                {"account_id": "x", "max_drawdown_pct": 5})
        final_calls = [c for c in repo.update_status.call_args_list
                       if len(c[0]) >= 2 and c[0][1] == "failed"]
        assert len(final_calls) >= 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_triggers(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.add_trade.return_value = 1
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "placing_trades"}
        accounts = AsyncMock()
        accounts.get_wallet.return_value = {"totalEquity": "1000"}
        accounts.get_positions.return_value = []
        accounts.place_trade.side_effect = Exception("API error")
        db = AsyncMock()
        engine = _make_engine(repo=repo, accounts=accounts, db=db)
        await engine._run_cycle(
            1,
            [{"ticker": f"T{i}", "direction": "buy", "confidence": "high", "score": 8} for i in range(5)],
            {"account_id": "x", "trade_direction": "straight", "leverage": 10,
             "capital_pct": 5, "max_drawdown_pct": 5, "target_type": "percentage",
             "target_value": 10},
        )
        [c for c in repo.update_trade.call_args_list
                        if c[1].get("status") == "failed" or (len(c[0]) > 1 and "failed" in str(c))]
        assert accounts.place_trade.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_catches_exception_and_finalizes(self):
        repo = AsyncMock()
        repo.update_status.return_value = True
        repo.get_cycle.return_value = {"id": 1, "account_id": "x", "status": "placing_trades"}
        accounts = AsyncMock()
        accounts.get_wallet.side_effect = Exception("wallet error")
        engine = _make_engine(repo=repo, accounts=accounts)
        await engine._execute_cycle(1, [{"ticker": "BTC"}], {"account_id": "x", "max_drawdown_pct": 5})
        assert 1 not in engine._active_tasks


class TestStartupRecovery:
    @pytest.mark.asyncio
    async def test_marks_stuck_cycles_failed(self):
        repo = AsyncMock()
        repo.find_all_non_terminal_cycles.return_value = [
            {"id": 1, "status": "running"},
            {"id": 2, "status": "placing_trades"},
        ]
        repo.update_status.return_value = True
        repo.get_cycle.return_value = None
        engine = _make_engine(repo=repo)
        await engine._startup_recovery()
        assert repo.reconcile_counters.call_count == 2
        assert repo.expire_cycle_rules.call_count == 2
        failed_calls = [c for c in repo.update_status.call_args_list
                        if len(c[0]) >= 2 and c[0][1] == "failed"]
        assert len(failed_calls) == 2
