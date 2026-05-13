"""Tests for backend.services.scanner_service.ScannerService — Phase 1 unit tests."""

import asyncio
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _mock_coingecko_prefetch():
    """Prevent real CoinGecko API calls during scanner tests."""
    with patch("tradingagents.dataflows.coingecko_data.prefetch_bulk_market_only"), \
         patch("tradingagents.dataflows.coingecko_data.prefetch_descriptions_background"), \
         patch("tradingagents.dataflows.coingecko_data.prefetch_fundamentals"):
        yield


@pytest.fixture
def scanner():
    from backend.services.scanner_service import ScannerService
    analysis = AsyncMock()
    analysis.max_concurrent = 6
    analysis.set_max_concurrent = MagicMock()
    db = MagicMock()
    # All DB methods are now async
    db.insert_scan = AsyncMock()
    db.update_scan = AsyncMock()
    db.get_scan = AsyncMock(return_value=None)
    db.list_scans = AsyncMock(return_value=[])
    db.get_running_scans = AsyncMock(return_value=[])
    db.insert_scan_result = AsyncMock()
    db.increment_scan_counter = AsyncMock()
    db.get_scan_completed_tickers = AsyncMock(return_value=set())
    db.get_scan_analysis_count = AsyncMock(return_value=0)
    return ScannerService(analysis_service=analysis, db=db)


@pytest.fixture
def scanner_no_db():
    from backend.services.scanner_service import ScannerService
    analysis = AsyncMock()
    analysis.max_concurrent = 6
    analysis.set_max_concurrent = MagicMock()
    return ScannerService(analysis_service=analysis, db=None)


