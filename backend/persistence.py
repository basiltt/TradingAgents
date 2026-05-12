"""PostgreSQL persistence layer with migration framework and connection resilience."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Generator, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed','cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL CHECK(started_at ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}'),
    completed_at TEXT CHECK(completed_at IS NULL OR completed_at ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}'),
    error TEXT,
    instance_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON analysis_runs(ticker, analysis_date);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON analysis_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS report_sections (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, section)
);

CREATE INDEX IF NOT EXISTS idx_reports_run_id ON report_sections(run_id)
""".strip()

_MIGRATIONS: list[tuple[int, str]] = [
    (1, _SCHEMA_V1),
    (2, "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))"),
    (3, "CREATE INDEX IF NOT EXISTS idx_runs_asset_type_started ON analysis_runs(asset_type, started_at DESC)"),
    (4, """
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','completed','failed','cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
)
"""),
    (5, """
CREATE TABLE IF NOT EXISTS scan_results (
    id SERIAL PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('completed','failed','cancelled','unknown')),
    direction TEXT NOT NULL DEFAULT 'hold' CHECK(direction IN ('buy','sell','hold')),
    confidence TEXT NOT NULL DEFAULT 'none' CHECK(confidence IN ('high','moderate','low','none')),
    score INTEGER NOT NULL DEFAULT 0 CHECK(score BETWEEN -10 AND 10),
    decision_summary TEXT NOT NULL DEFAULT '',
    UNIQUE(scan_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON scan_results(scan_id)
"""),
    (6, """
ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS signal_source TEXT NOT NULL DEFAULT 'unknown'
"""),
    (7, """
CREATE TABLE IF NOT EXISTS trading_accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('demo', 'live')),
    api_key_masked TEXT NOT NULL,
    api_key_encrypted BYTEA NOT NULL,
    api_secret_encrypted BYTEA NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    bybit_uid TEXT,
    last_connected_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON trading_accounts(is_active) WHERE deleted_at IS NULL
"""),
    (8, """
CREATE TABLE IF NOT EXISTS closed_pnl_records (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_entry_price REAL NOT NULL,
    avg_exit_price REAL NOT NULL,
    closed_pnl REAL NOT NULL,
    leverage REAL NOT NULL DEFAULT 1,
    created_time INTEGER NOT NULL,
    bybit_order_id TEXT NOT NULL,
    UNIQUE(account_id, bybit_order_id)
);
CREATE INDEX IF NOT EXISTS idx_closed_pnl_account_time ON closed_pnl_records(account_id, created_time DESC)
"""),
    (9, """
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    equity REAL NOT NULL DEFAULT 0,
    wallet_balance REAL NOT NULL DEFAULT 0,
    available_balance REAL NOT NULL DEFAULT 0,
    unrealised_pnl REAL NOT NULL DEFAULT 0,
    realised_pnl REAL NOT NULL DEFAULT 0,
    positions_count INTEGER NOT NULL DEFAULT 0,
    margin_used REAL NOT NULL DEFAULT 0,
    cumulative_pnl REAL NOT NULL DEFAULT 0,
    daily_return_pct REAL NOT NULL DEFAULT 0,
    peak_equity REAL NOT NULL DEFAULT 0,
    drawdown_pct REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(account_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_account_date ON daily_snapshots(account_id, snapshot_date DESC)
"""),
    (10, """
ALTER TABLE trading_accounts ADD COLUMN IF NOT EXISTS include_in_analytics BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS high_freq_snapshots (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity REAL NOT NULL,
    unrealised_pnl REAL NOT NULL,
    realised_pnl REAL NOT NULL,
    balance REAL NOT NULL,
    position_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hf_snapshots_account_ts ON high_freq_snapshots(account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_hf_snapshots_ts ON high_freq_snapshots(ts)
"""),
    (11, """
ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
"""),
    (12, """
CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'swing' CHECK(category IN ('scalping','intraday','swing','positional','grid','dca','hedging','arbitrage')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('active','paused','archived','draft')),
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
CREATE INDEX IF NOT EXISTS idx_strategies_category ON strategies(category)
"""),
    (13, """
CREATE TABLE IF NOT EXISTS scheduled_scans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK(schedule_type IN ('once','interval','daily','weekly','cron')),
    schedule_config JSONB NOT NULL DEFAULT '{}',
    scan_config JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','error')),
    timezone TEXT NOT NULL DEFAULT 'UTC',
    next_run_at TEXT,
    last_run_at TEXT,
    last_scan_id TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_scans_status_next ON scheduled_scans(status, next_run_at)
"""),
    (14, """
CREATE TABLE IF NOT EXISTS schedule_executions (
    id SERIAL PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES scheduled_scans(id) ON DELETE CASCADE,
    scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK(status IN ('started','completed','failed','skipped_busy','skipped_no_key','cancelled')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_executions_lookup ON schedule_executions(schedule_id, started_at DESC)
"""),
    (15, """
ALTER TABLE scans ADD COLUMN IF NOT EXISTS schedule_id TEXT;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS triggered_by TEXT NOT NULL DEFAULT 'manual' CHECK(triggered_by IN ('manual','scheduled','run_now'))
"""),
    (16, """
CREATE INDEX IF NOT EXISTS idx_scans_schedule_id ON scans(schedule_id) WHERE schedule_id IS NOT NULL
"""),
    (17, """
CREATE TABLE IF NOT EXISTS close_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    trigger_type VARCHAR(30) NOT NULL CHECK(trigger_type IN ('BALANCE_BELOW','BALANCE_ABOVE','EQUITY_DROP_PCT','EQUITY_RISE_PCT','PNL_BELOW','PNL_ABOVE')),
    threshold_value NUMERIC(20,8) NOT NULL,
    reference_value NUMERIC(20,8),
    status VARCHAR(15) NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','triggered','executed','expired')),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_close_rules_status_account ON close_rules(status, account_id)
"""),
    (18, """
CREATE TABLE IF NOT EXISTS close_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    rule_id UUID REFERENCES close_rules(id),
    trigger_source VARCHAR(10) NOT NULL CHECK(trigger_source IN ('manual','rule')),
    total_positions INT NOT NULL DEFAULT 0,
    closed_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    results JSONB NOT NULL DEFAULT '[]',
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_close_executions_account ON close_executions(account_id, executed_at DESC)
"""),
]


