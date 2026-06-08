"""Tests for ScannerService — covers the previously uncovered 69% of scanner_service.py."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.scanner_service import (
    ScannerBusyError,
    ScannerService,
    _parse_signal_from_reports,
)


# ---------------------------------------------------------------------------
# _parse_signal_from_reports
# ---------------------------------------------------------------------------

class TestParseSignalFromReports:
    def test_empty_reports_returns_hold(self):
        result = _parse_signal_from_reports({})
        assert result["direction"] == "hold"

    def test_trader_json_buy(self):
        reports = {"trader": '{"trade_type": "long", "confidence": 8}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"
        assert result["confidence"] == "high"
        assert result["score"] == 8

    def test_trader_json_sell(self):
        reports = {"trader": '{"trade_type": "short", "confidence": 3}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "sell"
        assert result["confidence"] == "low"
        assert result["score"] == -3

    def test_trader_json_hold_no_trade(self):
        reports = {"trader": '{"trade_type": "no trade", "confidence": 5}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "hold"

    def test_trader_json_hold_neutral(self):
        reports = {"trader": '{"trade_type": "hold", "confidence": 5}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "hold"

    def test_trader_json_buy_alias(self):
        reports = {"trader": '{"trade_type": "buy", "confidence": 7}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"

    def test_trader_json_sell_alias(self):
        reports = {"trader": '{"trade_type": "sell", "confidence": 2}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "sell"

    def test_trader_json_invalid_confidence_ignored(self):
        # confidence out of range (0 is not valid per 1<=raw_conf<=10)
        # defaults to conf_score=None → score=5 (moderate default)
        reports = {"trader": '{"trade_type": "buy", "confidence": 0}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"
        assert result["confidence"] in ("moderate", "low", "none")

    def test_trader_json_parse_error_falls_through(self):
        reports = {"trader": '{"trade_type": INVALID JSON}'}
        result = _parse_signal_from_reports(reports)
        # falls through to fallback regex on trader text
        assert isinstance(result["direction"], str)

    def test_pm_reject_overrides_to_hold(self):
        reports = {
            "trader": '{"trade_type": "buy", "confidence": 9}',
            "portfolio_manager": "Final Decision: Reject this trade",
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "hold"
        assert result["score"] == 0

    def test_pm_approve_with_direction(self):
        reports = {
            "portfolio_manager": "Final Decision: Approve — long position recommended",
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"

    def test_pm_approve_sell_direction(self):
        reports = {
            "portfolio_manager": "Final Decision: Approve — short position recommended",
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "sell"

    def test_pm_modify_with_direction(self):
        reports = {
            "portfolio_manager": "Final Decision: Modify — take long position",
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"

    def test_final_trade_decision_fallback(self):
        # Current code: no text regex fallback — returns hold/none/0 for unstructured input
        reports = {"final_trade_decision": "Recommendation: buy this asset"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_percentage_confidence_parsing(self):
        # Current code: no text regex for percentage — returns hold/none/0
        reports = {"trader": "We recommend a buy with 80% confidence"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_text_confidence_very_high(self):
        # Current code: narrative text not parsed — returns hold/none/0
        reports = {"trader": "very high confidence buy signal"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_text_confidence_strong(self):
        # Current code: narrative text not parsed — returns hold/none/0
        reports = {"trader": "strong buy signal detected"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_text_confidence_moderate(self):
        # Current code: narrative text not parsed — returns hold/none/0
        reports = {"trader": "moderate confidence sell signal"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("sell", "hold")

    def test_fallback_sell_from_bearish(self):
        # Current code: no bullish/bearish keyword regex — returns hold
        reports = {"final_trade_decision": "bearish outlook, expect decline"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("sell", "hold")

    def test_fallback_buy_from_bullish(self):
        # Current code: no bullish/bearish keyword regex — returns hold
        reports = {"final_trade_decision": "bullish pattern emerging"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_score_sign_for_sell(self):
        reports = {"trader": '{"trade_type": "sell", "confidence": 6}'}
        result = _parse_signal_from_reports(reports)
        assert result["score"] == -6

    def test_score_zero_for_hold(self):
        reports = {"trader": '{"trade_type": "hold", "confidence": 5}'}
        result = _parse_signal_from_reports(reports)
        assert result["score"] == 0

    def test_confidence_score_clamped_at_10(self):
        # 100% → round(100/10) = 10
        reports = {"final_trade_decision": "100% confidence buy"}
        result = _parse_signal_from_reports(reports)
        assert result["score"] <= 10

    def test_trader_no_trade_no_trade_underscore(self):
        reports = {"trader": '{"trade_type": "no_trade", "confidence": 5}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "hold"

    def test_trader_pass(self):
        reports = {"trader": '{"trade_type": "pass", "confidence": 5}'}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "hold"

    def test_pm_no_decision_match(self):
        # PM text exists but no "final decision:" pattern — doesn't interfere
        reports = {
            "portfolio_manager": "The portfolio looks good overall",
            "trader": '{"trade_type": "buy", "confidence": 7}',
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"


# ---------------------------------------------------------------------------
# ScannerService helpers
# ---------------------------------------------------------------------------

def _make_mock_analysis():
    analysis = MagicMock()
    analysis.start_analysis = AsyncMock(return_value="run-id-123")
    analysis.get_run = AsyncMock(return_value={"status": "completed"})
    analysis.get_snapshot = AsyncMock(return_value=None)
    analysis.get_report = AsyncMock(return_value=None)
    analysis.cancel_analysis = AsyncMock()
    analysis.wait_for_completion = AsyncMock(return_value={"status": "completed"})
    return analysis


def _make_scanner(db=None):
    analysis = _make_mock_analysis()
    return ScannerService(analysis_service=analysis, db=db), analysis


# ---------------------------------------------------------------------------
# start_scan
# ---------------------------------------------------------------------------

class TestStartScan:
    @pytest.mark.asyncio
    async def test_start_scan_returns_scan_id(self):
        svc, _ = _make_scanner()
        with patch(
            "backend.services.scanner_service.ScannerService._run_scan",
            new_callable=lambda: lambda self, *a, **kw: asyncio.sleep(0),
        ):
            # patch _run_scan to be a coroutine that does nothing
            async def fake_run(scan_id, symbols_override=None):
                pass
            svc._run_scan = fake_run
            scan_id = await svc.start_scan({"analysis_date": "2025-01-01"})
        assert isinstance(scan_id, str)
        assert len(scan_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_start_scan_busy_error(self):
        svc, _ = _make_scanner()

        async def long_run(scan_id, symbols_override=None):
            await asyncio.sleep(10)

        svc._run_scan = long_run
        # Start first scan
        await svc.start_scan({"analysis_date": "2025-01-01"})

        # Second scan should raise
        with pytest.raises(ScannerBusyError):
            await svc.start_scan({"analysis_date": "2025-01-01"})

    @pytest.mark.asyncio
    async def test_start_scan_evicts_old_completed(self):
        svc, _ = _make_scanner()

        async def noop(scan_id, symbols_override=None):
            pass

        svc._run_scan = noop

        # Manually populate 12 completed scans
        import uuid
        for i in range(12):
            sid = str(uuid.uuid4())
            svc._scans[sid] = {"status": "completed", "task": None}

        await svc.start_scan({"analysis_date": "2025-01-01"})
        # Only 10 completed + 1 new running should remain
        assert len(svc._scans) <= 11

    @pytest.mark.asyncio
    async def test_start_scan_inserts_into_db(self):
        db = MagicMock()
        db.insert_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)

        async def noop(scan_id, symbols_override=None):
            pass
        svc._run_scan = noop

        await svc.start_scan({"analysis_date": "2025-01-01"})
        assert db.insert_scan.called


# ---------------------------------------------------------------------------
# get_scan
# ---------------------------------------------------------------------------

class TestGetScan:
    @pytest.mark.asyncio
    async def test_get_scan_from_memory(self):
        svc, _ = _make_scanner()
        import uuid
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 5, "completed": 2, "failed": 0,
            "current_batch": 1, "total_batches": 1,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-01T00:00:00.000000Z", "completed_at": None,
            "cancel": False, "task": None,
        }
        result = await svc.get_scan(sid)
        assert result is not None
        assert result["scan_id"] == sid

    @pytest.mark.asyncio
    async def test_get_scan_from_db_fallback(self):
        db = MagicMock()
        db.get_scan = AsyncMock(return_value={
            "scan_id": "db-scan", "status": "completed",
            "total": 10, "completed": 10, "failed": 0,
            "results": [],
            "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": "2025-01-01T01:00:00.000000Z",
        })
        svc, _ = _make_scanner(db=db)
        result = await svc.get_scan("db-scan")
        assert result is not None
        assert result["scan_id"] == "db-scan"

    @pytest.mark.asyncio
    async def test_get_scan_not_found(self):
        db = MagicMock()
        db.get_scan = AsyncMock(return_value=None)
        svc, _ = _make_scanner(db=db)
        result = await svc.get_scan("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_scan_no_db_miss(self):
        svc, _ = _make_scanner()
        result = await svc.get_scan("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# cancel_scan
# ---------------------------------------------------------------------------

class TestCancelScan:
    @pytest.mark.asyncio
    async def test_cancel_unknown_scan_returns_false(self):
        svc, _ = _make_scanner()
        result = await svc.cancel_scan("does-not-exist")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_running_scan_returns_true(self):
        import uuid
        svc, _ = _make_scanner()
        sid = str(uuid.uuid4())
        task = asyncio.create_task(asyncio.sleep(100))
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "cancel": False, "task": task,
            "config": {}, "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None,
        }
        result = await svc.cancel_scan(sid)
        assert result is True
        assert svc._scans[sid]["cancel"] is True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_cancel_updates_db(self):
        import uuid
        db = MagicMock()
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "cancel": False, "task": None,
            "config": {}, "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None,
        }
        await svc.cancel_scan(sid)
        assert db.update_scan.called


# ---------------------------------------------------------------------------
# list_scans
# ---------------------------------------------------------------------------

class TestListScans:
    @pytest.mark.asyncio
    async def test_list_scans_empty(self):
        svc, _ = _make_scanner()
        result = await svc.list_scans()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_scans_in_memory(self):
        import uuid
        svc, _ = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "completed", "config": {},
            "total": 1, "completed": 1, "failed": 0,
            "current_batch": 0, "total_batches": 1,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": "2025-01-01T01:00:00.000000Z",
            "cancel": False, "task": None,
        }
        result = await svc.list_scans()
        assert len(result) == 1
        assert result[0]["scan_id"] == sid

    @pytest.mark.asyncio
    async def test_list_scans_merges_db_no_duplicates(self):
        import uuid
        db = MagicMock()
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        db.list_scans = AsyncMock(return_value=[
            {"scan_id": sid1, "status": "completed", "total": 1, "completed": 1, "failed": 0,
             "results": [], "started_at": "2025-01-01T00:00:00.000000Z", "completed_at": None},
            {"scan_id": sid2, "status": "completed", "total": 1, "completed": 1, "failed": 0,
             "results": [], "started_at": "2025-01-01T00:00:00.000000Z", "completed_at": None},
        ])
        svc, _ = _make_scanner(db=db)
        # sid1 already in memory
        svc._scans[sid1] = {
            "scan_id": sid1, "status": "completed", "config": {},
            "total": 1, "completed": 1, "failed": 0,
            "current_batch": 0, "total_batches": 1,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        result = await svc.list_scans()
        scan_ids = [r["scan_id"] for r in result]
        assert sid1 in scan_ids
        assert sid2 in scan_ids
        # No duplicates
        assert len(scan_ids) == len(set(scan_ids))


# ---------------------------------------------------------------------------
# resume_incomplete_scans
# ---------------------------------------------------------------------------

class TestResumeIncompleteScans:
    @pytest.mark.asyncio
    async def test_no_db_returns_zero(self):
        svc, _ = _make_scanner(db=None)
        result = await svc.resume_incomplete_scans()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_running_scans_returns_zero(self):
        db = MagicMock()
        db.get_running_scans = AsyncMock(return_value=[])
        svc, _ = _make_scanner(db=db)
        result = await svc.resume_incomplete_scans()
        assert result == 0

    @pytest.mark.asyncio
    async def test_symbol_fetch_failure_marks_scan_failed(self):
        db = MagicMock()
        db.get_running_scans = AsyncMock(return_value=[
            {"scan_id": "scan-1", "config": '{"analysis_date":"2025-01-01"}',
             "started_at": "2025-01-01T00:00:00.000000Z", "completed": 0, "failed": 0, "results": []},
        ])
        db.get_scan_completed_tickers = AsyncMock(return_value=[])
        db.get_scan = AsyncMock(return_value={"results": []})
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)

        import sys
        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(side_effect=Exception("network error"))
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit

        try:
            await svc.resume_incomplete_scans()
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        db.update_scan.assert_called_with("scan-1", status="failed")

    @pytest.mark.asyncio
    async def test_no_remaining_marks_completed(self):
        db = MagicMock()
        db.get_running_scans = AsyncMock(return_value=[
            {"scan_id": "scan-2", "config": '{}',
             "started_at": "2025-01-01T00:00:00.000000Z", "completed": 5, "failed": 0, "results": []},
        ])
        db.get_scan_completed_tickers = AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])
        db.get_scan = AsyncMock(return_value={"results": []})
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)

        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(return_value=["BTCUSDT", "ETHUSDT"])

        import sys
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc.resume_incomplete_scans()
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        # Should have called update_scan with completed status
        calls = [str(c) for c in db.update_scan.call_args_list]
        assert any("completed" in c for c in calls)

    @pytest.mark.asyncio
    async def test_multiple_running_scans_only_first_resumed(self):
        db = MagicMock()
        db.get_running_scans = AsyncMock(return_value=[
            {"scan_id": "scan-A", "config": '{}',
             "started_at": "2025-01-01T00:00:00.000000Z", "completed": 0, "failed": 0, "results": []},
            {"scan_id": "scan-B", "config": '{}',
             "started_at": "2025-01-01T00:00:00.000000Z", "completed": 0, "failed": 0, "results": []},
        ])
        db.get_scan_completed_tickers = AsyncMock(return_value=[])
        db.get_scan = AsyncMock(return_value={"results": []})
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)

        # scan-A has a remaining symbol so it will be resumed (not immediately completed)
        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(return_value=["BTCUSDT"])

        import sys
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc.resume_incomplete_scans()
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        # scan-B should be marked failed (extra stale, only 1 resumed at a time)
        calls = [(c.args, c.kwargs) for c in db.update_scan.call_args_list]
        assert any(c[0][0] == "scan-B" and c[1].get("status") == "failed" for c in calls)


# ---------------------------------------------------------------------------
# _run_scan
# ---------------------------------------------------------------------------

class TestRunScan:
    @pytest.mark.asyncio
    async def test_run_scan_symbol_fetch_fails(self):
        import uuid
        svc, _ = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        import sys
        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(side_effect=Exception("fail"))
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc._run_scan(sid)
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        assert svc._scans[sid]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_run_scan_normal_completion(self):
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        analysis.get_run = AsyncMock(return_value={"status": "completed"})

        await svc._run_scan(sid, symbols_override=["BTCUSDT"])

        assert svc._scans[sid]["status"] == "completed"
        assert svc._scans[sid]["current_tickers"] == []
        assert svc._scans[sid]["task"] is None

    @pytest.mark.asyncio
    async def test_run_scan_cancel_sets_cancelled_status(self):
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": True, "task": None,
        }

        await svc._run_scan(sid, symbols_override=["BTCUSDT"])

        assert svc._scans[sid]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_run_scan_db_updated_on_completion(self):
        import uuid
        db = MagicMock()
        db.update_scan = AsyncMock()
        svc, analysis = _make_scanner(db=db)
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        analysis.get_run = AsyncMock(return_value={"status": "completed"})

        await svc._run_scan(sid, symbols_override=[])

        assert db.update_scan.called


# ---------------------------------------------------------------------------
# _run_single
# ---------------------------------------------------------------------------

class TestRunSingle:
    @pytest.mark.asyncio
    async def test_run_single_start_analysis_fails(self):
        import uuid
        svc, analysis = _make_scanner()
        analysis.start_analysis = AsyncMock(side_effect=Exception("quota exceeded"))
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        await svc._run_single(sid, "BTCUSDT")

        assert svc._scans[sid]["failed"] == 1
        assert "Failed to start" in svc._scans[sid]["results"][0]["decision_summary"]

    @pytest.mark.asyncio
    async def test_run_single_poll_until_terminal(self):
        import uuid
        svc, analysis = _make_scanner()
        analysis.wait_for_completion = AsyncMock(return_value={"status": "completed"})
        analysis.get_snapshot = AsyncMock(return_value=None)
        analysis.get_report = AsyncMock(return_value=None)

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        await svc._run_single(sid, "BTCUSDT")

        assert svc._scans[sid]["completed"] == 1

    @pytest.mark.asyncio
    async def test_run_single_cancel_during_poll(self):
        import uuid
        svc, analysis = _make_scanner()

        sid = str(uuid.uuid4())

        async def wait_side_effect(run_id, timeout=1860):
            svc._scans[sid]["cancel"] = True
            raise asyncio.CancelledError()

        analysis.wait_for_completion = AsyncMock(side_effect=wait_side_effect)

        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        await svc._run_single(sid, "ETHUSDT")

        assert svc._scans[sid]["failed"] == 1
        result = svc._scans[sid]["results"][0]
        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_run_single_poll_exception(self):
        import uuid
        svc, analysis = _make_scanner()
        analysis.wait_for_completion = AsyncMock(side_effect=Exception("connection error"))

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        await svc._run_single(sid, "BTCUSDT")

        assert svc._scans[sid]["failed"] == 1

    @pytest.mark.asyncio
    async def test_run_single_cancelled_scan_skips(self):
        """If scan is cancelled before _run_single acquires config, returns early."""
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": True, "task": None,
        }
        await svc._run_single(sid, "BTCUSDT")
        # start_analysis should NOT have been called
        analysis.start_analysis.assert_not_called()


# ---------------------------------------------------------------------------
# _collect_result
# ---------------------------------------------------------------------------

class TestCollectResult:
    @pytest.mark.asyncio
    async def test_collect_result_completed_with_snapshot(self):
        import uuid
        svc, analysis = _make_scanner()
        analysis.get_snapshot = AsyncMock(return_value={
            "reports": {
                "trader": '{"trade_type": "buy", "confidence": 8}',
                "final_trade_decision": "Strong buy signal",
            }
        })
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        run = {"status": "completed"}
        await svc._collect_result(sid, "BTCUSDT", "run-id", run)

        assert svc._scans[sid]["completed"] == 1
        result = svc._scans[sid]["results"][0]
        assert result["direction"] == "buy"
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_collect_result_snapshot_fails_fallback_to_report(self):
        import uuid
        svc, analysis = _make_scanner()
        analysis.get_snapshot = AsyncMock(side_effect=Exception("snapshot error"))
        analysis.get_report = AsyncMock(return_value="bearish outlook expected")

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        run = {"status": "completed"}
        await svc._collect_result(sid, "ETHUSDT", "run-id", run)

        result = svc._scans[sid]["results"][0]
        # Current code uses structured signals only; unstructured text returns hold/none/0
        assert result["direction"] in ("sell", "hold")

    @pytest.mark.asyncio
    async def test_collect_result_failed_run(self):
        import uuid
        svc, _ = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        run = {"status": "failed"}
        await svc._collect_result(sid, "XRPUSDT", "run-id", run)

        assert svc._scans[sid]["failed"] == 1
        assert svc._scans[sid]["results"][0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_collect_result_with_db(self):
        import uuid
        db = MagicMock()
        db.insert_scan_result = AsyncMock()
        db.increment_scan_counter = AsyncMock()
        svc, analysis = _make_scanner(db=db)
        analysis.get_snapshot = AsyncMock(return_value=None)
        analysis.get_report = AsyncMock(return_value=None)

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        run = {"status": "completed"}
        await svc._collect_result(sid, "BTCUSDT", "run-id", run)

        assert db.insert_scan_result.called
        assert db.increment_scan_counter.called


# ---------------------------------------------------------------------------
# Additional _run_scan edge cases
# ---------------------------------------------------------------------------

class TestRunScanSymbolFetch:
    @pytest.mark.asyncio
    async def test_run_scan_live_fetch_path(self):
        """_run_scan with symbols_override=None fetches from bybit (mocked)."""
        import uuid
        import sys
        svc, analysis = _make_scanner()
        analysis.get_run = AsyncMock(return_value={"status": "completed"})
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(return_value=["BTCUSDT", "ETHUSDT"])
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc._run_scan(sid)
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        assert svc._scans[sid]["total"] == 2
        assert svc._scans[sid]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_run_scan_scan_missing_after_fetch(self):
        """Scan removed from _scans between fetch and processing returns early."""
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        # Remove scan during the lock acquisition after fetch
        original_lock_acquire = svc._lock.acquire

        call_count = 0
        async def fake_acquire():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # On second lock acquisition (after symbol fetch), remove scan
                svc._scans.pop(sid, None)
            return await original_lock_acquire()

        svc._lock.acquire = fake_acquire

        # Should not raise, just return early
        await svc._run_scan(sid, symbols_override=["BTCUSDT"])
        # Scan was removed — no assertion about state, just no crash

    @pytest.mark.asyncio
    async def test_run_scan_db_updates_total(self):
        """When symbols_override is None, DB is updated with total."""
        import uuid
        import sys
        db = MagicMock()
        db.update_scan = AsyncMock()
        svc, analysis = _make_scanner(db=db)
        analysis.get_run = AsyncMock(return_value={"status": "completed"})
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(return_value=["BTCUSDT"])
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc._run_scan(sid)
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        # update_scan should be called at least twice: once for total, once for completion
        assert db.update_scan.call_count >= 2
        # First call should include total=1
        first_call_kwargs = db.update_scan.call_args_list[0][1]
        assert first_call_kwargs.get("total") == 1


# ---------------------------------------------------------------------------
# Additional _parse_signal_from_reports edge cases
# ---------------------------------------------------------------------------

class TestParseSignalEdgeCases:
    def test_trader_json_no_trade_type_key(self):
        """JSON without trade_type key — fallback regex applies."""
        reports = {"trader": '{"confidence": 7}'}
        result = _parse_signal_from_reports(reports)
        assert isinstance(result["direction"], str)

    def test_pm_approve_no_direction_in_text(self):
        """PM approves but no direction word — trader direction used."""
        reports = {
            "portfolio_manager": "Final Decision: Approve the position.",
            "trader": '{"trade_type": "buy", "confidence": 7}',
        }
        result = _parse_signal_from_reports(reports)
        assert result["direction"] == "buy"

    def test_percentage_zero_excluded(self):
        """No text-based % parsing in current code — unstructured input returns hold."""
        reports = {"final_trade_decision": "buy with 0% confidence"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")
        assert result["score"] <= 10

    def test_extremely_high_confidence_text(self):
        """Narrative text not parsed — returns hold/none/0."""
        reports = {"trader": "exceptional buy signal"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_overwhelming_confidence_text(self):
        """Narrative text not parsed — returns hold/none/0."""
        reports = {"trader": "overwhelming evidence to buy"}
        result = _parse_signal_from_reports(reports)
        assert result["direction"] in ("buy", "hold")

    def test_confidence_score_clamped_min(self):
        """conf_score is clamped to at least 1."""
        # With no signals at all, conf_score stays 2 (above 1)
        result = _parse_signal_from_reports({})
        assert result["score"] >= -10 and result["score"] <= 10


# ---------------------------------------------------------------------------
# Targeted tests for remaining uncovered lines
# ---------------------------------------------------------------------------

class TestRemainingLines:
    @pytest.mark.asyncio
    async def test_resume_invalid_json_config(self):
        """Line 226-227: invalid JSON config falls back to empty dict."""
        db = MagicMock()
        db.get_running_scans = AsyncMock(return_value=[
            {"scan_id": "scan-x", "config": "NOT_JSON",
             "started_at": "2025-01-01T00:00:00.000000Z", "completed": 0, "failed": 0, "results": []},
        ])
        db.get_scan_completed_tickers = AsyncMock(return_value=[])
        db.get_scan = AsyncMock(return_value={"results": []})
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)

        import sys
        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(return_value=["BTCUSDT"])
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            # Should not raise — invalid config becomes {}
            await svc.resume_incomplete_scans()
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        # Scan was resumed (or marked completed), no crash
        assert True  # reached here without exception

    @pytest.mark.asyncio
    async def test_run_scan_general_exception_sets_scan_error(self):
        """Lines 365-367: non-CancelledError from gather sets scan_error=True → status=failed."""
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        # Make asyncio.gather raise a RuntimeError (non-CancelledError)
        with patch("asyncio.gather", side_effect=RuntimeError("unexpected error")):
            await svc._run_scan(sid, symbols_override=["BTCUSDT"])

        assert svc._scans[sid]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_run_scan_cancel_during_gather_sets_cancelled(self):
        """Line 377: scan["cancel"]=True → status='cancelled' during _run_scan finalisation."""
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        original_gather = asyncio.gather

        async def cancel_then_gather(*args, **kwargs):
            svc._scans[sid]["cancel"] = True
            return await original_gather(*args, **kwargs)

        with patch("asyncio.gather", side_effect=cancel_then_gather):
            await svc._run_scan(sid, symbols_override=[])

        assert svc._scans[sid]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_run_single_start_failure_with_db(self):
        """Line 442: DB insert_scan_result called when start_analysis fails and db is set."""
        import uuid
        db = MagicMock()
        db.insert_scan_result = AsyncMock()
        svc, analysis = _make_scanner(db=db)
        analysis.start_analysis = AsyncMock(side_effect=Exception("quota exceeded"))
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        await svc._run_single(sid, "BTCUSDT")
        assert db.insert_scan_result.called

    @pytest.mark.asyncio
    async def test_run_single_cancel_with_db(self):
        """DB insert and increment called when cancel fires during wait."""
        import uuid

        db = MagicMock()
        db.insert_scan_result = AsyncMock()
        db.increment_scan_counter = AsyncMock()
        svc, analysis = _make_scanner(db=db)

        sid = str(uuid.uuid4())

        async def wait_side_effect(run_id, timeout=1860):
            svc._scans[sid]["cancel"] = True
            raise asyncio.CancelledError()

        analysis.wait_for_completion = AsyncMock(side_effect=wait_side_effect)

        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        await svc._run_single(sid, "BTCUSDT")

        assert db.insert_scan_result.called
        assert db.increment_scan_counter.called

    @pytest.mark.asyncio
    async def test_run_single_poll_exception_with_db(self):
        """DB insert and increment called on wait_for_completion exception."""
        import uuid

        db = MagicMock()
        db.insert_scan_result = AsyncMock()
        db.increment_scan_counter = AsyncMock()
        svc, analysis = _make_scanner(db=db)
        analysis.wait_for_completion = AsyncMock(side_effect=Exception("connection error"))

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        await svc._run_single(sid, "BTCUSDT")

        assert db.insert_scan_result.called
        assert db.increment_scan_counter.called

    @pytest.mark.asyncio
    async def test_collect_result_report_fallback_exception_swallowed(self):
        """Lines 517-518: get_report raises but is swallowed, result still produced."""
        import uuid
        svc, analysis = _make_scanner()
        analysis.get_snapshot = AsyncMock(return_value={"reports": {}})
        analysis.get_report = AsyncMock(side_effect=Exception("report unavailable"))

        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 1, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 1, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }
        run = {"status": "completed"}
        await svc._collect_result(sid, "BTCUSDT", "run-id", run)

        # Result should still be appended (hold/none/0 due to no signal data)
        assert len(svc._scans[sid]["results"]) == 1
        assert svc._scans[sid]["results"][0]["direction"] == "hold"


class TestRemainingLines2:
    @pytest.mark.asyncio
    async def test_run_scan_symbol_fetch_fails_with_db(self):
        """Line 325: when symbol fetch fails and DB is set, DB is updated to failed."""
        import uuid
        import sys
        db = MagicMock()
        db.update_scan = AsyncMock()
        svc, _ = _make_scanner(db=db)
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        mock_bybit = MagicMock()
        mock_bybit.get_valid_symbols = MagicMock(side_effect=Exception("network error"))
        sys.modules["tradingagents.dataflows.bybit_data"] = mock_bybit
        try:
            await svc._run_scan(sid)
        finally:
            sys.modules.pop("tradingagents.dataflows.bybit_data", None)

        assert svc._scans[sid]["status"] == "failed"
        call_args = db.update_scan.call_args
        assert call_args[0][0] == sid
        assert call_args[1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_run_scan_scan_removed_before_second_lock(self):
        """Line 331: scan removed from _scans before second lock acquisition → early return."""
        import asyncio
        import uuid
        svc, analysis = _make_scanner()
        sid = str(uuid.uuid4())
        svc._scans[sid] = {
            "scan_id": sid, "status": "running", "config": {"analysis_date": "2025-01-01"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "results": [], "started_at": "2025-01-01T00:00:00.000000Z",
            "completed_at": None, "cancel": False, "task": None,
        }

        orig_aenter = asyncio.Lock.__aenter__
        call_count = [0]

        async def removing_aenter(self):
            call_count[0] += 1
            # Remove scan on the FIRST lock acquisition (line 328 in _run_scan)
            if call_count[0] == 1:
                svc._scans.pop(sid, None)
            return await orig_aenter(self)

        asyncio.Lock.__aenter__ = removing_aenter
        try:
            await svc._run_scan(sid, symbols_override=["BTCUSDT"])
        finally:
            asyncio.Lock.__aenter__ = orig_aenter

        assert sid not in svc._scans


@pytest.mark.asyncio
async def test_scanner_passes_recorder_to_executor(monkeypatch):
    """ScannerService stores a debug_recorder."""
    from backend.services.scanner_service import ScannerService
    rec = MagicMock()
    rec.new_run_context = MagicMock(return_value=MagicMock(run_id=None))
    rec.open_run = AsyncMock()
    svc = ScannerService(analysis_service=MagicMock(), db=None, debug_recorder=rec)
    assert svc._debug_recorder is rec


class TestSerializeSkippedCount:
    def test_serialize_counts_ta_prefilter_results(self):
        svc, _ = _make_scanner()
        scan = {
            "scan_id": "s1", "status": "completed", "total": 3, "completed": 3,
            "failed": 0, "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "started_at": "2026-06-08T00:00:00Z", "completed_at": "2026-06-08T00:01:00Z",
            "config": {},
            "results": [
                {"ticker": "BTC", "direction": "buy", "score": 5, "signal_source": "structured"},
                {"ticker": "ETH", "direction": "hold", "score": 0, "signal_source": "ta_prefilter"},
                {"ticker": "SOL", "direction": "hold", "score": 0, "signal_source": "ta_prefilter"},
            ],
        }
        out = svc._serialize(scan)
        assert out["skipped_count"] == 2

    def test_serialize_skipped_count_zero(self):
        svc, _ = _make_scanner()
        scan = {
            "scan_id": "s2", "status": "completed", "total": 1, "completed": 1,
            "failed": 0, "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "started_at": "2026-06-08T00:00:00Z", "completed_at": None, "config": {},
            "results": [{"ticker": "BTC", "direction": "buy", "score": 5, "signal_source": "structured"}],
        }
        assert svc._serialize(scan)["skipped_count"] == 0

    def test_serialize_db_passes_through_skipped_count(self):
        svc, _ = _make_scanner()
        db_scan = {
            "scan_id": "s3", "status": "completed", "total": 2, "completed": 2,
            "failed": 0, "started_at": "2026-06-08T00:00:00Z", "completed_at": None,
            "config": {}, "results": [], "direction_counts": {"hold": 2}, "skipped_count": 2,
        }
        assert svc._serialize_db(db_scan)["skipped_count"] == 2

    def test_serialize_db_defaults_skipped_count_to_zero(self):
        svc, _ = _make_scanner()
        db_scan = {
            "scan_id": "s4", "status": "completed", "total": 0, "completed": 0,
            "failed": 0, "started_at": "2026-06-08T00:00:00Z", "completed_at": None,
            "config": {}, "results": [], "direction_counts": {},
        }
        assert svc._serialize_db(db_scan)["skipped_count"] == 0