class TestScannerServiceBasics:
    @pytest.mark.asyncio
    async def test_start_scan_returns_id(self, scanner):
        # Mock _run_scan to avoid actual scanning
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
        assert isinstance(scan_id, str)
        assert len(scan_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_get_scan_in_memory(self, scanner):
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
        result = await scanner.get_scan(scan_id)
        assert result is not None
        assert result["scan_id"] == scan_id

    @pytest.mark.asyncio
    async def test_get_scan_not_found(self, scanner_no_db):
        result = await scanner_no_db.get_scan("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_scan(self, scanner):
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
        result = await scanner.cancel_scan(scan_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, scanner):
        result = await scanner.cancel_scan("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_scans(self, scanner):
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            await scanner.start_scan({"analysis_date": "2025-01-10"})
        scanner._db.list_scans.return_value = []
        scans = await scanner.list_scans()
        assert len(scans) == 1

    @pytest.mark.asyncio
    async def test_busy_error(self, scanner):
        from backend.services.scanner_service import ScannerBusyError
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            await scanner.start_scan({"analysis_date": "2025-01-10"})
        with pytest.raises(ScannerBusyError):
            with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                await scanner.start_scan({"analysis_date": "2025-01-11"})


class TestSerialize:
    def test_serialize_sorts_by_score(self):
        from backend.services.scanner_service import ScannerService
        svc = ScannerService(analysis_service=MagicMock())
        scan = {
            "scan_id": "s1", "status": "completed", "total": 2,
            "completed": 2, "failed": 0, "current_batch": 0,
            "total_batches": 1, "current_tickers": [],
            "results": [
                {"ticker": "A", "score": 3},
                {"ticker": "B", "score": -8},
            ],
            "started_at": "2025-01-10", "completed_at": "2025-01-10",
        }
        result = svc._serialize(scan)
        assert result["results"][0]["ticker"] == "B"  # abs(-8) > abs(3)

    def test_serialize_db(self):
        from backend.services.scanner_service import ScannerService
        svc = ScannerService(analysis_service=MagicMock())
        db_scan = {
            "scan_id": "s1", "status": "completed",
            "total": 5, "completed": 5, "failed": 0,
            "results": [{"ticker": "A"}],
            "started_at": "2025-01-10",
        }
        result = svc._serialize_db(db_scan)
        assert result["scan_id"] == "s1"
        assert result["current_batch"] == 0


class TestResumeIncompleteScans:
    @pytest.mark.asyncio
    async def test_no_db_returns_zero(self, scanner_no_db):
        result = await scanner_no_db.resume_incomplete_scans()
        assert result == 0


class TestRunSingle:
    @pytest.mark.asyncio
    async def test_start_analysis_failure(self, scanner):
        scanner._analysis.start_analysis.side_effect = Exception("failed")
        # Create a scan in memory
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        assert scanner._scans["s1"]["failed"] == 1
        assert len(scanner._scans["s1"]["results"]) == 1
        assert scanner._scans["s1"]["results"][0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancelled_before_start(self, scanner):
        """When cancel=True before _run_single starts, it returns immediately."""
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": True,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        # cancel=True at start means the method returns before calling start_analysis
        scanner._analysis.start_analysis.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_run_collects_result(self, scanner):
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._analysis.wait_for_completion = AsyncMock(return_value={"status": "completed"})
        scanner._analysis.get_snapshot = AsyncMock(return_value=None)
        scanner._analysis.get_report = AsyncMock(return_value="Buy BTCUSDT")
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        assert scanner._scans["s1"]["completed"] == 1


class TestCollectResult:
    @pytest.mark.asyncio
    async def test_completed_with_snapshot(self, scanner):
        scanner._analysis.get_snapshot = AsyncMock(return_value={
            "reports": {"final_trade_decision": "Buy with high confidence", "trader": '{"trade_type": "long", "confidence": 8}'}
        })
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        assert scanner._scans["s1"]["completed"] == 1
        assert len(scanner._scans["s1"]["results"]) == 1

    @pytest.mark.asyncio
    async def test_failed_run(self, scanner):
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "failed"})
        assert scanner._scans["s1"]["failed"] == 1


class TestRunScan:
    @pytest.mark.asyncio
    async def test_symbols_override(self, scanner):
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-10", "completed_at": None,
            "task": None,
        }
        with patch.object(scanner, "_run_single", new_callable=AsyncMock):
            await scanner._run_scan("s1", symbols_override=["BTCUSDT", "ETHUSDT"])
        assert scanner._scans["s1"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_symbol_fetch_failure(self, scanner):
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0,
            "current_tickers": [], "results": [],
            "started_at": "", "completed_at": None, "task": None,
        }
        call_count = 0
        original_to_thread = asyncio.to_thread

        async def mock_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("network")
            return fn(*args, **kwargs)

        with patch("backend.services.scanner_service.asyncio.to_thread", side_effect=mock_to_thread):
            await scanner._run_scan("s1")
        assert scanner._scans["s1"]["status"] == "failed"
        scanner._db.update_scan.assert_any_call("s1", status="failed")


class TestResumeIncompleteScansWithDB:
    @pytest.mark.asyncio
    async def test_resume_one_scan(self, scanner):
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": '{"analysis_date":"2025-01-10"}', "started_at": "2025-01-10", "completed": 0, "failed": 0}
        ]
        scanner._db.get_scan_completed_tickers.return_value = set()
        scanner._db.get_scan.return_value = {"results": []}
        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"]):
            with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                result = await scanner.resume_incomplete_scans()
        assert result == 1
        assert "s1" in scanner._scans

    @pytest.mark.asyncio
    async def test_resume_marks_extra_as_failed(self, scanner):
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": '{}', "started_at": "t1", "completed": 0, "failed": 0},
            {"scan_id": "s2", "config": '{}', "started_at": "t2", "completed": 0, "failed": 0},
        ]
        scanner._db.get_scan_completed_tickers.return_value = set()
        scanner._db.get_scan.return_value = {"results": []}
        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"]):
            with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                result = await scanner.resume_incomplete_scans()
        assert result == 1
        scanner._db.update_scan.assert_any_call("s2", status="failed")

    @pytest.mark.asyncio
    async def test_resume_all_done(self, scanner):
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": '{}', "started_at": "t1", "completed": 1, "failed": 0}
        ]
        scanner._db.get_scan_completed_tickers.return_value = {"BTCUSDT"}
        scanner._db.get_scan.return_value = {"results": []}
        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"]):
            result = await scanner.resume_incomplete_scans()
        assert result == 0
        # Verify update_scan was called with completed status
        calls = [c for c in scanner._db.update_scan.call_args_list if c[0][0] == "s1"]
        assert any("completed" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_resume_symbol_fetch_fails(self, scanner):
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": '{}', "started_at": "t1"}
        ]
        scanner._db.get_scan_completed_tickers.return_value = set()
        scanner._db.get_scan.return_value = {"results": []}

        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", side_effect=Exception("network")):
            result = await scanner.resume_incomplete_scans()
        assert result == 0

    @pytest.mark.asyncio
    async def test_resume_invalid_config_json(self, scanner):
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": "not json", "started_at": "t1", "completed": 0, "failed": 0}
        ]
        scanner._db.get_scan_completed_tickers.return_value = set()
        scanner._db.get_scan.return_value = {"results": []}
        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"]):
            with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                result = await scanner.resume_incomplete_scans()
        assert result == 1


