"""SQLite persistence layer with WAL mode and migration framework — TASK-004."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed','cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL CHECK(started_at GLOB '????-??-??T??:??:??*'),
    completed_at TEXT CHECK(completed_at IS NULL OR completed_at GLOB '????-??-??T??:??:??*'),
    error TEXT,
    instance_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON analysis_runs(ticker, analysis_date);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON analysis_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS report_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(run_id, section)
);

CREATE INDEX IF NOT EXISTS idx_reports_run_id ON report_sections(run_id);
"""

_MIGRATIONS: list[tuple[int, str]] = [
    (1, _SCHEMA_V1),
    # NOTE: SQLite's ALTER TABLE ADD COLUMN applies CHECK constraints only to new
    # rows written after this migration runs.  Rows that pre-date the migration and
    # were backfilled by the DEFAULT value are not re-validated.  This is acceptable
    # here because the DEFAULT 'stock' is always valid and legacy rows will never
    # contain an invalid value in practice.
    (2, "ALTER TABLE analysis_runs ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))"),
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
ALTER TABLE scan_results ADD COLUMN signal_source TEXT NOT NULL DEFAULT 'unknown'
"""),
]


class AnalysisDB:
    def __init__(self, db_path: str = "~/.tradingagents/cache/web_runs.db"):
        self._db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._instance_id = str(uuid.uuid4())
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            self._apply_migrations()
        except Exception:
            self._conn.close()
            raise

    def _apply_migrations(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]

            max_version = _MIGRATIONS[-1][0] if _MIGRATIONS else 0
            if current > max_version:
                raise RuntimeError(
                    f"Database schema v{current} is newer than this application supports "
                    f"(max v{max_version}). Please upgrade the application or restore from "
                    f"backup at {self._db_path}.backup.v{current}"
                )

            if current >= max_version:
                return

            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            backup_path = f"{self._db_path}.backup.v{current}"
            if not os.path.exists(backup_path):
                backup_conn = sqlite3.connect(backup_path)
                try:
                    self._conn.backup(backup_conn)
                finally:
                    backup_conn.close()

            for version, sql in _MIGRATIONS:
                if version <= current:
                    continue
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in sql.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            self._conn.execute(stmt)
                    self._conn.execute(f"PRAGMA user_version = {version}")
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise

    def insert_run(self, run: Dict[str, Any]) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO analysis_runs (run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
                self._conn.commit()
            except sqlite3.IntegrityError:
                self._conn.rollback()
                raise ValueError(f"Run {run['run_id']} already exists")

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        completed_at: Optional[str],
    ) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE analysis_runs SET status=?, error=?, completed_at=? "
                "WHERE run_id=? AND status='running'",
                (status, error, completed_at, run_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def save_report_section(self, run_id: str, section: str, content: str) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO report_sections (run_id, section, content) VALUES (?, ?, ?)",
                    (run_id, section, content),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # Parent run was deleted while this thread was still writing — ignore.
                self._conn.rollback()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

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
            conditions.append("ticker = ?")
            params.append(ticker)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if from_date:
            conditions.append("analysis_date >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("analysis_date <= ?")
            params.append(to_date)
        if asset_type:
            conditions.append("asset_type = ?")
            params.append(asset_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * limit

        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM analysis_runs {where}", params
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM analysis_runs {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def get_report_sections(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM report_sections WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def recover_orphans(self) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE analysis_runs SET status='failed', error='Server restarted — orphaned run' "
                "WHERE status='running'"
            )
            self._conn.commit()
            return cursor.rowcount

    def get_checkpoint_exists(self, ticker: str, date: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM analysis_runs WHERE ticker=? AND analysis_date=? LIMIT 1",
                (ticker, date),
            ).fetchone()
        return row is not None

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # report_sections has ON DELETE CASCADE but we rely on explicit delete
                # to be safe on older SQLite builds where FK cascade may be disabled at
                # connection level.
                self._conn.execute("DELETE FROM report_sections WHERE run_id=?", (run_id,))
                cursor = self._conn.execute("DELETE FROM analysis_runs WHERE run_id=?", (run_id,))
                self._conn.commit()
                return cursor.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise

    def delete_all_runs(self) -> int:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM report_sections")
                cursor = self._conn.execute("DELETE FROM analysis_runs")
                self._conn.commit()
                return cursor.rowcount
            except Exception:
                self._conn.rollback()
                raise

    def delete_all_checkpoints(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM analysis_runs WHERE status IN ('completed', 'failed', 'cancelled')")
            self._conn.commit()
            return cursor.rowcount

    def delete_ticker_checkpoints(self, ticker: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM analysis_runs WHERE ticker=? AND status IN ('completed', 'failed', 'cancelled')",
                (ticker,),
            )
            self._conn.commit()
            return cursor.rowcount

    def checkpoint(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def health_check(self) -> str:
        try:
            with self._lock:
                self._conn.execute("SELECT 1")
            return "ok"
        except Exception:
            return "degraded"

    # ── Scanner persistence ──────────────────────────────────────────

    def insert_scan(self, scan: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO scans (scan_id, status, config, total, completed, failed, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            self._conn.commit()

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        allowed = {"status", "total", "completed", "failed", "completed_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with self._lock:
            self._conn.execute(
                f"UPDATE scans SET {set_clause} WHERE scan_id=?",
                list(updates.values()) + [scan_id],
            )
            self._conn.commit()

    def insert_scan_result(self, scan_id: str, result: Dict[str, Any]) -> None:
        # Validate values against DB CHECK constraints before writing so we get
        # a clear error rather than a silent constraint violation.
        direction = result.get("direction", "hold")
        if direction not in ("buy", "sell", "hold"):
            logger.error("insert_scan_result: invalid direction %r — forcing hold", direction)
            direction = "hold"
        confidence = result.get("confidence", "none")
        if confidence not in ("high", "moderate", "low", "none"):
            logger.error("insert_scan_result: invalid confidence %r — forcing none", confidence)
            confidence = "none"
        score = int(result.get("score", 0))
        score = max(-10, min(10, score))
        status = result.get("status", "failed")
        if status not in ("completed", "failed", "cancelled", "unknown"):
            status = "unknown"

        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO scan_results "
                "(scan_id, ticker, run_id, status, direction, confidence, score, decision_summary, signal_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            self._conn.commit()

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scans WHERE scan_id=?", (scan_id,)
            ).fetchone()
            if not row:
                return None
            scan = dict(row)
            results = self._conn.execute(
                "SELECT ticker, run_id, status, direction, confidence, score, decision_summary, signal_source "
                "FROM scan_results WHERE scan_id=? ORDER BY ABS(score) DESC",
                (scan_id,),
            ).fetchall()
            scan["results"] = [dict(r) for r in results]
        return scan

    def list_scans(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scans ORDER BY started_at DESC"
            ).fetchall()
            scans = []
            for row in rows:
                scan = dict(row)
                results = self._conn.execute(
                    "SELECT ticker, run_id, status, direction, confidence, score, decision_summary, signal_source "
                    "FROM scan_results WHERE scan_id=? ORDER BY ABS(score) DESC",
                    (scan["scan_id"],),
                ).fetchall()
                scan["results"] = [dict(r) for r in results]
                scans.append(scan)
        return scans

    def get_scan_completed_tickers(self, scan_id: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker FROM scan_results WHERE scan_id=?", (scan_id,)
            ).fetchall()
        return {r[0] for r in rows}

    def increment_scan_counter(self, scan_id: str, field: str) -> None:
        if field not in ("completed", "failed"):
            return
        with self._lock:
            self._conn.execute(
                f"UPDATE scans SET {field} = {field} + 1 WHERE scan_id=?",
                (scan_id,),
            )
            self._conn.commit()

    def get_running_scans(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scans WHERE status='running'"
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
