"""Tests for scanner-related persistence methods — Phase 3 R1."""

import uuid
import pytest
from datetime import datetime, timezone


@pytest.fixture
def db(tmp_path):
    from backend.persistence import AnalysisDB
    return AnalysisDB(db_path=str(tmp_path / "test.db"))


def _scan(scan_id=None, status="running"):
    return {
        "scan_id": scan_id or str(uuid.uuid4()),
        "status": status,
        "config": "{}",
        "total": 5,
        "completed": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


def test_insert_and_get_scan(db):
    s = _scan()
    db.insert_scan(s)
    result = db.get_scan(s["scan_id"])
    assert result is not None
    assert result["scan_id"] == s["scan_id"]
    assert result["status"] == "running"
    assert result["results"] == []


def test_update_scan_status(db):
    s = _scan()
    db.insert_scan(s)
    db.update_scan(s["scan_id"], status="completed", completed=5)
    result = db.get_scan(s["scan_id"])
    assert result["status"] == "completed"
    assert result["completed"] == 5


def test_update_scan_ignores_invalid_fields(db):
    s = _scan()
    db.insert_scan(s)
    db.update_scan(s["scan_id"], invalid_field="hacked", status="completed")
    result = db.get_scan(s["scan_id"])
    assert result["status"] == "completed"
    assert "invalid_field" not in result


def test_update_scan_all_invalid_fields_noop(db):
    s = _scan()
    db.insert_scan(s)
    db.update_scan(s["scan_id"], bad_field="value")
    result = db.get_scan(s["scan_id"])
    assert result["status"] == "running"


def test_insert_scan_result_sorted_by_score(db):
    s = _scan()
    db.insert_scan(s)
    db.insert_scan_result(s["scan_id"], {"ticker": "A", "score": 3, "status": "completed", "direction": "long"})
    db.insert_scan_result(s["scan_id"], {"ticker": "B", "score": 8, "status": "completed", "direction": "long"})
    db.insert_scan_result(s["scan_id"], {"ticker": "C", "score": -5, "status": "completed", "direction": "short"})
    result = db.get_scan(s["scan_id"])
    scores = [r["score"] for r in result["results"]]
    # Should be ordered by ABS(score) DESC: 8, -5, 3
    assert abs(scores[0]) >= abs(scores[1]) >= abs(scores[2])


def test_list_scans_returns_all(db):
    s1 = _scan()
    s2 = _scan(status="completed")
    db.insert_scan(s1)
    db.insert_scan(s2)
    scans = db.list_scans()
    assert len(scans) == 2


def test_get_scan_completed_tickers(db):
    s = _scan()
    db.insert_scan(s)
    db.insert_scan_result(s["scan_id"], {"ticker": "SPY", "score": 1, "status": "completed", "direction": "long"})
    db.insert_scan_result(s["scan_id"], {"ticker": "AAPL", "score": 2, "status": "completed", "direction": "long"})
    tickers = db.get_scan_completed_tickers(s["scan_id"])
    assert tickers == {"SPY", "AAPL"}


def test_increment_scan_counter_completed(db):
    s = _scan()
    db.insert_scan(s)
    db.increment_scan_counter(s["scan_id"], "completed")
    db.increment_scan_counter(s["scan_id"], "completed")
    result = db.get_scan(s["scan_id"])
    assert result["completed"] == 2


def test_increment_scan_counter_failed(db):
    s = _scan()
    db.insert_scan(s)
    db.increment_scan_counter(s["scan_id"], "failed")
    result = db.get_scan(s["scan_id"])
    assert result["failed"] == 1


def test_increment_scan_counter_invalid_field_noop(db):
    s = _scan()
    db.insert_scan(s)
    db.increment_scan_counter(s["scan_id"], "invalid_field")
    result = db.get_scan(s["scan_id"])
    assert result["completed"] == 0
    assert result["failed"] == 0


def test_get_running_scans(db):
    s1 = _scan()
    s2 = _scan(status="completed")
    db.insert_scan(s1)
    db.insert_scan(s2)
    running = db.get_running_scans()
    assert len(running) == 1
    assert running[0]["scan_id"] == s1["scan_id"]


def test_get_scan_not_found(db):
    result = db.get_scan("nonexistent-id")
    assert result is None


def test_list_runs_page2(db):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for i in range(5):
        db.insert_run({
            "run_id": str(uuid.uuid4()), "ticker": "SPY",
            "analysis_date": "2025-01-10", "status": "completed",
            "config": "{}", "started_at": ts,
        })
    result = db.list_runs(page=2, limit=3)
    assert len(result["items"]) == 2
    assert result["total"] == 5


def test_list_runs_combined_filters(db):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for i, (ticker, status, date, at) in enumerate([
        ("SPY", "completed", "2025-01-10", "stock"),
        ("SPY", "failed", "2025-01-10", "stock"),
        ("AAPL", "completed", "2025-01-10", "stock"),
        ("BTCUSDT", "completed", "2025-01-10", "crypto"),
        ("SPY", "completed", "2025-01-11", "stock"),
    ]):
        db.insert_run({
            "run_id": str(uuid.uuid4()), "ticker": ticker,
            "analysis_date": date, "status": status,
            "config": "{}", "started_at": ts, "asset_type": at,
        })
    result = db.list_runs(
        ticker="SPY", status="completed",
        from_date="2025-01-10", to_date="2025-01-10",
        asset_type="stock",
    )
    assert result["total"] == 1


def test_delete_run_cascades_report_sections(db):
    run_id = str(uuid.uuid4())
    db.insert_run({
        "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
        "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
    })
    db.save_report_section(run_id, "market", "Market data")
    db.save_report_section(run_id, "news", "News data")
    db.delete_run(run_id)
    sections = db.get_report_sections(run_id)
    assert sections == []


def test_delete_all_runs_cascades_sections(db):
    for i in range(3):
        run_id = str(uuid.uuid4())
        db.insert_run({
            "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
            "status": "running", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
        })
        db.save_report_section(run_id, "market", "data")
    count = db.delete_all_runs()
    assert count == 3
    result = db.list_runs(page=1, limit=10)
    assert result["total"] == 0


def test_insert_scan_result_upsert_replaces(db):
    """R6-F5: INSERT OR REPLACE on scan_results replaces same (scan_id, ticker)."""
    s = _scan()
    db.insert_scan(s)
    result1 = {"ticker": "BTC", "status": "completed", "direction": "buy",
                "confidence": "high", "score": 8, "decision_summary": "v1", "run_id": "r1"}
    result2 = {"ticker": "BTC", "status": "completed", "direction": "sell",
                "confidence": "low", "score": -3, "decision_summary": "v2", "run_id": "r2"}
    db.insert_scan_result(s["scan_id"], result1)
    db.insert_scan_result(s["scan_id"], result2)
    scan = db.get_scan(s["scan_id"])
    btc_results = [r for r in scan["results"] if r["ticker"] == "BTC"]
    assert len(btc_results) == 1
    assert btc_results[0]["direction"] == "sell"


def test_get_scan_completed_tickers_nonexistent(db):
    """R6-F6: get_scan_completed_tickers returns empty set for unknown scan_id."""
    result = db.get_scan_completed_tickers("nonexistent-id")
    assert result == set()


def test_update_scan_completed_at(db):
    """R6-F7: update_scan persists completed_at field."""
    s = _scan()
    db.insert_scan(s)
    db.update_scan(s["scan_id"], status="completed", completed_at="2025-01-10T00:00:00Z")
    scan = db.get_scan(s["scan_id"])
    assert scan["completed_at"] == "2025-01-10T00:00:00Z"
