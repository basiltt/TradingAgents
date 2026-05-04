"""Tests for SQLite persistence layer — TASK-004."""

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path):
    from backend.persistence import AnalysisDB

    return AnalysisDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def sample_run():
    return {
        "run_id": str(uuid.uuid4()),
        "ticker": "SPY",
        "analysis_date": "2025-06-01",
        "status": "running",
        "config": '{"provider": "anthropic"}',
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


def test_wal_mode(db):
    with db._lock:
        cursor = db._conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
    assert mode == "wal"


def test_busy_timeout(db):
    with db._lock:
        cursor = db._conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
    assert timeout == 5000


def test_insert_and_get_run(db, sample_run):
    db.insert_run(sample_run)
    run = db.get_run(sample_run["run_id"])
    assert run is not None
    assert run["ticker"] == "SPY"
    assert run["status"] == "running"


def test_update_run_status(db, sample_run):
    db.insert_run(sample_run)
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    updated = db.update_run_status(sample_run["run_id"], "completed", None, completed_at)
    assert updated is True
    run = db.get_run(sample_run["run_id"])
    assert run["status"] == "completed"


def test_update_run_status_already_terminal(db, sample_run):
    db.insert_run(sample_run)
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    db.update_run_status(sample_run["run_id"], "completed", None, completed_at)
    updated = db.update_run_status(sample_run["run_id"], "failed", "oops", completed_at)
    assert updated is False
    run = db.get_run(sample_run["run_id"])
    assert run["status"] == "completed"


def test_save_and_get_report_sections(db, sample_run):
    db.insert_run(sample_run)
    db.save_report_section(sample_run["run_id"], "summary", "This is the summary.")
    db.save_report_section(sample_run["run_id"], "details", "These are details.")
    sections = db.get_report_sections(sample_run["run_id"])
    assert len(sections) == 2
    assert sections[0]["section"] == "summary"


def test_list_runs_pagination(db):
    for i in range(5):
        run = {
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "status": "completed",
            "config": "{}",
            "started_at": f"2025-06-01T10:0{i}:00Z",
        }
        db.insert_run(run)
    result = db.list_runs(page=1, limit=3)
    assert len(result["items"]) == 3
    assert result["total"] == 5


def test_list_runs_filter_ticker(db):
    for ticker in ["SPY", "SPY", "AAPL"]:
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": ticker,
            "analysis_date": "2025-06-01",
            "status": "completed",
            "config": "{}",
            "started_at": "2025-06-01T10:00:00Z",
        })
    result = db.list_runs(page=1, limit=10, ticker="SPY")
    assert result["total"] == 2


def test_list_runs_filter_status(db):
    for status in ["running", "completed", "failed"]:
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "status": status,
            "config": "{}",
            "started_at": "2025-06-01T10:00:00Z",
        })
    result = db.list_runs(page=1, limit=10, status="completed")
    assert result["total"] == 1


def test_list_runs_filter_date_range(db):
    for d in ["2025-05-01", "2025-06-01", "2025-07-01"]:
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": d,
            "status": "completed",
            "config": "{}",
            "started_at": f"{d}T10:00:00Z",
        })
    result = db.list_runs(page=1, limit=10, from_date="2025-05-15", to_date="2025-06-15")
    assert result["total"] == 1


def test_list_runs_no_matches(db):
    result = db.list_runs(page=1, limit=10, ticker="NONEXIST")
    assert result["total"] == 0
    assert result["items"] == []


def test_orphan_recovery(db, sample_run):
    db.insert_run(sample_run)
    count = db.recover_orphans()
    assert count >= 1
    run = db.get_run(sample_run["run_id"])
    assert run["status"] == "failed"


def test_started_at_check_constraint(db):
    with pytest.raises(Exception):
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "status": "running",
            "config": "{}",
            "started_at": "not-a-date",
        })


def test_schema_migration_no_op_current_version(tmp_path):
    from backend.persistence import AnalysisDB

    db1 = AnalysisDB(db_path=str(tmp_path / "test.db"))
    db1.close()
    db2 = AnalysisDB(db_path=str(tmp_path / "test.db"))
    db2.close()


