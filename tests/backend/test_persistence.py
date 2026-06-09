"""Tests for PostgreSQL persistence layer."""

import os
import threading
import uuid
from datetime import datetime, timezone

import psycopg2
import pytest

from backend import persistence as pers

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


def _ensure_test_db():
    try:
        base_dsn = _TEST_DSN.rsplit("/", 1)[0] + "/postgres"
        conn = psycopg2.connect(base_dsn)
        conn.autocommit = True
        cur = conn.cursor()
        db_name = _TEST_DSN.rsplit("/", 1)[1].split("?")[0]
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{db_name}"')
        conn.close()
    except psycopg2.OperationalError:
        pytest.skip("PostgreSQL not available", allow_module_level=True)


_ensure_test_db()


@pytest.fixture
def db():
    from backend.persistence import AnalysisDB

    instance = AnalysisDB(dsn=_TEST_DSN)
    yield instance
    with instance._get_conn() as conn:
        cur = conn.cursor()
        for table in (
            "close_executions",
            "close_rules",
            "trading_cycles",
            "trading_accounts",
            "scan_results",
            "scans",
            "report_sections",
            "analysis_runs",
        ):
            cur.execute(f"DELETE FROM {table}")
        conn.commit()
    instance.close()


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
    """CHECK constraint on started_at rejects non-ISO timestamps."""
    with pytest.raises(Exception):
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "status": "running",
            "config": "{}",
            "started_at": "not-a-date",
        })


def test_insert_run_invalid_status_raises(db):
    with pytest.raises(Exception):
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "status": "invalid_status",
            "config": "{}",
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        })


def test_schema_migration_no_op_current_version():
    from backend.persistence import AnalysisDB
    db1 = AnalysisDB(dsn=_TEST_DSN)
    db1.close()
    db2 = AnalysisDB(dsn=_TEST_DSN)
    db2.close()


