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
    (2, "ALTER TABLE analysis_runs ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))"),
    (3, "CREATE INDEX IF NOT EXISTS idx_runs_asset_type_started ON analysis_runs(asset_type, started_at DESC)"),
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
            self._conn.execute(
                "INSERT OR REPLACE INTO report_sections (run_id, section, content) VALUES (?, ?, ?)",
                (run_id, section, content),
            )
            self._conn.commit()

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
        limit = min(max(limit, 1), 100)
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
            cursor = self._conn.execute(
                "DELETE FROM analysis_runs WHERE run_id=?", (run_id,)
            )
            self._conn.execute(
                "DELETE FROM report_sections WHERE run_id=?", (run_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_all_runs(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM analysis_runs")
            self._conn.execute("DELETE FROM report_sections")
            self._conn.commit()
            return cursor.rowcount

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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