def test_schema_migration_higher_version_refused(tmp_path):
    from backend.persistence import AnalysisDB

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 9999")
    conn.close()

    with pytest.raises(RuntimeError, match="newer"):
        AnalysisDB(db_path=db_path)


def test_pre_migration_backup(tmp_path):
    from backend.persistence import AnalysisDB

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 0")
    conn.close()

    db = AnalysisDB(db_path=db_path)
    db.close()
    assert os.path.exists(db_path + ".backup.v0")


def test_concurrent_writes(db):
    errors = []

    def insert_run(i):
        try:
            db.insert_run({
                "run_id": str(uuid.uuid4()),
                "ticker": "SPY",
                "analysis_date": "2025-06-01",
                "status": "running",
                "config": "{}",
                "started_at": f"2025-06-01T10:{i:02d}:00Z",
            })
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=insert_run, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    result = db.list_runs(page=1, limit=20)
    assert result["total"] == 10


def test_get_checkpoint_exists(db, sample_run):
    db.insert_run(sample_run)
    assert db.get_checkpoint_exists("SPY", "2025-06-01") is True
    assert db.get_checkpoint_exists("AAPL", "2025-06-01") is False


# ---------------------------------------------------------------------------
# Crypto migration tests (TASK-015)
# ---------------------------------------------------------------------------

def test_migration_adds_asset_type_column(db):
    with db._lock:
        row = db._conn.execute(
            "PRAGMA table_info(analysis_runs)"
        ).fetchall()
    col_names = [r[1] for r in row]
    assert "asset_type" in col_names


def test_insert_run_with_asset_type(db):
    run = {
        "run_id": str(uuid.uuid4()),
        "ticker": "BTCUSDT",
        "analysis_date": "2025-01-15",
        "status": "running",
        "config": '{}',
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "asset_type": "crypto",
    }
    db.insert_run(run)
    stored = db.get_run(run["run_id"])
    assert stored["asset_type"] == "crypto"


def test_insert_run_default_asset_type(db, sample_run):
    db.insert_run(sample_run)
    stored = db.get_run(sample_run["run_id"])
    assert stored["asset_type"] == "stock"


def test_list_runs_filter_asset_type(db):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for i, at in enumerate(["stock", "crypto", "crypto"]):
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "BTCUSDT" if at == "crypto" else "SPY",
            "analysis_date": "2025-01-15",
            "status": "running",
            "config": "{}",
            "started_at": ts,
            "asset_type": at,
        })
    result = db.list_runs(asset_type="crypto")
    assert result["total"] == 2
    result2 = db.list_runs(asset_type="stock")
    assert result2["total"] == 1


def test_asset_type_sql_injection_safe(db):
    result = db.list_runs(asset_type="'; DROP TABLE analysis_runs; --")
    assert result["total"] == 0


def test_delete_run(db, sample_run):
    db.insert_run(sample_run)
    assert db.delete_run(sample_run["run_id"]) is True
    assert db.get_run(sample_run["run_id"]) is None


def test_delete_run_not_found(db):
    assert db.delete_run("nonexistent") is False


def test_delete_all_runs(db, sample_run):
    db.insert_run(sample_run)
    run2 = sample_run.copy()
    run2["run_id"] = str(uuid.uuid4())
    db.insert_run(run2)
    count = db.delete_all_runs()
    assert count == 2


def test_delete_all_checkpoints(db, sample_run):
    db.insert_run(sample_run)
    db.update_run_status(sample_run["run_id"], "completed", None, "2025-01-10T00:00:00Z")
    run2 = sample_run.copy()
    run2["run_id"] = str(uuid.uuid4())
    db.insert_run(run2)
    count = db.delete_all_checkpoints()
    assert count == 1
    assert db.get_run(run2["run_id"]) is not None


def test_delete_ticker_checkpoints(db, sample_run):
    db.insert_run(sample_run)
    db.update_run_status(sample_run["run_id"], "failed", "error", "2025-01-10T00:00:00Z")
    count = db.delete_ticker_checkpoints("SPY")
    assert count == 1


def test_health_check(db):
    assert db.health_check() == "ok"


def test_checkpoint(db, sample_run):
    db.insert_run(sample_run)
    db.checkpoint()  # should not raise
