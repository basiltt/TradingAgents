"""Tests for backend.services.scanner_service.ScannerService — Phase 1 unit tests."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def scanner():
    from backend.services.scanner_service import ScannerService
    analysis = AsyncMock()
    db = MagicMock()
    return ScannerService(analysis_service=analysis, db=db)


@pytest.fixture
def scanner_no_db():
    from backend.services.scanner_service import ScannerService
    analysis = AsyncMock()
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
        scanner._analysis.get_run.return_value = {"status": "completed"}
        scanner._analysis.get_snapshot = AsyncMock(return_value=None)
        scanner._analysis.get_report = AsyncMock(return_value="Buy BTCUSDT")
        scanner._scans["s1"] = {
            "scan_id": "s1", "status": "running", "cancel": False,
            "config": {"analysis_date": "2025-01-10"},
            "failed": 0, "completed": 0, "results": [],
            "current_tickers": [],
        }
        with patch("backend.services.scanner_service._POLL_INTERVAL", 0):
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