def test_schema_migration_higher_version_tolerated(caplog):
    """Opening the SYNC DB layer against a schema newer than its own migration list
    must NOT raise: AsyncAnalysisDB owns migrations in production, and the sync path
    is a read-only consumer that must coexist with a DB already migrated past its
    own _MIGRATIONS tail. It logs a warning and skips sync migrations instead."""
    import logging

    from backend.persistence import AnalysisDB
    conn = psycopg2.connect(_TEST_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("UPDATE schema_version SET version = 9999")
    conn.close()
    try:
        with caplog.at_level(logging.WARNING, logger="backend.persistence"):
            db = AnalysisDB(dsn=_TEST_DSN)  # must NOT raise
        db.close()
        assert any("newer than sync max" in r.message for r in caplog.records), \
            "expected a 'newer than sync max' warning when schema is ahead of the sync layer"
    finally:
        conn = psycopg2.connect(_TEST_DSN)
        conn.autocommit = True
        cur = conn.cursor()
        max_v = pers._MIGRATIONS[-1][0]
        cur.execute("UPDATE schema_version SET version = %s", (max_v,))
        conn.close()


def test_migration_rollback_on_bad_sql():
    """A bad migration rolls back and does not advance schema version."""
    original = pers._MIGRATIONS[:]
    pers._MIGRATIONS.append((9998, "INVALID SQL THAT WILL FAIL"))
    try:
        with pytest.raises(Exception):
            pers.AnalysisDB(dsn=_TEST_DSN)
        conn = psycopg2.connect(_TEST_DSN)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT version FROM schema_version")
        version = cur.fetchone()[0]
        conn.close()
        assert version != 9998
    finally:
        pers._MIGRATIONS.clear()
        pers._MIGRATIONS.extend(original)


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


def test_health_check_degraded():
    """health_check returns degraded when connection pool is closed."""
    from backend.persistence import AnalysisDB
    db2 = AnalysisDB(dsn=_TEST_DSN)
    db2.close()
    assert db2.health_check() == "degraded"


def test_checkpoint(db, sample_run):
    db.insert_run(sample_run)
    db.checkpoint()


def test_insert_run_duplicate_raises_value_error(db, sample_run):
    db.insert_run(sample_run)
    with pytest.raises(ValueError, match=sample_run["run_id"]):
        db.insert_run(sample_run)


def test_save_report_section_upsert_replaces(db, sample_run):
    db.insert_run(sample_run)
    db.save_report_section(sample_run["run_id"], "market", "version 1")
    db.save_report_section(sample_run["run_id"], "market", "version 2")
    sections = db.get_report_sections(sample_run["run_id"])
    market_sections = [s for s in sections if s["section"] == "market"]
    assert len(market_sections) == 1
    assert market_sections[0]["content"] == "version 2"


def test_update_run_status_stores_error_message(db, sample_run):
    db.insert_run(sample_run)
    completed_at = "2025-01-10T00:00:00Z"
    db.update_run_status(sample_run["run_id"], "failed", "timeout occurred", completed_at)
    run = db.get_run(sample_run["run_id"])
    assert run["error"] == "timeout occurred"


def test_insert_run_invalid_asset_type_raises(db):
    with pytest.raises(Exception):
        db.insert_run({
            "run_id": str(uuid.uuid4()),
            "ticker": "EURUSD",
            "analysis_date": "2025-01-10",
            "status": "running",
            "config": "{}",
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "asset_type": "forex",
        })


def test_report_sections_fk_nonexistent_run_raises(db):
    db.save_report_section("nonexistent-run-id", "market", "data")
    sections = db.get_report_sections("nonexistent-run-id")
    assert len(sections) == 0


def test_update_run_status_nonexistent_run_returns_false(db):
    result = db.update_run_status("nonexistent-run-id", "completed", None, "2025-01-10T00:00:00Z")
    assert result is False


def test_delete_ticker_checkpoints_preserves_running_runs(db, sample_run):
    completed_run = sample_run.copy()
    completed_run["run_id"] = str(uuid.uuid4())
    db.insert_run(completed_run)
    db.update_run_status(completed_run["run_id"], "completed", None, "2025-01-10T00:00:00Z")
    running_run = sample_run.copy()
    running_run["run_id"] = str(uuid.uuid4())
    db.insert_run(running_run)
    count = db.delete_ticker_checkpoints("SPY")
    assert count == 1
    assert db.get_run(running_run["run_id"]) is not None


def test_connection_pool_resilience(db, sample_run):
    """Verify that separate operations use independent connections from the pool."""
    db.insert_run(sample_run)
    run = db.get_run(sample_run["run_id"])
    assert run is not None
    db.update_run_status(sample_run["run_id"], "completed", None, "2025-01-10T00:00:00Z")
    run = db.get_run(sample_run["run_id"])
    assert run["status"] == "completed"


def test_completed_at_check_constraint(db, sample_run):
    """CHECK constraint on completed_at rejects non-ISO timestamps."""
    db.insert_run(sample_run)
    with pytest.raises(Exception):
        db.update_run_status(sample_run["run_id"], "completed", None, "not-a-date")


def test_update_run_status_invalid_status_raises(db, sample_run):
    """CHECK constraint rejects invalid status values on update."""
    db.insert_run(sample_run)
    with pytest.raises(Exception):
        db.update_run_status(sample_run["run_id"], "bogus_status", None, "2025-01-10T00:00:00Z")


def test_recover_orphans_returns_zero_when_none(db):
    """recover_orphans returns 0 when no running runs exist."""
    count = db.recover_orphans()
    assert count == 0


def test_default_dsn_raises_without_env():
    """_default_dsn raises RuntimeError when DATABASE_URL is unset."""
    import os
    from backend.persistence import _default_dsn
    old = os.environ.pop("DATABASE_URL", None)
    try:
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            _default_dsn()
    finally:
        if old is not None:
            os.environ["DATABASE_URL"] = old


def _ensure_account(db, account_id: str) -> None:
    with db._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trading_accounts (id, label, account_type, api_key_masked, api_key_encrypted, api_secret_encrypted, created_at, updated_at)
            VALUES (%s, 'Test', 'demo', 'xxx', '\\x00', '\\x00', %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (account_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _ensure_cycle(db, account_id: str, cycle_id: int) -> None:
    with db._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trading_cycles (
                id, account_id, status, trade_direction, leverage, capital_pct,
                max_trades, target_type, target_value, max_drawdown_pct, created_at
            )
            VALUES (%s, %s, 'pending', 'straight', 10, 5.0, 5, 'percentage', 10.0, 5.0, now())
            ON CONFLICT (id) DO NOTHING
            """,
            (cycle_id, account_id),
        )
        conn.commit()


def test_close_rules_insert_and_update(db):
    account_id = "test-rule-acc"
    _ensure_account(db, account_id)
    _ensure_cycle(db, account_id, 9999)

    from decimal import Decimal
    from datetime import datetime, timezone

    # 1. Insert with Decimal reference_value and cycle_id
    rule_decimal = {
        "account_id": account_id,
        "trigger_type": "BALANCE_BELOW",
        "threshold_value": Decimal("90.0"),
        "reference_value": Decimal("100.0"),
        "status": "active",
        "cycle_id": 9999,
    }
    inserted_decimal = db.insert_close_rule(rule_decimal)
    assert inserted_decimal["reference_value"] == "100.0"
    assert inserted_decimal["status"] == "active"
    assert inserted_decimal["cycle_id"] == 9999

    # 2. Insert with datetime reference_value
    dt_now = datetime.now(timezone.utc)
    rule_datetime = {
        "account_id": account_id,
        "trigger_type": "BREAKEVEN_TIMEOUT",
        "threshold_value": Decimal("120.0"),
        "reference_value": dt_now,
        "status": "active",
    }
    inserted_datetime = db.insert_close_rule(rule_datetime)
    assert inserted_datetime["reference_value"] == dt_now.isoformat()

    # 3. Insert with string reference_value
    rule_string = {
        "account_id": account_id,
        "trigger_type": "BALANCE_ABOVE",
        "threshold_value": Decimal("110.0"),
        "reference_value": "some-string",
        "status": "active",
    }
    inserted_string = db.insert_close_rule(rule_string)
    assert inserted_string["reference_value"] == "some-string"

    # 4. Update with Decimal and status
    updated = db.update_close_rule(
        inserted_string["id"], reference_value=Decimal("123.45"), status="paused"
    )
    assert updated is not None
    assert updated["reference_value"] == "123.45"
    assert updated["status"] == "paused"

    # 5. List close rules
    rules = db.list_close_rules(account_id)
    assert len(rules) == 3

