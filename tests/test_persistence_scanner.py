"""Tests for backend.persistence scanner methods — Phase 1 unit tests."""

import tempfile
import os
import pytest


@pytest.fixture
def db():
    from backend.persistence import AnalysisDB
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _db = AnalysisDB(path)
    yield _db
    _db.close()
    os.unlink(path)


class TestScannerPersistence:
    def test_insert_and_get_scan(self, db):
        scan = {
            "scan_id": "scan-1",
            "status": "running",
            "config": "{}",
            "total": 10,
            "completed": 0,
            "failed": 0,
            "started_at": "2025-01-10T00:00:00Z",
        }
        db.insert_scan(scan)
        result = db.get_scan("scan-1")
        assert result is not None
        assert result["scan_id"] == "scan-1"
        assert result["status"] == "running"
        assert result["results"] == []

    def test_get_scan_not_found(self, db):
        assert db.get_scan("nonexistent") is None

    def test_update_scan(self, db):
        db.insert_scan({"scan_id": "scan-2", "started_at": "2025-01-10T00:00:00Z"})
        db.update_scan("scan-2", status="completed", completed_at="2025-01-10T01:00:00Z")
        result = db.get_scan("scan-2")
        assert result["status"] == "completed"

    def test_update_scan_ignores_disallowed_fields(self, db):
        db.insert_scan({"scan_id": "scan-3", "started_at": "2025-01-10T00:00:00Z"})
        db.update_scan("scan-3", bogus_field="hack")
        result = db.get_scan("scan-3")
        assert result["status"] == "running"

    def test_insert_scan_result_and_get(self, db):
        db.insert_scan({"scan_id": "scan-4", "started_at": "2025-01-10T00:00:00Z"})
        db.insert_scan_result("scan-4", {
            "ticker": "AAPL",
            "run_id": "run-1",
            "status": "completed",
            "direction": "buy",
            "confidence": "high",
            "score": 8,
            "decision_summary": "Strong buy",
        })
        result = db.get_scan("scan-4")
        assert len(result["results"]) == 1
        assert result["results"][0]["ticker"] == "AAPL"
        assert result["results"][0]["score"] == 8

    def test_list_scans(self, db):
        db.insert_scan({"scan_id": "s1", "started_at": "2025-01-10T00:00:00Z"})
        db.insert_scan({"scan_id": "s2", "started_at": "2025-01-11T00:00:00Z"})
        scans = db.list_scans()
        assert len(scans) == 2

    def test_get_scan_completed_tickers(self, db):
        db.insert_scan({"scan_id": "s5", "started_at": "2025-01-10T00:00:00Z"})
        db.insert_scan_result("s5", {"ticker": "AAPL", "status": "completed"})
        db.insert_scan_result("s5", {"ticker": "GOOG", "status": "completed"})
        tickers = db.get_scan_completed_tickers("s5")
        assert tickers == {"AAPL", "GOOG"}

    def test_increment_scan_counter(self, db):
        db.insert_scan({"scan_id": "s6", "started_at": "2025-01-10T00:00:00Z"})
        db.increment_scan_counter("s6", "completed")
        db.increment_scan_counter("s6", "completed")
        result = db.get_scan("s6")
        assert result["completed"] == 2

    def test_increment_scan_counter_ignores_invalid_field(self, db):
        db.insert_scan({"scan_id": "s7", "started_at": "2025-01-10T00:00:00Z"})
        db.increment_scan_counter("s7", "bogus")  # should be a no-op

    def test_get_running_scans(self, db):
        db.insert_scan({"scan_id": "r1", "status": "running", "started_at": "2025-01-10T00:00:00Z"})
        db.insert_scan({"scan_id": "r2", "status": "completed", "started_at": "2025-01-10T00:00:00Z"})
        running = db.get_running_scans()
        assert len(running) == 1
        assert running[0]["scan_id"] == "r1"

    def test_health_check(self, db):
        assert db.health_check() == "ok"