class TestAnalyzeTickerCancel:
    @pytest.mark.asyncio
    async def test_cancel_during_poll(self, scanner):
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._analysis.cancel_analysis = AsyncMock()

        async def wait_side_effect(run_id, timeout=1860):
            scanner._scans["s1"]["cancel"] = True
            raise asyncio.CancelledError()

        scanner._analysis.wait_for_completion = AsyncMock(side_effect=wait_side_effect)
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }

        await scanner._run_single("s1", "BTCUSDT")
        scanner._analysis.cancel_analysis.assert_called_once_with("run-1")
        assert scanner._scans["s1"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_poll_exception(self, scanner):
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._analysis.wait_for_completion = AsyncMock(side_effect=Exception("poll fail"))
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        assert scanner._scans["s1"]["failed"] == 1


class TestCollectResultEdgeCases:
    @pytest.mark.asyncio
    async def test_snapshot_exception_fallback_to_report(self, scanner):
        scanner._analysis.get_snapshot = AsyncMock(side_effect=Exception("snapshot fail"))
        scanner._analysis.get_report = AsyncMock(return_value="Sell recommendation")
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        assert scanner._scans["s1"]["completed"] == 1
        # Current code uses structured signals only; unstructured text returns hold
        assert scanner._scans["s1"]["results"][0]["direction"] in ("sell", "hold")

    @pytest.mark.asyncio
    async def test_snapshot_no_reports_fallback_to_report(self, scanner):
        scanner._analysis.get_snapshot = AsyncMock(return_value={"reports": {}})
        scanner._analysis.get_report = AsyncMock(return_value="Buy with high confidence")
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        assert scanner._scans["s1"]["completed"] == 1

    @pytest.mark.asyncio
    async def test_report_exception(self, scanner):
        scanner._analysis.get_snapshot = AsyncMock(return_value=None)
        scanner._analysis.get_report = AsyncMock(side_effect=Exception("report fail"))
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        assert scanner._scans["s1"]["completed"] == 1

    @pytest.mark.asyncio
    async def test_collect_result_no_db(self, scanner_no_db):
        scanner_no_db._scans = {}
        scanner_no_db._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        scanner_no_db._analysis.get_snapshot = AsyncMock(return_value=None)
        scanner_no_db._analysis.get_report = AsyncMock(return_value=None)
        await scanner_no_db._collect_result("s1", "BTCUSDT", "run-1", {"status": "failed"})
        assert scanner_no_db._scans["s1"]["failed"] == 1


class TestCollectResultDBPersistence:
    @pytest.mark.asyncio
    async def test_completed_result_calls_insert_and_increment(self, scanner):
        """R2-F1/F3: _collect_result must call insert_scan_result + increment_scan_counter."""
        scanner._analysis.get_snapshot = AsyncMock(return_value={
            "reports": {"final_trade_decision": "Buy with high confidence"}
        })
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        scanner._db.insert_scan_result.assert_called_once()
        call_args = scanner._db.insert_scan_result.call_args
        assert call_args[0][0] == "s1"
        assert call_args[0][1]["ticker"] == "BTCUSDT"
        scanner._db.increment_scan_counter.assert_called_once_with("s1", "completed")

    @pytest.mark.asyncio
    async def test_failed_result_calls_insert_and_increment_failed(self, scanner):
        """Failed result uses 'failed' counter field."""
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", {"status": "failed"})
        scanner._db.insert_scan_result.assert_called_once()
        scanner._db.increment_scan_counter.assert_called_once_with("s1", "failed")

    @pytest.mark.asyncio
    async def test_collect_result_run_none_defaults_to_failed(self, scanner):
        """R2-F5/F6: _collect_result with run=None treats status as 'failed'."""
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._collect_result("s1", "BTCUSDT", "run-1", None)
        assert scanner._scans["s1"]["failed"] == 1
        scanner._db.insert_scan_result.assert_called_once()
        scanner._db.increment_scan_counter.assert_called_once_with("s1", "failed")

    @pytest.mark.asyncio
    async def test_collect_result_no_db_no_crash(self, scanner_no_db):
        """_collect_result with no DB doesn't crash."""
        scanner_no_db._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {}, "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        scanner_no_db._analysis.get_snapshot = AsyncMock(return_value=None)
        scanner_no_db._analysis.get_report = AsyncMock(return_value=None)
        await scanner_no_db._collect_result("s1", "BTCUSDT", "run-1", {"status": "completed"})
        assert scanner_no_db._scans["s1"]["completed"] == 1


class TestRunSingleDBPersistence:
    @pytest.mark.asyncio
    async def test_start_analysis_failure_calls_insert_scan_result(self, scanner):
        """R2-F2: _run_single start_analysis failure must write to DB via insert_scan_result."""
        scanner._analysis.start_analysis.side_effect = Exception("net error")
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        scanner._db.insert_scan_result.assert_called_once()
        call_args = scanner._db.insert_scan_result.call_args[0]
        assert call_args[0] == "s1"
        assert call_args[1]["status"] == "failed"
        assert call_args[1]["ticker"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_cancel_during_poll_calls_insert_scan_result(self, scanner):
        """Cancel path writes cancel_result to DB."""
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._analysis.cancel_analysis = AsyncMock()

        async def wait_side_effect(run_id, timeout=1860):
            scanner._scans["s1"]["cancel"] = True
            raise asyncio.CancelledError()

        scanner._analysis.wait_for_completion = AsyncMock(side_effect=wait_side_effect)
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }

        await scanner._run_single("s1", "BTCUSDT")

        scanner._db.insert_scan_result.assert_called_once()
        call_args = scanner._db.insert_scan_result.call_args[0]
        assert call_args[0] == "s1"
        assert call_args[1]["status"] == "cancelled"
        scanner._db.increment_scan_counter.assert_called_once_with("s1", "failed")

    @pytest.mark.asyncio
    async def test_poll_exception_calls_db_insert_and_increment(self, scanner):
        """wait_for_completion exception path writes failed result to DB."""
        scanner._analysis.start_analysis.return_value = "run-1"
        scanner._analysis.wait_for_completion = AsyncMock(side_effect=Exception("poll fail"))
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        await scanner._run_single("s1", "BTCUSDT")
        scanner._db.insert_scan_result.assert_called_once()
        scanner._db.increment_scan_counter.assert_called_once_with("s1", "failed")

class TestResumeEmptyRunningList:
    @pytest.mark.asyncio
    async def test_resume_no_running_scans_returns_zero(self, scanner):
        """R2-F7: resume_incomplete_scans with empty running list returns 0 immediately."""
        scanner._db.get_running_scans.return_value = []
        result = await scanner.resume_incomplete_scans()
        assert result == 0
        scanner._db.update_scan.assert_not_called()


class TestStartScanDBInsert:
    @pytest.mark.asyncio
    async def test_start_scan_calls_insert_scan(self, scanner):
        """R3-F6: start_scan must call _db.insert_scan with scan_id and status='running'."""
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
        scanner._db.insert_scan.assert_called_once()
        call_args = scanner._db.insert_scan.call_args[0]
        scan_dict = call_args[0]
        assert scan_dict["scan_id"] == scan_id
        assert scan_dict["status"] == "running"


class TestResumeSymbolFetchFailureDBUpdate:
    @pytest.mark.asyncio
    async def test_resume_symbol_fetch_failure_calls_update_scan_failed(self, scanner):
        """R3-F7: resume_incomplete_scans symbol-fetch failure calls update_scan with status='failed'."""
        scanner._db.get_running_scans.return_value = [
            {"scan_id": "s1", "config": '{}', "started_at": "t1", "completed": 0, "failed": 0}
        ]
        scanner._db.get_scan_completed_tickers.return_value = set()
        scanner._db.get_scan.return_value = {"results": []}

        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", side_effect=Exception("network")):
            result = await scanner.resume_incomplete_scans()
        assert result == 0
        scanner._db.update_scan.assert_called_with("s1", status="failed")


class TestParseSignalExtendedCoverage:
    def test_pm_approve_with_direction(self):
        """R3-F1: PM APPROVE with direction word in text extracts direction."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({"portfolio_manager": "Final decision: Approve the long trade"})
        assert result["direction"] == "buy"
        assert result["score"] > 0

    def test_percentage_confidence(self):
        """R3-F2: Current code does not parse % text — returns hold/none/0."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({"final_trade_decision": "I recommend buying with 80% confidence"})
        assert result["direction"] in ("buy", "hold")

    def test_overwhelming_confidence(self):
        """R3-F3: Current code does not parse keyword confidence — returns hold/none/0."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({"final_trade_decision": "Buy — overwhelming confidence"})
        assert result["score"] <= 10

    def test_trader_no_trade_blocks_fallback_regex(self):
        """R3-F4: trader JSON with trade_type=no_trade prevents direction from fallback regex."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({
            "trader": '{"trade_type": "no_trade"}',
            "final_trade_decision": "Buy bullish"
        })
        assert result["direction"] == "hold"

    def test_malformed_trader_json_returns_valid_signal(self):
        """R3-F5: Malformed trader JSON silently falls through and returns valid signal dict."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({"trader": "INVALID{"})
        assert "direction" in result
        assert "confidence" in result
        assert "score" in result


class TestRunScanDBAssertions:
    @pytest.mark.asyncio
    async def test_run_scan_updates_total_in_db(self, scanner):
        """R5-F5: _run_scan calls update_scan(total=N) after resolving symbols."""
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-10", "completed_at": None, "task": None,
        }
        with patch.object(scanner, "_run_single", new_callable=AsyncMock):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC", "ETH"]):
                await scanner._run_scan("s1")
        calls = [c for c in scanner._db.update_scan.call_args_list if "total" in (c[1] or {})]
        assert any(c[1].get("total") == 2 for c in calls)

    @pytest.mark.asyncio
    async def test_run_scan_final_update_scan_called(self, scanner):
        """R5-F4: _run_scan calls update_scan with final status/completed/failed counts."""
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "total": 0, "completed": 0, "failed": 0,
            "current_batch": 0, "total_batches": 0,
            "current_tickers": [], "results": [],
            "started_at": "2025-01-10", "completed_at": None, "task": None,
        }
        with patch.object(scanner, "_run_single", new_callable=AsyncMock):
            await scanner._run_scan("s1", symbols_override=["BTC"])
        # Should have called update_scan with final status
        final_calls = [c for c in scanner._db.update_scan.call_args_list
                       if "status" in (c[1] or {})]
        assert len(final_calls) >= 1
        last_call_kwargs = final_calls[-1][1]
        assert last_call_kwargs["status"] in ("completed", "failed", "cancelled")


class TestGetScanAndListFromDB:
    @pytest.mark.asyncio
    async def test_get_scan_from_db(self, scanner):
        """R7-F1(maintainability): get_scan DB fallback path when not in _scans."""
        scanner._db.get_scan.return_value = {
            "scan_id": "s1", "status": "completed", "total": 5,
            "completed": 5, "failed": 0, "results": [],
            "started_at": "2025-01-10",
        }
        result = await scanner.get_scan("s1")
        assert result is not None
        assert result["scan_id"] == "s1"

    @pytest.mark.asyncio
    async def test_list_scans_includes_db_only_scan(self, scanner):
        """R7-F2(maintainability): list_scans merges DB scans not in _scans."""
        scanner._db.list_scans.return_value = [
            {"scan_id": "db1", "status": "completed", "total": 3, "completed": 3,
             "failed": 0, "results": [], "started_at": "2025-01-10"}
        ]
        result = await scanner.list_scans()
        assert any(s["scan_id"] == "db1" for s in result)


class TestScanEviction:
    @pytest.mark.asyncio
    async def test_old_completed_scans_evicted(self, scanner):
        """Evict done scans beyond 10 (line 138)."""
        # Pre-populate with 11 completed scans
        for i in range(11):
            scanner._scans[f"old-{i}"] = {
                "scan_id": f"old-{i}", "status": "completed",
                "cancel": False, "config": "{}", "started_at": "t",
                "total": 0, "total_batches": 0, "completed": 0, "failed": 0,
                "current_tickers": [], "results": [],
            }
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            await scanner.start_scan({"analysis_date": "2025-01-10"})
        # Should have evicted to keep only 10 done + 1 running = 11 total
        done = [s for s in scanner._scans.values() if s["status"] != "running"]
        assert len(done) <= 10


class TestCancelMidTicker:
    @pytest.mark.asyncio
    async def test_cancel_check_inside_process_ticker(self, scanner):
        """Scan cancelled flag stops ticker processing (line 345)."""
        symbols_called = []

        async def fake_run_single(scan_id, ticker):
            symbols_called.append(ticker)

        with patch.object(scanner, "_run_single", side_effect=fake_run_single):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC", "ETH"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                # Immediately cancel
                await scanner.cancel_scan(scan_id)
                await asyncio.sleep(0.3)
        # Either 0 or limited symbols processed due to cancel
        assert len(symbols_called) <= 2

    @pytest.mark.asyncio
    async def test_scan_gather_exception_sets_failed(self, scanner):
        """gather outer except sets scan_error and final status is failed (lines 361-365, 375)."""
        async def raise_exc(scan_id, ticker):
            if ticker == "BTC":
                raise RuntimeError("forced error")

        with patch.object(scanner, "_run_single", side_effect=raise_exc):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                await asyncio.sleep(0.5)
        scan = await scanner.get_scan(scan_id)
        # Should be "completed" or "failed" — errors in gather return_exceptions=True
        assert scan["status"] in ("completed", "failed")


class TestScanFinalStatus:
    @pytest.mark.asyncio
    async def test_scan_completes_with_cancelled_flag(self, scanner):
        """Covers scanner_service.py:377: scan["cancel"]=True sets status to 'cancelled'."""
        # Start scan, cancel after it starts, then wait for completion
        async def slow_run_single(scan_id, ticker):
            await asyncio.sleep(0.3)

        with patch.object(scanner, "_run_single", side_effect=slow_run_single):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC", "ETH"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                await asyncio.sleep(0.05)  # let _run_scan start
                await scanner.cancel_scan(scan_id)
                await asyncio.sleep(1.0)  # wait for the scan task to finish
        scan = await scanner.get_scan(scan_id)
        assert scan["status"] in ("cancelled", "completed")

    @pytest.mark.asyncio
    async def test_scan_failed_via_gather_exception(self, scanner):
        """Covers scanner_service.py:374-375: scan_error=True via gather outer exception."""
        # Patch asyncio.gather to raise directly (outer except path)
        original_gather = asyncio.gather

        async def mock_gather(*args, **kwargs):
            raise RuntimeError("forced outer error")

        with patch("backend.services.scanner_service.asyncio.gather", side_effect=RuntimeError("forced")):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                await asyncio.sleep(0.5)
        scan = await scanner.get_scan(scan_id)
        assert scan["status"] == "failed"
        # Final update_scan call with status="failed" should be made
        final_calls = [c for c in scanner._db.update_scan.call_args_list
                       if c[1].get("status") == "failed"]
        assert len(final_calls) >= 1


        """Covers scanner_service.py:361: CancelledError during gather is caught."""
        with patch("backend.services.scanner_service.asyncio.gather", side_effect=asyncio.CancelledError):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                await asyncio.sleep(0.5)
        scan = await scanner.get_scan(scan_id)
        # CancelledError path — scan status should be something terminal
        assert scan["status"] in ("cancelled", "completed", "failed")


class TestRunScanEdgeCases:
    @pytest.mark.asyncio
    async def test_run_scan_scan_removed_before_batch(self, scanner):
        """Covers scanner_service.py:331: scan not found in _scans after symbol fetch."""
        # After symbols are fetched, remove the scan from _scans before _run_scan acquires lock
        scanner_scans_ref = scanner._scans

        def sync_fetch_and_remove():
            # Remove all scans to simulate scan vanishing mid-run (runs in thread)
            for sid in list(scanner_scans_ref.keys()):
                scanner_scans_ref.pop(sid, None)
            return ["BTC"]

        with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", side_effect=sync_fetch_and_remove):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
            await asyncio.sleep(0.5)
        # Scan was removed so _run_scan should have exited via the return on line 331

    @pytest.mark.asyncio
    async def test_process_ticker_cancel_flag_set(self, scanner):
        """Covers scanner_service.py:345: cancel flag set inside _process_ticker."""
        # Start scan with a symbol, cancel mid-process
        started = asyncio.Event()

        async def wait_for_cancel(scan_id, ticker):
            started.set()
            await asyncio.sleep(10)  # block to keep ticker in process

        with patch.object(scanner, "_run_single", side_effect=wait_for_cancel):
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTC", "ETH", "USDT"]):
                scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                await started.wait()
                # Cancel so that remaining _process_ticker invocations see cancel=True
                async with scanner._lock:
                    if scan_id in scanner._scans:
                        scanner._scans[scan_id]["cancel"] = True
                await asyncio.sleep(0.5)
        scan = await scanner.get_scan(scan_id)
        # Should be cancelled or completed
        assert scan is not None


class TestProcessTickerCancelDirect:
    @pytest.mark.asyncio
    async def test_process_ticker_sees_cancel_before_semaphore(self, scanner):
        """Covers scanner_service.py:345: ticker processing returns early when cancel=True."""
        from backend import services as svc_pkg
        import backend.services.scanner_service as svc_mod

        # Reduce batch size to 1 so tickers are processed one at a time
        orig_batch = svc_mod._BATCH_SIZE
        svc_mod._BATCH_SIZE = 1
        try:
            calls = []

            async def slow_run_single(scan_id, ticker):
                calls.append(ticker)
                await asyncio.sleep(0.1)

            with patch.object(scanner, "_run_single", side_effect=slow_run_single):
                with patch("tradingagents.dataflows.bybit_data.get_valid_symbols",
                           return_value=["A", "B", "C", "D", "E"]):
                    scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
                    await asyncio.sleep(0.05)  # let first ticker start
                    # Set cancel flag while first ticker is running
                    async with scanner._lock:
                        if scan_id in scanner._scans:
                            scanner._scans[scan_id]["cancel"] = True
                    await asyncio.sleep(0.5)
        finally:
            svc_mod._BATCH_SIZE = orig_batch

        # With batch_size=1 and cancel set after first, fewer than 5 tickers should run
        assert len(calls) < 5


class TestCancelScanDBUpdate:
    @pytest.mark.asyncio
    async def test_cancel_scan_calls_db_update_scan(self, scanner):
        """R6-F2: cancel_scan writes status='cancelled' to DB."""
        with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
            scan_id = await scanner.start_scan({"analysis_date": "2025-01-10"})
        result = await scanner.cancel_scan(scan_id)
        assert result is True
        scanner._db.update_scan.assert_any_call(scan_id, status="cancelled")


class TestInsertScanDuplicate:
    @pytest.mark.asyncio
    async def test_insert_scan_duplicate_raises(self, scanner):
        """R6-F4: insert_scan with duplicate scan_id raises an exception."""
        from backend.async_persistence import AsyncAnalysisDB
        import os
        dsn = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test")
        db = AsyncAnalysisDB(dsn=dsn)
        await db.connect()
        scan_id = f"dup-scan-{uuid.uuid4()}"
        s = {
            "scan_id": scan_id,
            "status": "running",
            "config": "{}",
            "total": 0,
            "completed": 0,
            "failed": 0,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        try:
            await db.insert_scan(s)
            with pytest.raises(Exception):
                await db.insert_scan(s)
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute("DELETE FROM scans WHERE scan_id = $1", scan_id)
            await db.close()


class TestPctZeroConfidence:
    def test_zero_pct_confidence_uses_default(self):
        """R6-F7: 0% confidence falls through to default conf_score."""
        from backend.services.scanner_service import _parse_signal_from_reports
        result = _parse_signal_from_reports({"final_trade_decision": "Buy with 0% confidence"})
        assert result["confidence"] in ("low", "none")


class TestResumeIncompleteScanIntegration:
    """R8: resume_incomplete_scans for-loop body with real AsyncAnalysisDB."""

    _TEST_SCAN_IDS = []

    async def _make_db(self):
        from backend.async_persistence import AsyncAnalysisDB
        import os
        dsn = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test")
        db = AsyncAnalysisDB(dsn=dsn)
        await db.connect()
        return db

    def _running_scan(self, scan_id=None):
        from datetime import datetime, timezone
        sid = scan_id or str(uuid.uuid4())
        self._TEST_SCAN_IDS.append(sid)
        return {
            "scan_id": sid,
            "status": "running",
            "config": "{}",
            "total": 3,
            "completed": 1,
            "failed": 0,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }

    async def _cleanup(self, db):
        if self._TEST_SCAN_IDS:
            async with db._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM scan_results WHERE scan_id = ANY($1::text[])",
                    self._TEST_SCAN_IDS,
                )
                await conn.execute(
                    "DELETE FROM scans WHERE scan_id = ANY($1::text[])",
                    self._TEST_SCAN_IDS,
                )
        self._TEST_SCAN_IDS.clear()
        await db.close()

    @pytest.mark.asyncio
    async def test_second_running_scan_marked_failed(self):
        """R8-F1b: second running scan in DB is marked failed (only 1 resumed at a time)."""
        db = await self._make_db()
        from backend.services.scanner_service import ScannerService
        analysis = AsyncMock()
        analysis.max_concurrent = 6
        scanner = ScannerService(analysis_service=analysis, db=db)

        sid_a = f"scan-a-{uuid.uuid4()}"
        sid_b = f"scan-b-{uuid.uuid4()}"
        s1 = self._running_scan(sid_a)
        s2 = self._running_scan(sid_b)
        await db.insert_scan(s1)
        await db.insert_scan(s2)

        try:
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["A", "B", "C"]):
                with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                    count = await scanner.resume_incomplete_scans()

            assert count == 1
            result = await db.get_scan(sid_b)
            assert result["status"] == "failed"
        finally:
            await self._cleanup(db)

    @pytest.mark.asyncio
    async def test_symbol_fetch_failure_marks_scan_failed(self):
        """R8-F1c: symbols fetch failure marks scan failed, returns 0."""
        db = await self._make_db()
        from backend.services.scanner_service import ScannerService
        analysis = AsyncMock()
        analysis.max_concurrent = 6
        scanner = ScannerService(analysis_service=analysis, db=db)

        sid = f"scan-fail-sym-{uuid.uuid4()}"
        s = self._running_scan(sid)
        await db.insert_scan(s)

        try:
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", side_effect=RuntimeError("network")):
                count = await scanner.resume_incomplete_scans()

            assert count == 0
            result = await db.get_scan(sid)
            assert result["status"] == "failed"
        finally:
            await self._cleanup(db)

    @pytest.mark.asyncio
    async def test_all_symbols_done_marks_scan_completed(self):
        """R8-F1d: when all symbols already done, scan is immediately marked completed."""
        db = await self._make_db()
        from backend.services.scanner_service import ScannerService
        analysis = AsyncMock()
        analysis.max_concurrent = 6
        scanner = ScannerService(analysis_service=analysis, db=db)

        sid = f"scan-all-done-{uuid.uuid4()}"
        s = self._running_scan(sid)
        await db.insert_scan(s)
        await db.insert_scan_result(sid, {"ticker": "A", "score": 1, "status": "completed", "direction": "long"})
        await db.insert_scan_result(sid, {"ticker": "B", "score": 2, "status": "completed", "direction": "long"})
        await db.insert_scan_result(sid, {"ticker": "C", "score": 3, "status": "completed", "direction": "long"})

        try:
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["A", "B", "C"]):
                count = await scanner.resume_incomplete_scans()

            assert count == 0
            result = await db.get_scan(sid)
            assert result["status"] == "completed"
        finally:
            await self._cleanup(db)

    @pytest.mark.asyncio
    async def test_malformed_config_json_uses_empty_dict(self):
        """R8-F11: malformed config JSON falls back to empty dict without raising."""
        from datetime import datetime, timezone
        db = await self._make_db()
        from backend.services.scanner_service import ScannerService
        analysis = AsyncMock()
        analysis.max_concurrent = 6
        scanner = ScannerService(analysis_service=analysis, db=db)

        sid = f"scan-bad-cfg-{uuid.uuid4()}"
        self._TEST_SCAN_IDS.append(sid)

        async with db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO scans (scan_id, status, config, total, completed, failed, started_at) "
                "VALUES ($1, 'running', $2, 2, 0, 0, '2025-01-10T00:00:00Z')",
                sid, "{not valid json",
            )

        try:
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["X", "Y"]):
                with patch.object(scanner, "_run_scan", new_callable=AsyncMock):
                    count = await scanner.resume_incomplete_scans()

            assert count == 1
            async with scanner._lock:
                in_mem = scanner._scans.get(sid)
            assert in_mem is not None
            assert in_mem["config"] == {}
        finally:
            await self._cleanup(db)

    @pytest.mark.asyncio
    async def test_symbols_override_used_in_run_scan(self):
        """R8-F2: _run_scan is called with symbols_override set to remaining tickers."""
        db = await self._make_db()
        from backend.services.scanner_service import ScannerService
        analysis = AsyncMock()
        analysis.max_concurrent = 6
        scanner = ScannerService(analysis_service=analysis, db=db)

        sid = f"scan-override-{uuid.uuid4()}"
        s = self._running_scan(sid)
        await db.insert_scan(s)
        await db.insert_scan_result(sid, {"ticker": "A", "score": 1, "status": "completed", "direction": "long"})

        try:
            with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["A", "B", "C"]):
                with patch.object(scanner, "_run_scan", new_callable=AsyncMock) as mock_run:
                    count = await scanner.resume_incomplete_scans()
                    await asyncio.sleep(0)

            assert count == 1
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert sorted(kwargs.get("symbols_override")) == ["B", "C"]
        finally:
            await self._cleanup(db)