def _default_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://user:pass@localhost:5432/tradingagents"
        )
    return dsn


class AnalysisDB:
    _POOL_MAX = int(os.environ.get("DB_POOL_MAX", "20"))
    _POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _default_dsn()
        self._instance_id = str(uuid.uuid4())
        self._closed = False
        self._lock = threading.Lock()
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=self._POOL_MAX,
            dsn=self._dsn,
            connect_timeout=10,
        )
        self._semaphore = threading.Semaphore(self._POOL_MAX)
        try:
            self._apply_migrations()
        except Exception:
            self._pool.closeall()
            raise

    @contextmanager
    def _get_conn(self) -> Generator[Any, None, None]:
        if self._closed:
            raise psycopg2.pool.PoolError("database pool is shutting down")
        if not self._semaphore.acquire(timeout=self._POOL_TIMEOUT):
            raise psycopg2.pool.PoolError(
                f"Timed out waiting for a database connection ({self._POOL_TIMEOUT}s)"
            )
        try:
            conn = self._pool.getconn()
        except Exception:
            self._semaphore.release()
            raise
        try:
            yield conn
        finally:
            try:
                if conn.closed:
                    self._pool.putconn(conn, close=True)
                else:
                    conn.rollback()
                    self._pool.putconn(conn)
            except Exception:
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
            finally:
                self._semaphore.release()

    def _apply_migrations(self) -> None:
        with self._get_conn() as conn:
            conn.autocommit = False
            cur = conn.cursor()
            try:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version "
                    "(version INTEGER NOT NULL DEFAULT 0)"
                )
                conn.commit()

                # Advisory lock prevents concurrent migration from multiple instances
                cur.execute("SELECT pg_advisory_lock(8675309)")
                try:
                    cur.execute("SELECT version FROM schema_version")
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("INSERT INTO schema_version (version) VALUES (0)")
                        conn.commit()
                        current = 0
                    else:
                        current = row[0]

                    max_version = _MIGRATIONS[-1][0] if _MIGRATIONS else 0
                    if current > max_version:
                        raise RuntimeError(
                            f"Database schema v{current} is newer than this application "
                            f"supports (max v{max_version}). Please upgrade the application."
                        )

                    if current >= max_version:
                        return

                    for version, sql in _MIGRATIONS:
                        if version <= current:
                            continue
                        try:
                            for stmt in sql.split(";"):
                                stmt = stmt.strip()
                                if stmt:
                                    cur.execute(stmt)
                            cur.execute(
                                "UPDATE schema_version SET version = %s", (version,)
                            )
                            conn.commit()
                        except Exception:
                            conn.rollback()
                            raise
                finally:
                    cur.execute("SELECT pg_advisory_unlock(8675309)")
                    conn.commit()
            except Exception:
                conn.rollback()
                raise

    def insert_run(self, run: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO analysis_runs "
                    "(run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        run["run_id"],
                        run["ticker"],
                        run["analysis_date"],
                        run["status"],
                        run.get("config", "{}"),
                        run["started_at"],
                        self._instance_id,
                        run.get("asset_type", "stock"),
                    ),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise ValueError(f"Run {run['run_id']} already exists")
            except Exception:
                conn.rollback()
                raise

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        completed_at: Optional[str],
    ) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE analysis_runs SET status=%s, error=%s, completed_at=%s "
                    "WHERE run_id=%s AND status='running'",
                    (status, error, completed_at, run_id),
                )
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def save_report_section(self, run_id: str, section: str, content: str) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO report_sections (run_id, section, content) VALUES (%s, %s, %s) "
                    "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                    (run_id, section, content),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM analysis_runs WHERE run_id=%s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            except Exception:
                conn.rollback()
                raise

    def list_runs(
        self,
        page: int = 1,
        limit: int = 20,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        limit = min(max(limit, 1), 10000)
        conditions: list[str] = []
        params: list[Any] = []

        if ticker:
            conditions.append("ticker = %s")
            params.append(ticker)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if from_date:
            conditions.append("analysis_date >= %s")
            params.append(from_date)
        if to_date:
            conditions.append("analysis_date <= %s")
            params.append(to_date)
        if asset_type:
            conditions.append("asset_type = %s")
            params.append(asset_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * limit

        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"SELECT COUNT(*) as cnt FROM analysis_runs {where}", params
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"SELECT run_id, ticker, analysis_date, status, started_at, "
                    f"completed_at, asset_type, config FROM analysis_runs {where} "
                    f"ORDER BY started_at DESC LIMIT %s OFFSET %s",
                    params + [limit, offset],
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def get_report_sections(self, run_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM report_sections WHERE run_id=%s ORDER BY id",
                    (run_id,),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def recover_orphans(self) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE analysis_runs SET status='failed', "
                    "error='Server restarted — orphaned run' "
                    "WHERE status='running'"
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def get_checkpoint_exists(self, ticker: str, date: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT 1 FROM analysis_runs WHERE ticker=%s AND analysis_date=%s LIMIT 1",
                    (ticker, date),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row is not None

    def delete_run(self, run_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM analysis_runs WHERE run_id=%s", (run_id,))
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def delete_all_runs(self) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM analysis_runs")
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def delete_all_checkpoints(self) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM analysis_runs "
                    "WHERE status IN ('completed', 'failed', 'cancelled')"
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def delete_ticker_checkpoints(self, ticker: str) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM analysis_runs "
                    "WHERE ticker=%s AND status IN ('completed', 'failed', 'cancelled')",
                    (ticker,),
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def checkpoint(self) -> None:
        pass

    def health_check(self) -> str:
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                conn.rollback()
            return "ok"
        except Exception:
            return "degraded"

    # ── Scanner persistence ──────────────────────────────────────────

    def insert_scan(self, scan: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scans "
                    "(scan_id, status, config, total, completed, failed, started_at, schedule_id, triggered_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        scan["scan_id"],
                        scan.get("status", "running"),
                        scan.get("config", "{}"),
                        scan.get("total", 0),
                        scan.get("completed", 0),
                        scan.get("failed", 0),
                        scan["started_at"],
                        scan.get("schedule_id"),
                        scan.get("triggered_by", "manual"),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        allowed = {"status", "total", "completed", "failed", "completed_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scans SET {set_clause} WHERE scan_id=%s",
                    list(updates.values()) + [scan_id],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def insert_scan_result(self, scan_id: str, result: Dict[str, Any]) -> None:
        direction = result.get("direction", "hold")
        if direction not in ("buy", "sell", "hold"):
            logger.error(
                "insert_scan_result: invalid direction %r — forcing hold", direction
            )
            direction = "hold"
        confidence = result.get("confidence", "none")
        if confidence not in ("high", "moderate", "low", "none"):
            logger.error(
                "insert_scan_result: invalid confidence %r — forcing none", confidence
            )
            confidence = "none"
        score = int(result.get("score", 0))
        score = max(-10, min(10, score))
        status = result.get("status", "failed")
        if status not in ("completed", "failed", "cancelled", "unknown"):
            status = "unknown"

        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scan_results "
                    "(scan_id, ticker, run_id, status, direction, confidence, "
                    "score, decision_summary, signal_source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (scan_id, ticker) DO UPDATE SET "
                    "run_id = EXCLUDED.run_id, status = EXCLUDED.status, "
                    "direction = EXCLUDED.direction, confidence = EXCLUDED.confidence, "
                    "score = EXCLUDED.score, decision_summary = EXCLUDED.decision_summary, "
                    "signal_source = EXCLUDED.signal_source",
                    (
                        scan_id,
                        result["ticker"],
                        result.get("run_id"),
                        status,
                        direction,
                        confidence,
                        score,
                        result.get("decision_summary", ""),
                        result.get("signal_source", "unknown"),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scans WHERE scan_id=%s", (scan_id,))
                row = cur.fetchone()
                if not row:
                    return None
                scan = dict(row)
                cur.execute(
                    "SELECT ticker, run_id, status, direction, confidence, score, "
                    "decision_summary, signal_source "
                    "FROM scan_results WHERE scan_id=%s ORDER BY ABS(score) DESC",
                    (scan_id,),
                )
                results = cur.fetchall()
                scan["results"] = [dict(r) for r in results]
            except Exception:
                conn.rollback()
                raise
        return scan

    def list_scans(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scans ORDER BY started_at DESC")
                rows = cur.fetchall()
                scans = [dict(r) for r in rows]
                if not scans:
                    return []
                scan_ids = [s["scan_id"] for s in scans]
                cur.execute(
                    "SELECT scan_id, direction, COUNT(*) as cnt "
                    "FROM scan_results WHERE scan_id = ANY(%s) "
                    "GROUP BY scan_id, direction",
                    (scan_ids,),
                )
                counts = cur.fetchall()
                counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
                for row in counts:
                    counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
                for scan in scans:
                    scan["results"] = []
                    scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
            except Exception:
                conn.rollback()
                raise
        return scans

    def get_scan_completed_tickers(self, scan_id: str) -> set[str]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT ticker FROM scan_results WHERE scan_id=%s", (scan_id,)
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {r[0] for r in rows}

    def increment_scan_counter(self, scan_id: str, field: str) -> None:
        if field not in ("completed", "failed"):
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scans SET {field} = {field} + 1 WHERE scan_id=%s",
                    (scan_id,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_running_scans(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scans WHERE status='running'")
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def delete_scan(self, scan_id: str) -> Dict[str, Any]:
        """Delete a scan and cascade-delete its associated analysis runs.

        Returns dict with counts: {deleted_results, deleted_analyses, deleted_sections}.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT run_id FROM scan_results WHERE scan_id=%s AND run_id IS NOT NULL",
                    (scan_id,),
                )
                run_ids = [r[0] for r in cur.fetchall()]

                deleted_sections = 0
                deleted_analyses = 0
                if run_ids:
                    cur.execute(
                        "DELETE FROM report_sections WHERE run_id = ANY(%s)",
                        (run_ids,),
                    )
                    deleted_sections = cur.rowcount
                    cur.execute(
                        "DELETE FROM analysis_runs WHERE run_id = ANY(%s)",
                        (run_ids,),
                    )
                    deleted_analyses = cur.rowcount

                cur.execute("DELETE FROM scan_results WHERE scan_id=%s", (scan_id,))
                deleted_results = cur.rowcount

                cur.execute("DELETE FROM scans WHERE scan_id=%s", (scan_id,))
                scan_deleted = cur.rowcount

                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if scan_deleted == 0:
            return {}
        return {
            "deleted_results": deleted_results,
            "deleted_analyses": deleted_analyses,
            "deleted_sections": deleted_sections,
        }

    def get_scan_analysis_count(self, scan_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM scan_results WHERE scan_id=%s AND run_id IS NOT NULL",
                    (scan_id,),
                )
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        self._closed = True
        self._pool.closeall()

    # ── Trading Accounts persistence ────────────────────────────────────

    def insert_account(self, account: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO trading_accounts "
                    "(id, label, account_type, api_key_masked, api_key_encrypted, "
                    "api_secret_encrypted, key_version, is_active, bybit_uid, "
                    "last_connected_at, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        account["id"],
                        account["label"],
                        account["account_type"],
                        account["api_key_masked"],
                        account["api_key_encrypted"],
                        account["api_secret_encrypted"],
                        account.get("key_version", 1),
                        1,
                        account.get("bybit_uid"),
                        account.get("last_connected_at"),
                        account["created_at"],
                        account["updated_at"],
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_accounts(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, label, account_type, api_key_masked, is_active, "
                    "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
                    "include_in_analytics "
                    "FROM trading_accounts WHERE deleted_at IS NULL "
                    "ORDER BY created_at DESC"
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, label, account_type, api_key_masked, is_active, "
                    "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
                    "include_in_analytics "
                    "FROM trading_accounts WHERE id=%s AND deleted_at IS NULL",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def get_account_credentials(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, account_type, api_key_encrypted, api_secret_encrypted "
                    "FROM trading_accounts WHERE id=%s AND deleted_at IS NULL",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def update_account(self, account_id: str, **fields: Any) -> bool:
        allowed = {"label", "is_active", "bybit_uid", "last_connected_at", "last_error", "include_in_analytics"}
        nullable = {"last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed and (v is not None or k in nullable)}
        if not updates:
            return False
        updates["updated_at"] = fields.get("updated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE trading_accounts SET {set_clause} WHERE id=%s AND deleted_at IS NULL",
                    list(updates.values()) + [account_id],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    def rotate_account_credentials(
        self, account_id: str, api_key_masked: str,
        api_key_encrypted: bytes, api_secret_encrypted: bytes, updated_at: str,
    ) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE trading_accounts SET api_key_masked=%s, api_key_encrypted=%s, "
                    "api_secret_encrypted=%s, last_error=NULL, updated_at=%s "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (api_key_masked, api_key_encrypted, api_secret_encrypted, updated_at, account_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    def soft_delete_account(self, account_id: str, deleted_at: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE trading_accounts SET deleted_at=%s, is_active=0, updated_at=%s "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (deleted_at, deleted_at, account_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    # ── Closed PnL persistence ──────────────────────────────────────────

    def insert_closed_pnl_records(self, account_id: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        inserted = 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                for rec in records:
                    try:
                        cur.execute(
                            "INSERT INTO closed_pnl_records "
                            "(account_id, symbol, side, qty, avg_entry_price, avg_exit_price, "
                            "closed_pnl, leverage, created_time, bybit_order_id) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                            "ON CONFLICT (account_id, bybit_order_id) DO NOTHING",
                            (
                                account_id,
                                rec["symbol"],
                                rec["side"],
                                float(rec["qty"]),
                                float(rec["avgEntryPrice"]),
                                float(rec["avgExitPrice"]),
                                float(rec["closedPnl"]),
                                float(rec.get("leverage", 1)),
                                int(rec["createdTime"]),
                                rec["orderId"],
                            ),
                        )
                        inserted += cur.rowcount
                    except (KeyError, TypeError, ValueError) as e:
                        logger.warning("Skipping closed PnL record: %s — %s", type(e).__name__, e)
                    except Exception:
                        logger.debug("Duplicate or DB error inserting PnL record", exc_info=True)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted

    def get_closed_pnl(
        self, account_id: str, start_time: int, end_time: int,
        page: int = 1, limit: int = 100,
    ) -> Dict[str, Any]:
        offset = (page - 1) * limit
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s",
                    (account_id, start_time, end_time),
                )
                total = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT * FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s "
                    "ORDER BY created_time DESC LIMIT %s OFFSET %s",
                    (account_id, start_time, end_time, limit, offset),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    def get_closed_pnl_summary(
        self, account_id: str, start_time: int, end_time: int,
    ) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT closed_pnl FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s",
                    (account_id, start_time, end_time),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }

        wins = [r[0] for r in rows if r[0] > 0]
        losses = [r[0] for r in rows if r[0] < 0]
        total_pnl = sum(r[0] for r in rows)
        total_count = len(rows)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0.0
        avg_win = str(sum(wins) / win_count) if wins else "0"
        avg_loss = str(abs(sum(losses) / loss_count)) if losses else "0"

        return {
            "total_pnl": str(total_pnl),
            "total_count": total_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }

    def get_portfolio_pnl_summary(
        self, start_time: int, end_time: int,
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                sql = (
                    "SELECT cpr.closed_pnl FROM closed_pnl_records cpr "
                    "JOIN trading_accounts ta ON ta.id = cpr.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND cpr.created_time>=%s AND cpr.created_time<=%s"
                )
                params: list = [start_time, end_time]
                if account_type:
                    sql += " AND ta.account_type = %s"
                    params.append(account_type)
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }

        wins = [r[0] for r in rows if r[0] > 0]
        losses = [r[0] for r in rows if r[0] < 0]
        total_pnl = sum(r[0] for r in rows)
        total_count = len(rows)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0.0
        avg_win = str(sum(wins) / win_count) if wins else "0"
        avg_loss = str(abs(sum(losses) / loss_count)) if losses else "0"

        return {
            "total_pnl": str(total_pnl),
            "total_count": total_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }

    def get_latest_closed_pnl_time(self, account_id: str) -> Optional[int]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT MAX(created_time) FROM closed_pnl_records WHERE account_id=%s",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row[0] if row and row[0] else None

    # ── Daily Snapshots ────────────────────────────────────────────────

    def upsert_daily_snapshot(self, snapshot: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO daily_snapshots "
                    "(account_id, snapshot_date, equity, wallet_balance, available_balance, "
                    "unrealised_pnl, realised_pnl, positions_count, margin_used, "
                    "cumulative_pnl, daily_return_pct, peak_equity, drawdown_pct) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (account_id, snapshot_date) DO UPDATE SET "
                    "equity = EXCLUDED.equity, wallet_balance = EXCLUDED.wallet_balance, "
                    "available_balance = EXCLUDED.available_balance, "
                    "unrealised_pnl = EXCLUDED.unrealised_pnl, "
                    "realised_pnl = EXCLUDED.realised_pnl, "
                    "positions_count = EXCLUDED.positions_count, "
                    "margin_used = EXCLUDED.margin_used, "
                    "cumulative_pnl = EXCLUDED.cumulative_pnl, "
                    "daily_return_pct = EXCLUDED.daily_return_pct, "
                    "peak_equity = EXCLUDED.peak_equity, "
                    "drawdown_pct = EXCLUDED.drawdown_pct, "
                    "updated_at = now()",
                    (
                        snapshot["account_id"],
                        snapshot["snapshot_date"],
                        snapshot.get("equity", 0),
                        snapshot.get("wallet_balance", 0),
                        snapshot.get("available_balance", 0),
                        snapshot.get("unrealised_pnl", 0),
                        snapshot.get("realised_pnl", 0),
                        snapshot.get("positions_count", 0),
                        snapshot.get("margin_used", 0),
                        snapshot.get("cumulative_pnl", 0),
                        snapshot.get("daily_return_pct", 0),
                        snapshot.get("peak_equity", 0),
                        snapshot.get("drawdown_pct", 0),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_daily_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s AND snapshot_date>=%s AND snapshot_date<=%s "
                    "ORDER BY snapshot_date ASC",
                    (account_id, start_date, end_date),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_all_account_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                sql = (
                    "SELECT ds.* FROM daily_snapshots ds "
                    "JOIN trading_accounts ta ON ta.id = ds.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND ds.snapshot_date>=%s AND ds.snapshot_date<=%s "
                )
                params: list = [start_date, end_date]
                if account_type:
                    sql += "AND ta.account_type = %s "
                    params.append(account_type)
                sql += "ORDER BY ds.snapshot_date ASC"
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_latest_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s ORDER BY snapshot_date DESC LIMIT 1",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def get_previous_snapshot(self, account_id: str, before_date: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s AND snapshot_date < %s "
                    "ORDER BY snapshot_date DESC LIMIT 1",
                    (account_id, before_date),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    # ── High-Frequency Snapshots ──────────────────────────────────────

    def get_hf_snapshots(
        self, account_id: str, since_ts: str,
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM high_freq_snapshots "
                    "WHERE account_id=%s AND ts >= %s "
                    "ORDER BY ts ASC",
                    (account_id, since_ts),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_all_hf_snapshots(
        self, since_ts: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                sql = (
                    "SELECT hf.* FROM high_freq_snapshots hf "
                    "JOIN trading_accounts ta ON ta.id = hf.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND hf.ts >= %s "
                )
                params: list = [since_ts]
                if account_type:
                    sql += "AND ta.account_type = %s "
                    params.append(account_type)
                sql += "ORDER BY hf.ts ASC"
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def insert_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                batch_ts = datetime.now(timezone.utc)
                args = [
                    (s["account_id"], batch_ts, s["equity"], s["unrealised_pnl"],
                     s["realised_pnl"], s["balance"], s.get("position_count", 0))
                    for s in snapshots
                ]
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO high_freq_snapshots "
                    "(account_id, ts, equity, unrealised_pnl, realised_pnl, balance, position_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    args,
                )
                conn.commit()
                return len(args)
            except Exception:
                conn.rollback()
                raise

    _VALID_SNAPSHOT_TABLES = {"daily_snapshots", "high_freq_snapshots"}

    def cleanup_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        if before_ts:
            if is_hf:
                conditions.append("ts < (%s::date + INTERVAL '1 day')")
            else:
                conditions.append("snapshot_date <= %s")
            params.append(before_ts)
        if after_ts:
            if is_hf:
                conditions.append("ts >= %s::date")
            else:
                conditions.append("snapshot_date >= %s")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"DELETE FROM {table} WHERE {where}", params)
                count = cur.rowcount
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    def cleanup_old_hf_snapshots(self, max_age_days: int = 1095) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM high_freq_snapshots WHERE ts < NOW() - %s * INTERVAL '1 day'",
                    (max_age_days,),
                )
                count = cur.rowcount
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    def count_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        if before_ts:
            if is_hf:
                conditions.append("ts < (%s::date + INTERVAL '1 day')")
            else:
                conditions.append("snapshot_date <= %s")
            params.append(before_ts)
        if after_ts:
            if is_hf:
                conditions.append("ts >= %s::date")
            else:
                conditions.append("snapshot_date >= %s")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params)
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    # ── Strategies ──────────────────────────────────────────────────

    @staticmethod
    def _deserialize_strategy(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("config"), str):
            d["config"] = json.loads(d["config"])
        return d

    def insert_strategy(self, strategy: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO strategies (id, name, description, category, status, config, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        strategy["id"], strategy["name"], strategy.get("description", ""),
                        strategy.get("category", "swing"), strategy.get("status", "draft"),
                        json.dumps(strategy.get("config", {})),
                        strategy["created_at"], strategy["updated_at"],
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_strategies(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if category:
            conditions.append("category = %s")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "TRUE"
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(f"SELECT id, name, description, category, status, config, created_at, updated_at FROM strategies WHERE {where} ORDER BY updated_at DESC", params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        result = []
        for r in rows:
            result.append(self._deserialize_strategy(r))
        return result

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT id, name, description, category, status, config, created_at, updated_at FROM strategies WHERE id = %s", (strategy_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._deserialize_strategy(row)

    def update_strategy(self, strategy_id: str, **fields: Any) -> bool:
        allowed = {"name", "description", "category", "status", "config"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and not isinstance(updates["config"], str):
            updates["config"] = json.dumps(updates["config"])
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE strategies SET {set_clause} WHERE id = %s",
                    list(updates.values()) + [strategy_id],
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def delete_strategy(self, strategy_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    # ── Scheduled Scans ──────────────────────────────────────────────

    def insert_scheduled_scan(self, data: Dict[str, Any]) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scheduled_scans "
                    "(id, name, schedule_type, schedule_config, scan_config, status, "
                    "timezone, next_run_at, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        data["id"],
                        data["name"],
                        data["schedule_type"],
                        json.dumps(data["schedule_config"]),
                        json.dumps(data["scan_config"]),
                        data.get("status", "active"),
                        data.get("timezone", "UTC"),
                        data.get("next_run_at"),
                        data["created_at"],
                        data["updated_at"],
                    ),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise ValueError(f"Scheduled scan {data['id']} already exists")
            except Exception:
                conn.rollback()
                raise

    def update_scheduled_scan(self, schedule_id: str, fields: Dict[str, Any]) -> None:
        allowed = {
            "name", "schedule_type", "schedule_config", "scan_config",
            "status", "timezone", "next_run_at", "last_run_at",
            "last_scan_id", "consecutive_failures", "updated_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        for k in ("schedule_config", "scan_config"):
            if k in updates and isinstance(updates[k], dict):
                updates[k] = json.dumps(updates[k])
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scheduled_scans SET {set_clause} WHERE id=%s",
                    (*updates.values(), schedule_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_scheduled_scan(self, schedule_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM scheduled_scans WHERE id=%s", (schedule_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM scheduled_scans ORDER BY created_at DESC"
                )
                return [self._deserialize_schedule(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _deserialize_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        for k in ("schedule_config", "scan_config"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return d

    def get_scheduled_scan(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scheduled_scans WHERE id=%s", (schedule_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return self._deserialize_schedule(row) if row else None

    def get_due_scheduled_scans(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM scheduled_scans "
                    "WHERE status='active' AND next_run_at <= %s "
                    "ORDER BY next_run_at ASC LIMIT 5",
                    (now,),
                )
                return [self._deserialize_schedule(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    def claim_scheduled_scan(
        self, schedule_id: str, old_next: str, new_next: Optional[str]
    ) -> bool:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE scheduled_scans "
                    "SET next_run_at=%s, last_run_at=%s, updated_at=%s "
                    "WHERE id=%s AND next_run_at=%s AND status='active'",
                    (new_next, now, now, schedule_id, old_next),
                )
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def insert_schedule_execution(self, data: Dict[str, Any]) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO schedule_executions "
                    "(schedule_id, scan_id, status, started_at, completed_at, error_message) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        data["schedule_id"],
                        data.get("scan_id"),
                        data["status"],
                        data["started_at"],
                        data.get("completed_at"),
                        data.get("error_message"),
                    ),
                )
                exec_id = cur.fetchone()[0]
                conn.commit()
                return exec_id
            except Exception:
                conn.rollback()
                raise

    def update_schedule_execution(self, exec_id: int, fields: Dict[str, Any]) -> None:
        allowed = {"scan_id", "status", "completed_at", "error_message"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE schedule_executions SET {set_clause} WHERE id=%s",
                    (*updates.values(), exec_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_schedule_executions(
        self, schedule_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM schedule_executions "
                    "WHERE schedule_id=%s ORDER BY started_at DESC LIMIT %s",
                    (schedule_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    def cleanup_old_executions(self, days: int = 90, min_keep: int = 100) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM schedule_executions "
                    "WHERE started_at < %s "
                    "AND id NOT IN ("
                    "  SELECT id FROM ("
                    "    SELECT id, ROW_NUMBER() OVER (PARTITION BY schedule_id ORDER BY started_at DESC) AS rn "
                    "    FROM schedule_executions"
                    "  ) ranked WHERE rn <= %s"
                    ")",
                    (cutoff, min_keep),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    def update_scan_schedule_link(
        self, scan_id: str, schedule_id: str, triggered_by: str
    ) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE scans SET schedule_id=%s, triggered_by=%s WHERE scan_id=%s",
                    (schedule_id, triggered_by, scan_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def count_scheduled_scans(self) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM scheduled_scans")
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    def mark_orphaned_executions(self) -> int:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE schedule_executions SET status='failed', "
                    "completed_at=%s, error_message='Server restarted during execution' "
                    "WHERE status='started' AND started_at < %s",
                    (now, threshold),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    # ── Close Rules ──────────────────────────────────────────────

    def insert_close_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "trigger_type", "threshold_value", "reference_value",
                "status", "expires_at"]
        vals = {c: rule.get(c) for c in cols}
        if vals.get("status") is None:
            vals["status"] = "active"
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(["%s"] * len(vals))
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"INSERT INTO close_rules ({col_names}) VALUES ({placeholders}) RETURNING *",
                    list(vals.values()),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._serialize_row(row)

    def list_close_rules(self, account_id: str) -> list:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM close_rules WHERE account_id = %s ORDER BY created_at DESC",
                    (account_id,),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [self._serialize_row(r) for r in rows]

    def get_close_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM close_rules WHERE id = %s", (rule_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._serialize_row(row)

    def update_close_rule(self, rule_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"trigger_type", "threshold_value", "reference_value", "status", "expires_at", "triggered_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return None
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"UPDATE close_rules SET {set_clause} WHERE id = %s RETURNING *",
                    list(updates.values()) + [rule_id],
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._serialize_row(row)

    def atomic_trigger_rule(self, rule_id: str) -> bool:
        """Atomically set rule status to 'triggered' only if currently 'active'. Returns True if transitioned."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE close_rules SET status = 'triggered', triggered_at = now(), updated_at = now() "
                    "WHERE id = %s AND status = 'active' RETURNING id",
                    (rule_id,),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return row is not None

    def delete_close_rule(self, rule_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM close_executions WHERE rule_id = %s", (rule_id,))
                cur.execute("DELETE FROM close_rules WHERE id = %s", (rule_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def list_active_rules(self) -> list:
        """Fetch all active rules for non-deleted, active accounts."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT cr.* FROM close_rules cr "
                    "JOIN trading_accounts ta ON cr.account_id = ta.id "
                    "WHERE cr.status = 'active' AND ta.deleted_at IS NULL "
                    "AND ta.is_active = 1 "
                    "AND (cr.expires_at IS NULL OR cr.expires_at > now()) "
                    "ORDER BY cr.account_id, cr.created_at",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [self._serialize_row(r) for r in rows]

    def recover_stuck_triggered_rules(self, max_age_seconds: int = 120) -> int:
        """Revert rules stuck in 'triggered' state for longer than max_age_seconds."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE close_rules SET status = 'active', triggered_at = NULL "
                    "WHERE status = 'triggered' "
                    "AND triggered_at < now() - interval '1 second' * %s",
                    (max_age_seconds,),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    def count_active_rules_by_account(self) -> Dict[str, int]:
        """Return {account_id: count} for all accounts with active rules."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT account_id::text, COUNT(*) FROM close_rules "
                    "WHERE status = 'active' GROUP BY account_id",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {r[0]: r[1] for r in rows}

    def get_active_targets_by_account(self) -> Dict[str, list]:
        """Return {account_id: [{trigger_type, threshold_value, reference_value}]} for active rules."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT account_id::text, trigger_type, threshold_value, reference_value "
                    "FROM close_rules WHERE status = 'active' ORDER BY account_id, created_at",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        result: Dict[str, list] = {}
        for r in rows:
            result.setdefault(r[0], []).append({
                "trigger_type": r[1],
                "threshold_value": str(r[2]) if r[2] is not None else None,
                "reference_value": str(r[3]) if r[3] is not None else None,
            })
        return result

    def count_rules_for_account(self, account_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM close_rules WHERE account_id = %s AND status IN ('active', 'paused')",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row[0] if row else 0

    # ── Close Executions ─────────────────────────────────────────

    def insert_close_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "rule_id", "trigger_source", "total_positions",
                "closed_count", "failed_count", "results"]
        vals = {c: execution.get(c) for c in cols}
        if vals.get("results") and not isinstance(vals["results"], str):
            vals["results"] = json.dumps(vals["results"])
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(["%s"] * len(vals))
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"INSERT INTO close_executions ({col_names}) VALUES ({placeholders}) RETURNING *",
                    list(vals.values()),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._serialize_row(row)

    def list_close_executions(self, account_id: str, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        offset = (page - 1) * limit
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM close_executions WHERE account_id = %s",
                    (account_id,),
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    "SELECT * FROM close_executions WHERE account_id = %s "
                    "ORDER BY executed_at DESC LIMIT %s OFFSET %s",
                    (account_id, limit, offset),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {
            "items": [self._serialize_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def _serialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DB row to JSON-safe dict."""
        result = {}
        for k, v in dict(row).items():
            if isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, date):
                result[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                result[k] = str(v)
            elif isinstance(v, Decimal):
                result[k] = str(v)
            else:
                result[k] = v
        return result
