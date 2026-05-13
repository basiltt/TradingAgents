"""Async PostgreSQL persistence layer using asyncpg with connection pooling."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

# ── Schema & Migrations (identical to persistence.py) ──────────────────

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
    (19, "ALTER TABLE closed_pnl_records ALTER COLUMN created_time TYPE BIGINT"),
    (20, """
CREATE TABLE IF NOT EXISTS trading_cycles (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','placing_trades','running','stopping','completed','stopped','failed')),
    trade_direction VARCHAR(10) NOT NULL CHECK (trade_direction IN ('straight','reverse')),
    leverage INTEGER NOT NULL CHECK (leverage BETWEEN 1 AND 125),
    capital_pct NUMERIC(5,2) NOT NULL CHECK (capital_pct > 0 AND capital_pct <= 100),
    take_profit_pct NUMERIC(6,2) CHECK (take_profit_pct > 0 AND take_profit_pct <= 1000),
    stop_loss_pct NUMERIC(6,2) CHECK (stop_loss_pct > 0 AND stop_loss_pct <= 1000),
    min_score INTEGER NOT NULL DEFAULT 3 CHECK (min_score BETWEEN -10 AND 10),
    min_confidence VARCHAR(10) NOT NULL DEFAULT 'moderate'
        CHECK (min_confidence IN ('none','low','moderate','high')),
    signal_filter VARCHAR(4) NOT NULL DEFAULT 'both'
        CHECK (signal_filter IN ('buy','sell','both')),
    max_trades INTEGER NOT NULL CHECK (max_trades BETWEEN 1 AND 20),
    target_type VARCHAR(10) NOT NULL CHECK (target_type IN ('percentage','amount')),
    target_value NUMERIC(12,2) NOT NULL CHECK (target_value > 0),
    max_drawdown_pct NUMERIC(5,2) NOT NULL CHECK (max_drawdown_pct > 0 AND max_drawdown_pct <= 100),
    initial_equity NUMERIC(14,4),
    final_pnl NUMERIC(14,4),
    stop_reason VARCHAR(200),
    trades_placed INTEGER NOT NULL DEFAULT 0,
    trades_failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_account_status ON trading_cycles(account_id, status);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_created ON trading_cycles(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_scan_id ON trading_cycles(scan_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_cycle ON trading_cycles(account_id)
    WHERE status IN ('pending','placing_trades','running','stopping');
CREATE INDEX IF NOT EXISTS idx_trading_cycles_stuck ON trading_cycles(status, created_at)
    WHERE status IN ('running','placing_trades','stopping')
"""),
    (21, """
CREATE TABLE IF NOT EXISTS cycle_trades (
    id SERIAL PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES trading_cycles(id) ON DELETE RESTRICT,
    symbol VARCHAR(30) NOT NULL,
    order_id VARCHAR(50),
    order_link_id VARCHAR(50),
    side VARCHAR(4) NOT NULL CHECK (side IN ('Buy','Sell')),
    qty NUMERIC(18,8),
    entry_price NUMERIC(18,8),
    status VARCHAR(15) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','submitted','filled','failed','cancelled')),
    error_msg VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cycle_trades_cycle_id ON cycle_trades(cycle_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cycle_trades_order_link_id ON cycle_trades(order_link_id)
    WHERE order_link_id IS NOT NULL
"""),
    (22, """
ALTER TABLE close_rules ADD COLUMN IF NOT EXISTS cycle_id INTEGER REFERENCES trading_cycles(id) ON DELETE RESTRICT;
ALTER TABLE close_rules DROP CONSTRAINT IF EXISTS close_rules_status_check;
ALTER TABLE close_rules ADD CONSTRAINT close_rules_status_check
    CHECK (status IN ('active','paused','triggered','executed','expired','pending_activation'));
CREATE INDEX IF NOT EXISTS idx_close_rules_cycle_id ON close_rules(cycle_id) WHERE cycle_id IS NOT NULL
"""),
    (23, """
CREATE INDEX IF NOT EXISTS idx_scans_started_desc ON scans(started_at DESC)
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


class AsyncAnalysisDB:

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _default_dsn()
        self._instance_id = str(uuid.uuid4())
        self._pool: asyncpg.Pool | None = None
        self._sync_pool = None
        self._closed = False
        self._sync_sem: threading.Semaphore | None = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=int(os.environ.get("DB_POOL_MIN", "2")),
            max_size=int(os.environ.get("DB_POOL_MAX", "10")),
            command_timeout=int(os.environ.get("DB_COMMAND_TIMEOUT", "10")),
            max_inactive_connection_lifetime=300,
        )
        # Sync bridge for graph executor threads
        import psycopg2.pool
        _sync_max = int(os.environ.get("DB_SYNC_POOL_MAX", os.environ.get("GRAPH_EXECUTOR_WORKERS", "8")))
        self._sync_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=_sync_max, dsn=self._dsn, connect_timeout=10,
        )
        self._sync_sem = threading.Semaphore(_sync_max)
        await self._apply_migrations()

    @asynccontextmanager
    async def _transaction(self):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def _apply_migrations(self) -> None:
        # Use a dedicated connection (not pool) for advisory lock
        conn = await asyncpg.connect(dsn=self._dsn)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL DEFAULT 0)"
            )
            # Advisory lock prevents concurrent migration from multiple instances
            await conn.execute("SELECT pg_advisory_lock(8675309)")
            try:
                row = await conn.fetchrow("SELECT version FROM schema_version")
                if row is None:
                    await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
                    current = 0
                else:
                    current = row["version"]

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
                    async with conn.transaction():
                        for stmt in sql.split(";"):
                            stmt = stmt.strip()
                            if stmt:
                                await conn.execute(stmt)
                        await conn.execute(
                            "UPDATE schema_version SET version = $1", version
                        )
            finally:
                await conn.execute("SELECT pg_advisory_unlock(8675309)")
        finally:
            await conn.close()

    # ── Health / lifecycle ──────────────────────────────────────────

    def is_healthy(self) -> bool:
        return self._pool is not None and not self._pool.is_closing()

    async def close(self):
        self._closed = True
        if self._sync_pool:
            self._sync_pool.closeall()
        if self._pool:
            await self._pool.close()

    # ── Sync bridge (for graph executor threads) ───────────────────

    @contextmanager
    def _get_sync_conn(self):
        if self._closed:
            raise RuntimeError("Database is shutting down")
        if not self._sync_sem.acquire(timeout=10):
            raise RuntimeError("Sync connection pool exhausted (timeout=10s)")
        try:
            conn = self._sync_pool.getconn()
            try:
                yield conn
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                close = getattr(conn, "closed", 0) != 0
                self._sync_pool.putconn(conn, close=close)
        finally:
            self._sync_sem.release()

    def sync_save_report_section(self, run_id, section, content):
        with self._get_sync_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO report_sections (run_id, section, content) VALUES (%s, %s, %s) "
                "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                (run_id, section, content),
            )
            conn.commit()

    def sync_update_run_status(self, run_id, status, error, completed_at):
        with self._get_sync_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE analysis_runs SET status=%s, error=%s, completed_at=%s "
                "WHERE run_id=%s AND status='running'",
                (status, error, completed_at, run_id),
            )
            conn.commit()

    # ── Pure helpers (no DB) ───────────────────────────────────────

    @staticmethod
    def _deserialize_strategy(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("config"), str):
            d["config"] = json.loads(d["config"])
        return d

    @staticmethod
    def _deserialize_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        for k in ("schedule_config", "scan_config"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return d

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

    # ── Analysis Runs ──────────────────────────────────────────────

    async def insert_run(self, run: Dict[str, Any]) -> None:
        try:
            await self._pool.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                run["run_id"],
                run["ticker"],
                run["analysis_date"],
                run["status"],
                run.get("config", "{}"),
                run["started_at"],
                self._instance_id,
                run.get("asset_type", "stock"),
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Run {run['run_id']} already exists")

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        completed_at: Optional[str],
    ) -> bool:
        result = await self._pool.execute(
            "UPDATE analysis_runs SET status=$1, error=$2, completed_at=$3 "
            "WHERE run_id=$4 AND status='running'",
            status, error, completed_at, run_id,
        )
        return int(result.split()[-1]) > 0

    async def save_report_section(self, run_id: str, section: str, content: str) -> None:
        try:
            await self._pool.execute(
                "INSERT INTO report_sections (run_id, section, content) VALUES ($1, $2, $3) "
                "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                run_id, section, content,
            )
        except asyncpg.UniqueViolationError:
            pass

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM analysis_runs WHERE run_id=$1", run_id
        )
        return dict(row) if row else None

    async def list_runs(
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
        idx = 0

        if ticker:
            idx += 1
            conditions.append(f"ticker = ${idx}")
            params.append(ticker)
        if status:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)
        if from_date:
            idx += 1
            conditions.append(f"analysis_date >= ${idx}")
            params.append(from_date)
        if to_date:
            idx += 1
            conditions.append(f"analysis_date <= ${idx}")
            params.append(to_date)
        if asset_type:
            idx += 1
            conditions.append(f"asset_type = ${idx}")
            params.append(asset_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * limit

        total = await self._pool.fetchval(
            f"SELECT COUNT(*) FROM analysis_runs {where}", *params
        )
        rows = await self._pool.fetch(
            f"SELECT run_id, ticker, analysis_date, status, started_at, "
            f"completed_at, asset_type, config FROM analysis_runs {where} "
            f"ORDER BY started_at DESC LIMIT ${idx + 1} OFFSET ${idx + 2}",
            *params, limit, offset,
        )
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def get_report_sections(self, run_id: str) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM report_sections WHERE run_id=$1 ORDER BY id", run_id
        )
        return [dict(r) for r in rows]

    async def recover_orphans(self) -> int:
        result = await self._pool.execute(
            "UPDATE analysis_runs SET status='failed', "
            "error='Server restarted — orphaned run' "
            "WHERE status='running'"
        )
        return int(result.split()[-1])

    async def get_checkpoint_exists(self, ticker: str, date: str) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM analysis_runs WHERE ticker=$1 AND analysis_date=$2 LIMIT 1",
            ticker, date,
        )
        return row is not None

    async def delete_run(self, run_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM analysis_runs WHERE run_id=$1", run_id
        )
        return int(result.split()[-1]) > 0

    async def delete_all_runs(self) -> int:
        result = await self._pool.execute("DELETE FROM analysis_runs")
        return int(result.split()[-1])

    async def delete_all_checkpoints(self) -> int:
        result = await self._pool.execute(
            "DELETE FROM analysis_runs "
            "WHERE status IN ('completed', 'failed', 'cancelled')"
        )
        return int(result.split()[-1])

    async def delete_ticker_checkpoints(self, ticker: str) -> int:
        result = await self._pool.execute(
            "DELETE FROM analysis_runs "
            "WHERE ticker=$1 AND status IN ('completed', 'failed', 'cancelled')",
            ticker,
        )
        return int(result.split()[-1])

    async def checkpoint(self) -> None:
        pass

    async def health_check(self) -> str:
        try:
            await self._pool.fetchval("SELECT 1")
            return "ok"
        except Exception:
            return "degraded"

    # ── Scanner persistence ──────────────────────────────────────────

    async def insert_scan(self, scan: Dict[str, Any]) -> None:
        await self._pool.execute(
            "INSERT INTO scans "
            "(scan_id, status, config, total, completed, failed, started_at, schedule_id, triggered_by) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            scan["scan_id"],
            scan.get("status", "running"),
            scan.get("config", "{}"),
            scan.get("total", 0),
            scan.get("completed", 0),
            scan.get("failed", 0),
            scan["started_at"],
            scan.get("schedule_id"),
            scan.get("triggered_by", "manual"),
        )

    async def update_scan(self, scan_id: str, **fields: Any) -> None:
        allowed = {"status", "total", "completed", "failed", "completed_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(scan_id)
        await self._pool.execute(
            f"UPDATE scans SET {', '.join(parts)} WHERE scan_id=${len(params)}",
            *params,
        )

    async def insert_scan_result(self, scan_id: str, result: Dict[str, Any]) -> None:
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
            logger.warning("insert_scan_result: invalid status %r — forcing unknown", status)
            status = "unknown"

        await self._pool.execute(
            "INSERT INTO scan_results "
            "(scan_id, ticker, run_id, status, direction, confidence, "
            "score, decision_summary, signal_source) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
            "ON CONFLICT (scan_id, ticker) DO UPDATE SET "
            "run_id = EXCLUDED.run_id, status = EXCLUDED.status, "
            "direction = EXCLUDED.direction, confidence = EXCLUDED.confidence, "
            "score = EXCLUDED.score, decision_summary = EXCLUDED.decision_summary, "
            "signal_source = EXCLUDED.signal_source",
            scan_id,
            result["ticker"],
            result.get("run_id"),
            status,
            direction,
            confidence,
            score,
            result.get("decision_summary", ""),
            result.get("signal_source", "unknown"),
        )

    async def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM scans WHERE scan_id=$1", scan_id
        )
        if not row:
            return None
        scan = dict(row)
        results = await self._pool.fetch(
            "SELECT ticker, run_id, status, direction, confidence, score, "
            "decision_summary, signal_source "
            "FROM scan_results WHERE scan_id=$1 ORDER BY ABS(score) DESC",
            scan_id,
        )
        scan["results"] = [dict(r) for r in results]
        return scan

    async def list_scans(self) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT scan_id, status, config, total, completed, failed, "
            "started_at, completed_at, schedule_id, triggered_by "
            "FROM scans ORDER BY started_at DESC LIMIT 50"
        )
        scans = [dict(r) for r in rows]
        if not scans:
            return []
        scan_ids = [s["scan_id"] for s in scans]
        counts = await self._pool.fetch(
            "SELECT scan_id, direction, COUNT(*) as cnt "
            "FROM scan_results WHERE scan_id = ANY($1) "
            "GROUP BY scan_id, direction",
            scan_ids,
        )
        counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
        for row in counts:
            counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
        for scan in scans:
            scan["results"] = []
            scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
        return scans

    async def get_scan_completed_tickers(self, scan_id: str) -> set[str]:
        rows = await self._pool.fetch(
            "SELECT ticker FROM scan_results WHERE scan_id=$1", scan_id
        )
        return {r["ticker"] for r in rows}

    async def increment_scan_counter(self, scan_id: str, field: str) -> None:
        if field not in ("completed", "failed"):
            return
        await self._pool.execute(
            f"UPDATE scans SET {field} = {field} + 1 WHERE scan_id=$1",
            scan_id,
        )

    async def get_running_scans(self) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM scans WHERE status='running'"
        )
        return [dict(r) for r in rows]

    async def delete_scan(self, scan_id: str) -> Dict[str, Any]:
        """Delete a scan and cascade-delete its associated analysis runs."""
        async with self._transaction() as conn:
            run_rows = await conn.fetch(
                "SELECT run_id FROM scan_results WHERE scan_id=$1 AND run_id IS NOT NULL",
                scan_id,
            )
            run_ids = [r["run_id"] for r in run_rows]

            deleted_sections = 0
            deleted_analyses = 0
            if run_ids:
                result = await conn.execute(
                    "DELETE FROM report_sections WHERE run_id = ANY($1)", run_ids
                )
                deleted_sections = int(result.split()[-1])
                result = await conn.execute(
                    "DELETE FROM analysis_runs WHERE run_id = ANY($1)", run_ids
                )
                deleted_analyses = int(result.split()[-1])

            result = await conn.execute(
                "DELETE FROM scan_results WHERE scan_id=$1", scan_id
            )
            deleted_results = int(result.split()[-1])

            result = await conn.execute(
                "DELETE FROM scans WHERE scan_id=$1", scan_id
            )
            scan_deleted = int(result.split()[-1])

        if scan_deleted == 0:
            return {}
        return {
            "deleted_results": deleted_results,
            "deleted_analyses": deleted_analyses,
            "deleted_sections": deleted_sections,
        }

    async def get_scan_analysis_count(self, scan_id: str) -> int:
        return await self._pool.fetchval(
            "SELECT COUNT(*) FROM scan_results WHERE scan_id=$1 AND run_id IS NOT NULL",
            scan_id,
        )

    # ── Trading Accounts persistence ────────────────────────────────────

    async def insert_account(self, account: Dict[str, Any]) -> None:
        await self._pool.execute(
            "INSERT INTO trading_accounts "
            "(id, label, account_type, api_key_masked, api_key_encrypted, "
            "api_secret_encrypted, key_version, is_active, bybit_uid, "
            "last_connected_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
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
        )

    async def list_accounts(self) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT id, label, account_type, api_key_masked, is_active, "
            "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
            "include_in_analytics "
            "FROM trading_accounts WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT id, label, account_type, api_key_masked, is_active, "
            "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
            "include_in_analytics "
            "FROM trading_accounts WHERE id=$1 AND deleted_at IS NULL",
            account_id,
        )
        return dict(row) if row else None

    async def get_account_credentials(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT id, account_type, api_key_encrypted, api_secret_encrypted "
            "FROM trading_accounts WHERE id=$1 AND deleted_at IS NULL",
            account_id,
        )
        if not row:
            return None
        d = dict(row)
        # asyncpg returns memoryview for BYTEA — convert to bytes
        d["api_key_encrypted"] = bytes(d["api_key_encrypted"])
        d["api_secret_encrypted"] = bytes(d["api_secret_encrypted"])
        return d

    async def update_account(self, account_id: str, **fields: Any) -> bool:
        allowed = {"label", "is_active", "bybit_uid", "last_connected_at", "last_error", "include_in_analytics"}
        nullable = {"last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed and (v is not None or k in nullable)}
        if not updates:
            return False
        updates["updated_at"] = fields.get("updated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(account_id)
        result = await self._pool.execute(
            f"UPDATE trading_accounts SET {', '.join(parts)} WHERE id=${len(params)} AND deleted_at IS NULL",
            *params,
        )
        return int(result.split()[-1]) > 0

    async def rotate_account_credentials(
        self, account_id: str, api_key_masked: str,
        api_key_encrypted: bytes, api_secret_encrypted: bytes, updated_at: str,
    ) -> bool:
        result = await self._pool.execute(
            "UPDATE trading_accounts SET api_key_masked=$1, api_key_encrypted=$2, "
            "api_secret_encrypted=$3, last_error=NULL, updated_at=$4 "
            "WHERE id=$5 AND deleted_at IS NULL",
            api_key_masked, api_key_encrypted, api_secret_encrypted, updated_at, account_id,
        )
        return int(result.split()[-1]) > 0

    async def soft_delete_account(self, account_id: str, deleted_at: str) -> bool:
        result = await self._pool.execute(
            "UPDATE trading_accounts SET deleted_at=$1, is_active=0, updated_at=$1 "
            "WHERE id=$2 AND deleted_at IS NULL",
            deleted_at, account_id,
        )
        return int(result.split()[-1]) > 0

    # ── Closed PnL persistence ──────────────────────────────────────────

    async def insert_closed_pnl_records(self, account_id: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        inserted = 0
        for rec in records:
            try:
                await self._pool.execute(
                    "INSERT INTO closed_pnl_records "
                    "(account_id, symbol, side, qty, avg_entry_price, avg_exit_price, "
                    "closed_pnl, leverage, created_time, bybit_order_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
                    "ON CONFLICT (account_id, bybit_order_id) DO NOTHING",
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
                )
                inserted += 1
            except asyncpg.UniqueViolationError:
                pass
            except Exception:
                logger.exception("Failed to insert closed PnL record: %s", rec.get("orderId"))
        return inserted

    async def get_closed_pnl(
        self, account_id: str, start_time: int, end_time: int,
        page: int = 1, limit: int = 50,
    ) -> Dict[str, Any]:
        offset = (page - 1) * limit
        total = await self._pool.fetchval(
            "SELECT COUNT(*) FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3",
            account_id, start_time, end_time,
        )
        rows = await self._pool.fetch(
            "SELECT * FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3 "
            "ORDER BY created_time DESC LIMIT $4 OFFSET $5",
            account_id, start_time, end_time, limit, offset,
        )
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    async def get_closed_pnl_summary(
        self, account_id: str, start_time: int, end_time: int,
    ) -> Dict[str, Any]:
        rows = await self._pool.fetch(
            "SELECT closed_pnl FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3",
            account_id, start_time, end_time,
        )
        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }
        vals = [r["closed_pnl"] for r in rows]
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v < 0]
        total_pnl = sum(vals)
        total_count = len(vals)
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

    async def get_portfolio_pnl_summary(
        self, start_time: int, end_time: int,
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        sql = (
            "SELECT cpr.closed_pnl FROM closed_pnl_records cpr "
            "JOIN trading_accounts ta ON ta.id = cpr.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND cpr.created_time>=$1 AND cpr.created_time<=$2"
        )
        params: list = [start_time, end_time]
        if account_type:
            sql += " AND ta.account_type = $3"
            params.append(account_type)
        rows = await self._pool.fetch(sql, *params)

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }
        vals = [r["closed_pnl"] for r in rows]
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v < 0]
        total_pnl = sum(vals)
        total_count = len(vals)
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

    async def get_latest_closed_pnl_time(self, account_id: str) -> Optional[int]:
        val = await self._pool.fetchval(
            "SELECT MAX(created_time) FROM closed_pnl_records WHERE account_id=$1",
            account_id,
        )
        return val if val else None

    # ── Daily Snapshots ────────────────────────────────────────────────

    async def upsert_daily_snapshot(self, snapshot: Dict[str, Any]) -> None:
        await self._pool.execute(
            "INSERT INTO daily_snapshots "
            "(account_id, snapshot_date, equity, wallet_balance, available_balance, "
            "unrealised_pnl, realised_pnl, positions_count, margin_used, "
            "cumulative_pnl, daily_return_pct, peak_equity, drawdown_pct) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
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
        )

    async def get_daily_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 AND snapshot_date>=$2 AND snapshot_date<=$3 "
            "ORDER BY snapshot_date ASC",
            account_id, start_date, end_date,
        )
        return [dict(r) for r in rows]

    async def get_all_account_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT ds.* FROM daily_snapshots ds "
            "JOIN trading_accounts ta ON ta.id = ds.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND ds.snapshot_date>=$1 AND ds.snapshot_date<=$2 "
        )
        params: list = [start_date, end_date]
        if account_type:
            sql += "AND ta.account_type = $3 "
            params.append(account_type)
        sql += "ORDER BY ds.snapshot_date ASC"
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def get_latest_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 ORDER BY snapshot_date DESC LIMIT 1",
            account_id,
        )
        return dict(row) if row else None

    async def get_previous_snapshot(self, account_id: str, before_date: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 AND snapshot_date < $2 "
            "ORDER BY snapshot_date DESC LIMIT 1",
            account_id, before_date,
        )
        return dict(row) if row else None

    # ── High-Frequency Snapshots ──────────────────────────────────────

    async def get_hf_snapshots(
        self, account_id: str, since_ts: datetime,
    ) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM high_freq_snapshots "
            "WHERE account_id=$1 AND ts >= $2 "
            "ORDER BY ts ASC",
            account_id, since_ts,
        )
        return [dict(r) for r in rows]

    async def get_all_hf_snapshots(
        self, since_ts: datetime, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT hf.* FROM high_freq_snapshots hf "
            "JOIN trading_accounts ta ON ta.id = hf.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND hf.ts >= $1 "
        )
        params: list = [since_ts]
        if account_type:
            sql += "AND ta.account_type = $2 "
            params.append(account_type)
        sql += "ORDER BY hf.ts ASC"
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def insert_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        batch_ts = datetime.now(timezone.utc)
        args = [
            (s["account_id"], batch_ts, s["equity"], s["unrealised_pnl"],
             s["realised_pnl"], s["balance"], s.get("position_count", 0))
            for s in snapshots
        ]
        async with self._transaction() as conn:
            await conn.executemany(
                "INSERT INTO high_freq_snapshots "
                "(account_id, ts, equity, unrealised_pnl, realised_pnl, balance, position_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                args,
            )
        return len(args)

    _VALID_SNAPSHOT_TABLES = {"daily_snapshots", "high_freq_snapshots"}

    async def cleanup_snapshots(
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
        idx = 0
        if account_id:
            idx += 1
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
        if before_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts < (${idx}::date + INTERVAL '1 day')")
            else:
                conditions.append(f"snapshot_date <= ${idx}")
            params.append(before_ts)
        if after_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts >= ${idx}::date")
            else:
                conditions.append(f"snapshot_date >= ${idx}")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        result = await self._pool.execute(
            f"DELETE FROM {table} WHERE {where}", *params
        )
        return int(result.split()[-1])

    async def cleanup_old_hf_snapshots(self, max_age_days: int = 1095) -> int:
        result = await self._pool.execute(
            "DELETE FROM high_freq_snapshots WHERE ts < NOW() - make_interval(days => $1)",
            max_age_days,
        )
        return int(result.split()[-1])

    async def count_snapshots(
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
        idx = 0
        if account_id:
            idx += 1
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
        if before_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts < (${idx}::date + INTERVAL '1 day')")
            else:
                conditions.append(f"snapshot_date <= ${idx}")
            params.append(before_ts)
        if after_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts >= ${idx}::date")
            else:
                conditions.append(f"snapshot_date >= ${idx}")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        return await self._pool.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", *params
        )

    # ── Strategies ──────────────────────────────────────────────────

    async def insert_strategy(self, strategy: Dict[str, Any]) -> None:
        await self._pool.execute(
            "INSERT INTO strategies (id, name, description, category, status, config, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            strategy["id"], strategy["name"], strategy.get("description", ""),
            strategy.get("category", "swing"), strategy.get("status", "draft"),
            json.dumps(strategy.get("config", {})),
            strategy["created_at"], strategy["updated_at"],
        )

    async def list_strategies(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions = []
        params: list = []
        idx = 0
        if status:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)
        if category:
            idx += 1
            conditions.append(f"category = ${idx}")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "TRUE"
        rows = await self._pool.fetch(
            f"SELECT id, name, description, category, status, config, created_at, updated_at "
            f"FROM strategies WHERE {where} ORDER BY updated_at DESC",
            *params,
        )
        return [self._deserialize_strategy(r) for r in rows]

    async def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT id, name, description, category, status, config, created_at, updated_at "
            "FROM strategies WHERE id = $1",
            strategy_id,
        )
        if not row:
            return None
        return self._deserialize_strategy(row)

    async def update_strategy(self, strategy_id: str, **fields: Any) -> bool:
        allowed = {"name", "description", "category", "status", "config"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and not isinstance(updates["config"], str):
            updates["config"] = json.dumps(updates["config"])
        updates["updated_at"] = datetime.now(timezone.utc)
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k} = ${i}")
            params.append(v)
        params.append(strategy_id)
        result = await self._pool.execute(
            f"UPDATE strategies SET {', '.join(parts)} WHERE id = ${len(params)}",
            *params,
        )
        return int(result.split()[-1]) > 0

    async def delete_strategy(self, strategy_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM strategies WHERE id = $1", strategy_id
        )
        return int(result.split()[-1]) > 0

    # ── Scheduled Scans ──────────────────────────────────────────────

    async def insert_scheduled_scan(self, data: Dict[str, Any]) -> None:
        try:
            await self._pool.execute(
                "INSERT INTO scheduled_scans "
                "(id, name, schedule_type, schedule_config, scan_config, status, "
                "timezone, next_run_at, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
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
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Scheduled scan {data['id']} already exists")

    async def update_scheduled_scan(self, schedule_id: str, fields: Dict[str, Any]) -> None:
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
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(schedule_id)
        await self._pool.execute(
            f"UPDATE scheduled_scans SET {', '.join(parts)} WHERE id=${len(params)}",
            *params,
        )

    async def delete_scheduled_scan(self, schedule_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM scheduled_scans WHERE id=$1", schedule_id
        )
        return int(result.split()[-1]) > 0

    async def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM scheduled_scans ORDER BY created_at DESC"
        )
        return [self._deserialize_schedule(r) for r in rows]

    async def get_scheduled_scan(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM scheduled_scans WHERE id=$1", schedule_id
        )
        return self._deserialize_schedule(row) if row else None

    async def get_due_scheduled_scans(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = await self._pool.fetch(
            "SELECT * FROM scheduled_scans "
            "WHERE status='active' AND next_run_at <= $1 "
            "ORDER BY next_run_at ASC LIMIT 5",
            now,
        )
        return [self._deserialize_schedule(r) for r in rows]

    async def claim_scheduled_scan(
        self, schedule_id: str, old_next: str, new_next: Optional[str]
    ) -> bool:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self._pool.execute(
            "UPDATE scheduled_scans "
            "SET next_run_at=$1, last_run_at=$2, updated_at=$2 "
            "WHERE id=$3 AND next_run_at=$4 AND status='active'",
            new_next, now, schedule_id, old_next,
        )
        return int(result.split()[-1]) > 0

    async def insert_schedule_execution(self, data: Dict[str, Any]) -> int:
        return await self._pool.fetchval(
            "INSERT INTO schedule_executions "
            "(schedule_id, scan_id, status, started_at, completed_at, error_message) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            data["schedule_id"],
            data.get("scan_id"),
            data["status"],
            data["started_at"],
            data.get("completed_at"),
            data.get("error_message"),
        )

    async def update_schedule_execution(self, exec_id: int, fields: Dict[str, Any]) -> None:
        allowed = {"scan_id", "status", "completed_at", "error_message"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(exec_id)
        await self._pool.execute(
            f"UPDATE schedule_executions SET {', '.join(parts)} WHERE id=${len(params)}",
            *params,
        )

    async def list_schedule_executions(
        self, schedule_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM schedule_executions "
            "WHERE schedule_id=$1 ORDER BY started_at DESC LIMIT $2",
            schedule_id, limit,
        )
        return [dict(r) for r in rows]

    async def cleanup_old_executions(self, days: int = 90, min_keep: int = 100) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self._pool.execute(
            "DELETE FROM schedule_executions "
            "WHERE started_at < $1 "
            "AND id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER (PARTITION BY schedule_id ORDER BY started_at DESC) AS rn "
            "    FROM schedule_executions"
            "  ) ranked WHERE rn <= $2"
            ")",
            cutoff, min_keep,
        )
        return int(result.split()[-1])

    async def update_scan_schedule_link(
        self, scan_id: str, schedule_id: str, triggered_by: str
    ) -> None:
        await self._pool.execute(
            "UPDATE scans SET schedule_id=$1, triggered_by=$2 WHERE scan_id=$3",
            schedule_id, triggered_by, scan_id,
        )

    async def count_scheduled_scans(self) -> int:
        return await self._pool.fetchval("SELECT COUNT(*) FROM scheduled_scans")

    async def mark_orphaned_executions(self) -> int:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self._pool.execute(
            "UPDATE schedule_executions SET status='failed', "
            "completed_at=$1, error_message='Server restarted during execution' "
            "WHERE status='started' AND started_at < $2",
            now, threshold,
        )
        return int(result.split()[-1])

    # ── Close Rules ──────────────────────────────────────────────

    async def insert_close_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "trigger_type", "threshold_value", "reference_value",
                "status", "expires_at", "cycle_id"]
        vals = {c: rule.get(c) for c in cols}
        if vals.get("status") is None:
            vals["status"] = "active"
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(f"${i}" for i in range(1, len(vals) + 1))
        row = await self._pool.fetchrow(
            f"INSERT INTO close_rules ({col_names}) VALUES ({placeholders}) RETURNING *",
            *vals.values(),
        )
        return self._serialize_row(row)

    async def list_close_rules(self, account_id: str) -> list:
        rows = await self._pool.fetch(
            "SELECT * FROM close_rules WHERE account_id = $1 ORDER BY created_at DESC",
            account_id,
        )
        return [self._serialize_row(r) for r in rows]

    async def get_close_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM close_rules WHERE id = $1", rule_id
        )
        if not row:
            return None
        return self._serialize_row(row)

    async def update_close_rule(self, rule_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"trigger_type", "threshold_value", "reference_value", "status", "expires_at", "triggered_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return None
        for dt_field in ("expires_at", "triggered_at"):
            if dt_field in updates and isinstance(updates[dt_field], str):
                updates[dt_field] = datetime.fromisoformat(updates[dt_field])
        updates["updated_at"] = datetime.now(timezone.utc)
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k} = ${i}")
            params.append(v)
        params.append(rule_id)
        row = await self._pool.fetchrow(
            f"UPDATE close_rules SET {', '.join(parts)} WHERE id = ${len(params)} RETURNING *",
            *params,
        )
        if not row:
            return None
        return self._serialize_row(row)

    async def atomic_trigger_rule(self, rule_id: str) -> bool:
        """Atomically set rule status to 'triggered' only if currently 'active'. Returns True if transitioned."""
        row = await self._pool.fetchrow(
            "UPDATE close_rules SET status = 'triggered', triggered_at = now(), updated_at = now() "
            "WHERE id = $1 AND status = 'active' RETURNING id",
            rule_id,
        )
        return row is not None

    async def delete_close_rule(self, rule_id: str) -> bool:
        async with self._transaction() as conn:
            await conn.execute("DELETE FROM close_executions WHERE rule_id = $1", rule_id)
            result = await conn.execute("DELETE FROM close_rules WHERE id = $1", rule_id)
        return int(result.split()[-1]) > 0

    async def list_active_rules(self) -> list:
        """Fetch all active rules for non-deleted, active accounts."""
        rows = await self._pool.fetch(
            "SELECT cr.* FROM close_rules cr "
            "JOIN trading_accounts ta ON cr.account_id = ta.id "
            "WHERE cr.status = 'active' AND ta.deleted_at IS NULL "
            "AND ta.is_active = 1 "
            "AND (cr.expires_at IS NULL OR cr.expires_at > now()) "
            "ORDER BY cr.account_id, cr.created_at",
        )
        return [self._serialize_row(r) for r in rows]

    async def recover_stuck_triggered_rules(self, max_age_seconds: int = 120) -> int:
        """Revert rules stuck in 'triggered' state for longer than max_age_seconds."""
        result = await self._pool.execute(
            "UPDATE close_rules SET status = 'active', triggered_at = NULL "
            "WHERE status = 'triggered' "
            "AND triggered_at < now() - interval '1 second' * $1",
            max_age_seconds,
        )
        return int(result.split()[-1])

    async def count_active_rules_by_account(self) -> Dict[str, int]:
        """Return {account_id: count} for all accounts with active rules."""
        rows = await self._pool.fetch(
            "SELECT account_id::text, COUNT(*) as cnt FROM close_rules "
            "WHERE status = 'active' GROUP BY account_id",
        )
        return {r["account_id"]: r["cnt"] for r in rows}

    async def get_active_targets_by_account(self) -> Dict[str, list]:
        """Return {account_id: [{trigger_type, threshold_value, reference_value}]} for active rules."""
        rows = await self._pool.fetch(
            "SELECT account_id::text, trigger_type, threshold_value, reference_value "
            "FROM close_rules WHERE status = 'active' ORDER BY account_id, created_at",
        )
        result: Dict[str, list] = {}
        for r in rows:
            result.setdefault(r["account_id"], []).append({
                "trigger_type": r["trigger_type"],
                "threshold_value": str(r["threshold_value"]) if r["threshold_value"] is not None else None,
                "reference_value": str(r["reference_value"]) if r["reference_value"] is not None else None,
            })
        return result

    async def count_rules_for_account(self, account_id: str) -> int:
        return await self._pool.fetchval(
            "SELECT COUNT(*) FROM close_rules WHERE account_id = $1 AND status IN ('active', 'paused')",
            account_id,
        )

    # ── Close Executions ─────────────────────────────────────────

    async def insert_close_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "rule_id", "trigger_source", "total_positions",
                "closed_count", "failed_count", "results"]
        vals = {c: execution.get(c) for c in cols}
        if vals.get("results") and not isinstance(vals["results"], str):
            vals["results"] = json.dumps(vals["results"])
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(f"${i}" for i in range(1, len(vals) + 1))
        row = await self._pool.fetchrow(
            f"INSERT INTO close_executions ({col_names}) VALUES ({placeholders}) RETURNING *",
            *vals.values(),
        )
        return self._serialize_row(row)

    async def list_close_executions(self, account_id: str, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        offset = (page - 1) * limit
        total = await self._pool.fetchval(
            "SELECT COUNT(*) FROM close_executions WHERE account_id = $1",
            account_id,
        )
        rows = await self._pool.fetch(
            "SELECT * FROM close_executions WHERE account_id = $1 "
            "ORDER BY executed_at DESC LIMIT $2 OFFSET $3",
            account_id, limit, offset,
        )
        return {
            "items": [self._serialize_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }
