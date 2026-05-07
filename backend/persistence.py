"""PostgreSQL persistence layer with migration framework and connection resilience."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from contextlib import contextmanager
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
                    f"SELECT * FROM analysis_runs {where} "
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
                    "(scan_id, status, config, total, completed, failed, started_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        scan["scan_id"],
                        scan.get("status", "running"),
                        scan.get("config", "{}"),
                        scan.get("total", 0),
                        scan.get("completed", 0),
                        scan.get("failed", 0),
                        scan["started_at"],
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
                    "SELECT scan_id, ticker, run_id, status, direction, confidence, "
                    "score, decision_summary, signal_source "
                    "FROM scan_results WHERE scan_id = ANY(%s) "
                    "ORDER BY ABS(score) DESC",
                    (scan_ids,),
                )
                all_results = cur.fetchall()
                results_by_scan: Dict[str, list] = {s["scan_id"]: [] for s in scans}
                for r in all_results:
                    rd = dict(r)
                    sid = rd.pop("scan_id")
                    results_by_scan[sid].append(rd)
                for scan in scans:
                    scan["results"] = results_by_scan[scan["scan_id"]]
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

    def close(self) -> None:
        self._pool.closeall()
