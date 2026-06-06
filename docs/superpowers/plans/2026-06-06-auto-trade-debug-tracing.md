# Auto-Trade Debug Tracing & Forensics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add always-on, performance-safe decision tracing to the `AutoTradeExecutor` path so any past scheduled/manual auto-trade run is fully reconstructable via a `/api/v1/debug` API, without ever slowing the money-handling trade path.

**Architecture:** A new `DebugTraceRecorder` service is injected into `ScannerService` and `AutoTradeExecutor`. Instrumentation hooks call synchronous, fail-open `emit_*` methods that only append to a bounded in-memory buffer (drop-on-pressure, never blocks trading). A lifespan-managed background drainer bulk-inserts buffered events into six new `debug_*` Postgres tables (migration v37→v38) on a dedicated connection. A new `debug_router` serves a deep aggregate forensic tree plus focused sub-routes. Retention defaults to 60 days, runtime-configurable, with nightly CASCADE cleanup.

**Tech Stack:** Python 3.12 / asyncio, FastAPI, asyncpg (Postgres), Pydantic v2, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-06-auto-trade-debug-tracing-design.md`

---

## File Structure

**New files:**
- `backend/services/debug_trace_recorder.py` — the recorder service: bounded buffer, fail-open `emit_*` methods, kill-switch flag, cached config, background drainer + nightly retention task, bulk-`COPY` persistence.
- `backend/services/debug_trace_repository.py` — all SQL for `debug_*` tables: bulk insert (COPY), aggregate-tree reads, sub-route reads, retention delete, config read/update.
- `backend/routers/debug.py` — `/api/v1/debug` routes (aggregate tree + sub-routes + config).
- `backend/schemas/debug.py` — Pydantic v2 response/request models for the debug API.
- `tests/backend/services/test_debug_trace_recorder.py` — recorder unit tests (fail-open, drop-on-pressure, buffer/flush, config cache).
- `tests/backend/services/test_debug_trace_repository.py` — repository SQL tests (insert/read/retention) against a test DB.
- `tests/backend/routers/test_debug_router.py` — API tests for tree + sub-routes + config.
- `tests/backend/services/test_debug_trace_performance.py` — performance gate (emit overhead, tracing on/off timing parity, stalled-drainer non-blocking).
- `tests/backend/services/test_auto_trade_instrumentation.py` — verifies executor hooks emit the right events/decisions and that recorder failure never breaks a trade.

**Modified files:**
- `backend/async_persistence.py` — append migration `(38, _SCHEMA_DEBUG_V38)`; add `debug_*` helper methods (or delegate to repository). Insert before the closing `]` of `_MIGRATIONS` at line 989.
- `backend/services/auto_trade_service.py` — accept optional `recorder` in `AutoTradeExecutor.__init__`; add fail-open hooks in `init_balances`, `execute_batch`, `fill_immediate_remaining`, `post_scan_recheck`, and `_try_trade` (return a reason code instead of bare `None`/counter-only at each early return, then emit).
- `backend/services/scanner_service.py` — accept `debug_recorder` in `ScannerService.__init__` (line 320); pass it into both `AutoTradeExecutor(...)` constructions (lines 416, 576); open a debug run when the auto-trade phase starts and close it at finalize.
- `backend/routers/scanner.py` — in the manual `_run_auto_trade` (around line 205), pass the recorder into the executor and open/close a debug run so manual re-triggers create a new run (no overwrite).
- `backend/main.py` — instantiate `DebugTraceRecorder` in lifespan, store on `app.state.debug_trace_recorder`, inject into `ScannerService`, start drainer + nightly cleanup, register `debug_router`, shut down via `_safe_shutdown`.

**Design boundary:** the recorder owns runtime/buffering/lifecycle; the repository owns SQL; the router owns HTTP shaping. Instrumentation in the executor is thin (build a dict, call one `emit_*`), keeping the hot path trivial and the trade logic readable.

---

## Phase 1 — Schema (migration v38) & Repository

### Task 1: Add the v38 migration with six debug tables

**Files:**
- Modify: `backend/async_persistence.py` (insert a module-level constant before the `_MIGRATIONS` list, then add the `(38, ...)` tuple before the closing `]` at line 989)

- [ ] **Step 1: Add the migration SQL constant**

Insert this constant just above `_MIGRATIONS: list[tuple[int, _MigrationSQL]] = [` (around line 571). Statements are semicolon-separated (the runner splits on `;`):

```python
_SCHEMA_DEBUG_V38 = """
CREATE TABLE IF NOT EXISTS debug_runs (
    id BIGSERIAL PRIMARY KEY,
    scan_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (trigger_source IN ('scheduled','manual','run_now','unknown')),
    schedule_id TEXT,
    schedule_execution_id BIGINT,
    scan_started_at TIMESTAMPTZ,
    scan_completed_at TIMESTAMPTZ,
    exec_started_at TIMESTAMPTZ,
    exec_completed_at TIMESTAMPTZ,
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    total_symbols INT NOT NULL DEFAULT 0,
    completed_symbols INT NOT NULL DEFAULT 0,
    failed_symbols INT NOT NULL DEFAULT 0,
    num_accounts INT NOT NULL DEFAULT 0,
    phase_reached TEXT,
    dropped_event_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_runs_scan ON debug_runs(scan_id);
CREATE INDEX IF NOT EXISTS idx_debug_runs_created ON debug_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_debug_runs_schedule ON debug_runs(schedule_id, created_at DESC);
CREATE TABLE IF NOT EXISTS debug_account_traces (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    account_label TEXT,
    execution_mode TEXT,
    final_stopped_reason TEXT,
    gate_that_stopped TEXT,
    rescued_by_recheck BOOLEAN NOT NULL DEFAULT FALSE,
    base_capital NUMERIC(20,8),
    equity_at_start NUMERIC(20,8),
    positions_at_start_count INT,
    trades_executed INT NOT NULL DEFAULT 0,
    trades_failed INT NOT NULL DEFAULT 0,
    trades_skipped INT NOT NULL DEFAULT 0,
    rules_created JSONB NOT NULL DEFAULT '[]',
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_acct_run ON debug_account_traces(run_id);
CREATE INDEX IF NOT EXISTS idx_debug_acct_account ON debug_account_traces(account_id, created_at DESC);
CREATE TABLE IF NOT EXISTS debug_lifecycle_events (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    seq INT NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT 'unknown',
    event_type TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_life_run_acct ON debug_lifecycle_events(run_id, account_id, seq);
CREATE TABLE IF NOT EXISTS debug_symbol_decisions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'unknown',
    symbol TEXT NOT NULL,
    scan_score INT,
    scan_confidence TEXT,
    scan_direction TEXT,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason_detail JSONB NOT NULL DEFAULT '{}',
    order_id TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_sym_run_acct ON debug_symbol_decisions(run_id, account_id);
CREATE INDEX IF NOT EXISTS idx_debug_sym_symbol ON debug_symbol_decisions(symbol, ts DESC);
CREATE TABLE IF NOT EXISTS debug_exchange_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    gate TEXT NOT NULL,
    positions JSONB NOT NULL DEFAULT '[]',
    position_count INT NOT NULL DEFAULT 0,
    wallet JSONB NOT NULL DEFAULT '{}',
    equity NUMERIC(20,8),
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_snap_run_acct ON debug_exchange_snapshots(run_id, account_id, gate);
CREATE TABLE IF NOT EXISTS debug_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tracing_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    retention_days INT NOT NULL DEFAULT 60 CHECK (retention_days BETWEEN 1 AND 3650),
    symbol_decision_cap INT NOT NULL DEFAULT 200 CHECK (symbol_decision_cap BETWEEN 0 AND 100000),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO debug_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING
"""
```

- [ ] **Step 2: Append the migration tuple**

Change the tail of `_MIGRATIONS` (line ~988-989) from:

```python
    ))
"""),
]
```

to:

```python
    ))
"""),
    (38, _SCHEMA_DEBUG_V38),
]
```

- [ ] **Step 3: Apply migrations against the dev DB and verify v38**

Run (PowerShell, repo root, with `DATABASE_URL` set to your dev DB):
```bash
python -c "import asyncio; from backend.async_persistence import AsyncAnalysisDB, _default_dsn; \
db=AsyncAnalysisDB(_default_dsn()); asyncio.run(db.connect())"
```
Then verify:
```bash
python -c "import asyncio,asyncpg,os; \
async def m(): \
 c=await asyncpg.connect(os.environ['DATABASE_URL']); \
 v=await c.fetchval('select version from schema_version'); \
 t=await c.fetch(\"select table_name from information_schema.tables where table_name like 'debug_%' order by 1\"); \
 print('version',v,'tables',[r['table_name'] for r in t]); await c.close()
asyncio.run(m())"
```
Expected: `version 38 tables ['debug_account_traces','debug_config','debug_exchange_snapshots','debug_lifecycle_events','debug_runs','debug_symbol_decisions']`

- [ ] **Step 4: Commit**

```bash
git add backend/async_persistence.py
git commit -m "feat(debug): add v38 migration for auto-trade debug tracing tables"
```

### Task 2: DebugTraceRepository — config read/update + run create/finalize

**Files:**
- Create: `backend/services/debug_trace_repository.py`
- Test: `tests/backend/test_debug_trace_repository.py`

This task covers the run lifecycle + config SQL. Bulk event insert (COPY) is Task 3. The repository takes an `asyncpg.Pool` and is pure SQL (no buffering/threading).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_debug_trace_repository.py`:

```python
"""Tests for DebugTraceRepository."""

import os
import asyncpg
import pytest
import pytest_asyncio

from backend.services.debug_trace_repository import DebugTraceRepository

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


@pytest_asyncio.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(dsn=_TEST_DSN, min_size=1, max_size=3)
    except Exception:
        pytest.skip("PostgreSQL not available")
        return
    from backend.async_persistence import _MIGRATIONS
    async with p.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = await conn.fetchrow("SELECT version FROM schema_version")
        current = row["version"] if row else 0
        if not row:
            await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for ver, sql in _MIGRATIONS:
            if ver > current:
                if callable(sql):
                    await sql(conn)
                else:
                    for stmt in sql.split(";"):
                        if stmt.strip():
                            await conn.execute(stmt)
                await conn.execute("UPDATE schema_version SET version = $1", ver)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM debug_runs")
    await p.close()


@pytest.mark.asyncio
async def test_get_config_returns_defaults(pool):
    repo = DebugTraceRepository(pool)
    cfg = await repo.get_config()
    assert cfg["tracing_enabled"] is True
    assert cfg["retention_days"] == 60
    assert cfg["symbol_decision_cap"] == 200


@pytest.mark.asyncio
async def test_update_config_persists(pool):
    repo = DebugTraceRepository(pool)
    await repo.update_config(tracing_enabled=False, retention_days=30, symbol_decision_cap=50)
    cfg = await repo.get_config()
    assert cfg["tracing_enabled"] is False
    assert cfg["retention_days"] == 30
    assert cfg["symbol_decision_cap"] == 50


@pytest.mark.asyncio
async def test_create_and_finalize_run(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(
        scan_id="scan-abc", trigger_source="scheduled",
        schedule_id="sch-1", schedule_execution_id=42,
        config_snapshot={"k": "v"},
    )
    assert isinstance(run_id, int)
    await repo.finalize_run(
        run_id, phase_reached="finalized",
        total_symbols=580, completed_symbols=580, failed_symbols=0,
        num_accounts=21, dropped_event_count=0,
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM debug_runs WHERE id=$1", run_id)
    assert row["trigger_source"] == "scheduled"
    assert row["num_accounts"] == 21
    assert row["phase_reached"] == "finalized"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.debug_trace_repository'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/services/debug_trace_repository.py`:

```python
"""SQL repository for auto-trade debug tracing tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg


class DebugTraceRepository:
    """All SQL for debug_* tables. Pure data access — no buffering or threading."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── config ────────────────────────────────────────────────
    async def get_config(self) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tracing_enabled, retention_days, symbol_decision_cap FROM debug_config WHERE id=1"
            )
        if row is None:
            return {"tracing_enabled": True, "retention_days": 60, "symbol_decision_cap": 200}
        return dict(row)

    async def update_config(
        self, *, tracing_enabled: Optional[bool] = None,
        retention_days: Optional[int] = None, symbol_decision_cap: Optional[int] = None,
    ) -> dict[str, Any]:
        sets, args, i = [], [], 1
        if tracing_enabled is not None:
            sets.append(f"tracing_enabled=${i}"); args.append(tracing_enabled); i += 1
        if retention_days is not None:
            sets.append(f"retention_days=${i}"); args.append(retention_days); i += 1
        if symbol_decision_cap is not None:
            sets.append(f"symbol_decision_cap=${i}"); args.append(symbol_decision_cap); i += 1
        if sets:
            sets.append("updated_at=now()")
            async with self._pool.acquire() as conn:
                await conn.execute(f"UPDATE debug_config SET {', '.join(sets)} WHERE id=1", *args)
        return await self.get_config()

    # ── run lifecycle ─────────────────────────────────────────
    async def create_run(
        self, *, scan_id: str, trigger_source: str = "unknown",
        schedule_id: Optional[str] = None, schedule_execution_id: Optional[int] = None,
        scan_started_at: Optional[datetime] = None, scan_completed_at: Optional[datetime] = None,
        config_snapshot: Optional[dict] = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO debug_runs
                  (scan_id, trigger_source, schedule_id, schedule_execution_id,
                   scan_started_at, scan_completed_at, exec_started_at, config_snapshot)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
                """,
                scan_id, trigger_source, schedule_id, schedule_execution_id,
                scan_started_at, scan_completed_at, datetime.now(timezone.utc),
                json.dumps(config_snapshot or {}),
            )

    async def finalize_run(
        self, run_id: int, *, phase_reached: str,
        total_symbols: int = 0, completed_symbols: int = 0, failed_symbols: int = 0,
        num_accounts: int = 0, dropped_event_count: int = 0,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE debug_runs SET
                  exec_completed_at=now(), phase_reached=$2,
                  total_symbols=$3, completed_symbols=$4, failed_symbols=$5,
                  num_accounts=$6, dropped_event_count=$7
                WHERE id=$1
                """,
                run_id, phase_reached, total_symbols, completed_symbols,
                failed_symbols, num_accounts, dropped_event_count,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -v`
Expected: PASS (3 tests). If PostgreSQL test DB is unavailable, tests skip — that is acceptable but prefer a real `tradingagents_test` DB.

- [ ] **Step 5: Commit**

```bash
git add backend/services/debug_trace_repository.py tests/backend/test_debug_trace_repository.py
git commit -m "feat(debug): add DebugTraceRepository config + run lifecycle SQL"
```

### Task 3: Repository bulk event insert (COPY) + retention delete

**Files:**
- Modify: `backend/services/debug_trace_repository.py`
- Test: `tests/backend/test_debug_trace_repository.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backend/test_debug_trace_repository.py`:

```python
@pytest.mark.asyncio
async def test_bulk_insert_events_and_read_back(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-bulk", trigger_source="manual")
    await repo.bulk_insert(
        account_traces=[{
            "run_id": run_id, "account_id": "acc-1", "account_label": "Dad - Demo",
            "execution_mode": "batch", "final_stopped_reason": None,
            "gate_that_stopped": None, "rescued_by_recheck": True,
            "base_capital": 500.0, "equity_at_start": 510.0, "positions_at_start_count": 3,
            "trades_executed": 3, "trades_failed": 0, "trades_skipped": 54,
            "rules_created": [{"rule_id": "r1", "trigger_type": "EQUITY_RISE_PCT"}],
            "config_snapshot": {"max_trades": 3},
        }],
        lifecycle_events=[{
            "run_id": run_id, "account_id": "acc-1", "seq": 0,
            "phase": "post_scan_recheck", "event_type": "state_reset", "detail": {},
        }],
        symbol_decisions=[{
            "run_id": run_id, "account_id": "acc-1", "phase": "post_scan_recheck",
            "symbol": "B3USDT", "scan_score": -7, "scan_confidence": "high",
            "scan_direction": "sell", "decision": "placed", "reason_code": "placed_ok",
            "reason_detail": {}, "order_id": "o1",
        }],
        exchange_snapshots=[{
            "run_id": run_id, "account_id": "acc-1", "gate": "scan_start",
            "positions": [{"symbol": "AAPLUSDT", "size": "1"}], "position_count": 1,
            "wallet": {"totalEquity": "510"}, "equity": 510.0,
        }],
    )
    async with pool.acquire() as conn:
        a = await conn.fetchval("SELECT count(*) FROM debug_account_traces WHERE run_id=$1", run_id)
        l = await conn.fetchval("SELECT count(*) FROM debug_lifecycle_events WHERE run_id=$1", run_id)
        s = await conn.fetchval("SELECT count(*) FROM debug_symbol_decisions WHERE run_id=$1", run_id)
        x = await conn.fetchval("SELECT count(*) FROM debug_exchange_snapshots WHERE run_id=$1", run_id)
        # JSONB content must round-trip correctly through COPY (codec regression guard).
        rules_json = await conn.fetchval(
            "SELECT rules_created FROM debug_account_traces WHERE run_id=$1", run_id
        )
        snap_json = await conn.fetchval(
            "SELECT positions FROM debug_exchange_snapshots WHERE run_id=$1", run_id
        )
    assert (a, l, s, x) == (1, 1, 1, 1)
    import json as _json
    # asyncpg returns jsonb as str (built-in binary codec); it must parse back to our data.
    rules = _json.loads(rules_json) if isinstance(rules_json, str) else rules_json
    snap = _json.loads(snap_json) if isinstance(snap_json, str) else snap_json
    assert rules[0]["trigger_type"] == "EQUITY_RISE_PCT"
    assert snap[0]["symbol"] == "AAPLUSDT"


@pytest.mark.asyncio
async def test_delete_runs_older_than(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-old", trigger_source="scheduled")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE debug_runs SET created_at = now() - interval '100 days' WHERE id=$1", run_id
        )
    deleted = await repo.delete_runs_older_than(60)
    assert deleted >= 1
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM debug_runs WHERE id=$1", run_id) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -k "bulk_insert or delete_runs" -v`
Expected: FAIL with `AttributeError: 'DebugTraceRepository' object has no attribute 'bulk_insert'`

- [ ] **Step 3: Implement bulk insert + retention**

> **JSONB-over-COPY contract (verified).** `copy_records_to_table` uses asyncpg's binary protocol. asyncpg's built-in `jsonb` codec is **binary** and accepts a Python `str`, so passing `json.dumps(...)` strings for JSONB columns is correct and matches how the rest of `async_persistence.py` writes JSONB (lines 2005/2045/2077/2425). **Do NOT** register a global text json/jsonb codec via `set_type_codec(..., format='text')` / pool `init=` — a *text* codec is explicitly unsupported by COPY and would break this method. `copy_records_to_table` also does not support per-column `::jsonb` casts (none are needed). The repository round-trip test in Step 1 (`test_bulk_insert_events_and_read_back`) is the regression guard; if anyone later adds a text json codec, that test fails loudly.

Append these methods to `DebugTraceRepository` in `backend/services/debug_trace_repository.py`:

```python
    # ── bulk event insert ─────────────────────────────────────
    async def bulk_insert(
        self, *,
        account_traces: Optional[list[dict]] = None,
        lifecycle_events: Optional[list[dict]] = None,
        symbol_decisions: Optional[list[dict]] = None,
        exchange_snapshots: Optional[list[dict]] = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if account_traces:
                await conn.copy_records_to_table(
                    "debug_account_traces",
                    columns=[
                        "run_id", "account_id", "account_label", "execution_mode",
                        "final_stopped_reason", "gate_that_stopped", "rescued_by_recheck",
                        "base_capital", "equity_at_start", "positions_at_start_count",
                        "trades_executed", "trades_failed", "trades_skipped",
                        "rules_created", "config_snapshot",
                    ],
                    records=[(
                        r["run_id"], r["account_id"], r.get("account_label"),
                        r.get("execution_mode"), r.get("final_stopped_reason"),
                        r.get("gate_that_stopped"), bool(r.get("rescued_by_recheck", False)),
                        r.get("base_capital"), r.get("equity_at_start"),
                        r.get("positions_at_start_count"),
                        int(r.get("trades_executed", 0)), int(r.get("trades_failed", 0)),
                        int(r.get("trades_skipped", 0)),
                        json.dumps(r.get("rules_created", [])),
                        json.dumps(r.get("config_snapshot", {})),
                    ) for r in account_traces],
                )
            if lifecycle_events:
                await conn.copy_records_to_table(
                    "debug_lifecycle_events",
                    columns=["run_id", "account_id", "seq", "phase", "event_type", "detail", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], int(r.get("seq", 0)),
                        r.get("phase", "unknown"), r["event_type"],
                        json.dumps(r.get("detail", {})),
                        r.get("ts") or datetime.now(timezone.utc),
                    ) for r in lifecycle_events],
                )
            if symbol_decisions:
                await conn.copy_records_to_table(
                    "debug_symbol_decisions",
                    columns=[
                        "run_id", "account_id", "phase", "symbol", "scan_score",
                        "scan_confidence", "scan_direction", "decision", "reason_code",
                        "reason_detail", "order_id", "ts",
                    ],
                    records=[(
                        r["run_id"], r["account_id"], r.get("phase", "unknown"), r["symbol"],
                        r.get("scan_score"), r.get("scan_confidence"), r.get("scan_direction"),
                        r["decision"], r["reason_code"], json.dumps(r.get("reason_detail", {})),
                        r.get("order_id"), r.get("ts") or datetime.now(timezone.utc),
                    ) for r in symbol_decisions],
                )
            if exchange_snapshots:
                await conn.copy_records_to_table(
                    "debug_exchange_snapshots",
                    columns=["run_id", "account_id", "gate", "positions", "position_count", "wallet", "equity", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], r["gate"],
                        json.dumps(r.get("positions", [])), int(r.get("position_count", 0)),
                        json.dumps(r.get("wallet", {})), r.get("equity"),
                        r.get("ts") or datetime.now(timezone.utc),
                    ) for r in exchange_snapshots],
                )

    # ── retention ─────────────────────────────────────────────
    async def delete_runs_older_than(self, retention_days: int) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM debug_runs WHERE created_at < now() - ($1 || ' days')::interval",
                str(int(retention_days)),
            )
        # result like "DELETE 5"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/debug_trace_repository.py tests/backend/test_debug_trace_repository.py
git commit -m "feat(debug): add bulk COPY insert + retention delete to repository"
```

---

## Phase 2 — DebugTraceRecorder (performance-critical service)

The recorder is the in-memory front end the executor calls. Design invariants (from spec Section 4):
- `emit_*` methods are **synchronous**, do **no I/O**, **never raise** (fail-open), and **never block** (drop on full buffer).
- A `RunContext` object accumulates per-run state; the recorder holds the active run's events in a bounded `deque`.
- A background async drainer flushes to the repository via bulk COPY.
- A single `_enabled` boolean (mirrors `debug_config.tracing_enabled`) short-circuits every emit when off.

### Task 4: RunContext + recorder skeleton with fail-open emit + drop-on-pressure

**Files:**
- Create: `backend/services/debug_trace_recorder.py`
- Test: `tests/backend/test_debug_trace_recorder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_debug_trace_recorder.py`:

```python
"""Unit tests for DebugTraceRecorder (no DB required — repository is mocked)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.debug_trace_recorder import DebugTraceRecorder


def _recorder(enabled=True, buffer_max=1000):
    repo = MagicMock()
    repo.create_run = AsyncMock(return_value=1)
    repo.finalize_run = AsyncMock()
    repo.bulk_insert = AsyncMock()
    repo.get_config = AsyncMock(return_value={
        "tracing_enabled": enabled, "retention_days": 60, "symbol_decision_cap": 200,
    })
    repo.delete_runs_older_than = AsyncMock(return_value=0)
    rec = DebugTraceRecorder(repo, buffer_max=buffer_max)
    rec._enabled = enabled
    rec._symbol_decision_cap = 200
    return rec, repo


def test_emit_when_disabled_is_noop():
    rec, repo = _recorder(enabled=False)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    rec.emit_lifecycle(ctx, account_id="a1", phase="init_balances", event_type="marked_stopped")
    assert rec.buffered_count() == 0


def test_emit_lifecycle_buffers_event():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="init_balances", event_type="marked_stopped",
                       detail={"reason": "positions_already_open"})
    assert rec.buffered_count() == 1


def test_emit_never_raises_on_bad_input():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    # Passing odd types must not raise — fail-open contract.
    rec.emit_symbol_decision(ctx, account_id=None, phase=None, symbol=None,
                             decision=None, reason_code=None, reason_detail=object())
    # No assertion on buffer; the contract is "does not raise".


def test_drop_on_pressure_increments_dropped():
    rec, repo = _recorder(buffer_max=2)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    for i in range(5):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type=f"e{i}")
    assert rec.buffered_count() == 2
    assert ctx.dropped_event_count == 3


def test_symbol_decision_cap_truncates():
    rec, repo = _recorder()
    rec._symbol_decision_cap = 3
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    for i in range(10):
        rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol=f"S{i}USDT",
                                 decision="skipped", reason_code="min_score", reason_detail={})
    # 3 real + 1 truncation marker
    syms = [e for e in rec.snapshot_buffer() if e["_table"] == "symbol_decisions"]
    assert len(syms) == 4
    assert any(s["reason_code"] == "truncated" for s in syms)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_debug_trace_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.debug_trace_recorder'`

- [ ] **Step 3: Implement RunContext + recorder skeleton**

Create `backend/services/debug_trace_recorder.py`:

```python
"""In-memory, fail-open recorder for auto-trade debug tracing.

Performance contract (money path safety):
- emit_* methods are synchronous, do no I/O, never raise, never block.
- On a full buffer, events are dropped and counted (never backpressure trading).
- A single boolean short-circuits all emits when tracing is disabled.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER_MAX = 50_000


@dataclass
class RunContext:
    """Per-run accumulator. Cheap to create; holds no locks."""
    scan_id: str
    trigger_source: str = "unknown"
    schedule_id: Optional[str] = None
    schedule_execution_id: Optional[int] = None
    run_id: Optional[int] = None
    dropped_event_count: int = 0
    phase_reached: str = "created"
    _seq: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _symbol_counts: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    _truncated_marked: set = field(default_factory=set)

    def next_seq(self, account_id: str) -> int:
        n = self._seq[account_id]
        self._seq[account_id] = n + 1
        return n


class DebugTraceRecorder:
    def __init__(self, repository: Any, *, buffer_max: int = _DEFAULT_BUFFER_MAX) -> None:
        self._repo = repository
        self._buffer: deque = deque(maxlen=buffer_max)
        self._buffer_max = buffer_max
        self._enabled = True
        self._symbol_decision_cap = 200
        self._retention_days = 60
        self._drainer_task = None
        self._cleanup_task = None
        self._running = False

    # ── introspection (used by tests) ─────────────────────────
    def buffered_count(self) -> int:
        return len(self._buffer)

    def snapshot_buffer(self) -> list[dict]:
        return list(self._buffer)

    # ── run context ───────────────────────────────────────────
    def new_run_context(self, *, scan_id: str, trigger_source: str = "unknown",
                        schedule_id: Optional[str] = None,
                        schedule_execution_id: Optional[int] = None) -> RunContext:
        return RunContext(
            scan_id=scan_id, trigger_source=trigger_source,
            schedule_id=schedule_id, schedule_execution_id=schedule_execution_id,
        )

    # ── internal: append with drop-on-pressure ────────────────
    def _append(self, ctx: RunContext, record: dict) -> None:
        if len(self._buffer) >= self._buffer_max:
            ctx.dropped_event_count += 1
            return
        self._buffer.append(record)

    # ── emit methods (sync, fail-open) ────────────────────────
    def emit_lifecycle(self, ctx: RunContext, *, account_id: str, phase: str,
                       event_type: str, detail: Optional[dict] = None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            self._append(ctx, {
                "_table": "lifecycle_events",
                "run_id": ctx.run_id, "account_id": account_id,
                "seq": ctx.next_seq(account_id), "phase": phase,
                "event_type": event_type, "detail": detail or {},
                "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_lifecycle_failed", exc_info=True)

    def emit_symbol_decision(self, ctx: RunContext, *, account_id: str, phase: str,
                             symbol: str, decision: str, reason_code: str,
                             reason_detail: Optional[dict] = None,
                             scan_score=None, scan_confidence=None,
                             scan_direction=None, order_id=None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            key = (account_id, phase)
            count = ctx._symbol_counts[key]
            if count >= self._symbol_decision_cap:
                if key not in ctx._truncated_marked:
                    ctx._truncated_marked.add(key)
                    self._append(ctx, {
                        "_table": "symbol_decisions", "run_id": ctx.run_id,
                        "account_id": account_id, "phase": phase, "symbol": "*",
                        "decision": "skipped", "reason_code": "truncated",
                        "reason_detail": {"cap": self._symbol_decision_cap},
                        "scan_score": None, "scan_confidence": None,
                        "scan_direction": None, "order_id": None,
                        "ts": datetime.now(timezone.utc),
                    })
                return
            ctx._symbol_counts[key] = count + 1
            self._append(ctx, {
                "_table": "symbol_decisions", "run_id": ctx.run_id,
                "account_id": account_id, "phase": phase, "symbol": symbol,
                "decision": decision, "reason_code": reason_code,
                "reason_detail": reason_detail or {},
                "scan_score": scan_score, "scan_confidence": scan_confidence,
                "scan_direction": scan_direction, "order_id": order_id,
                "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_symbol_decision_failed", exc_info=True)

    def emit_exchange_snapshot(self, ctx: RunContext, *, account_id: str, gate: str,
                               positions: Optional[list] = None,
                               wallet: Optional[dict] = None, equity=None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            # Shallow-copy the executor's live structures: the caller may mutate the
            # same positions/wallet objects later in init_balances, which would
            # otherwise retroactively change this captured snapshot. Copies are cheap
            # (a few dozen small dicts) and keep the snapshot a true point-in-time view.
            pos = list(positions) if positions else []
            wal = dict(wallet) if wallet else {}
            self._append(ctx, {
                "_table": "exchange_snapshots", "run_id": ctx.run_id,
                "account_id": account_id, "gate": gate, "positions": pos,
                "position_count": len(pos), "wallet": wal,
                "equity": equity, "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_exchange_snapshot_failed", exc_info=True)

    def emit_account_trace(self, ctx: RunContext, *, account_id: str, **fields: Any) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            rec = {"_table": "account_traces", "run_id": ctx.run_id, "account_id": account_id}
            rec.update(fields)
            self._append(ctx, rec)
        except Exception:
            logger.debug("emit_account_trace_failed", exc_info=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_debug_trace_recorder.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/debug_trace_recorder.py tests/backend/test_debug_trace_recorder.py
git commit -m "feat(debug): add DebugTraceRecorder skeleton with fail-open emit + drop-on-pressure"
```

### Task 5: Recorder run open/close + background drainer + retention loop

**Files:**
- Modify: `backend/services/debug_trace_recorder.py`
- Test: `tests/backend/test_debug_trace_recorder.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backend/test_debug_trace_recorder.py`:

```python
@pytest.mark.asyncio
async def test_open_run_sets_run_id_and_persists():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    await rec.open_run(ctx, config_snapshot={"x": 1})
    assert ctx.run_id == 1
    repo.create_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_drain_flushes_buffer_to_repo():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    rec.emit_exchange_snapshot(ctx, account_id="a1", gate="scan_start", positions=[])
    await rec.drain_once()
    repo.bulk_insert.assert_awaited()
    assert rec.buffered_count() == 0


@pytest.mark.asyncio
async def test_close_run_finalizes_with_dropped_count():
    rec, repo = _recorder(buffer_max=1)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="a")
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="b")  # dropped
    await rec.close_run(ctx, phase_reached="finalized", total_symbols=10,
                        completed_symbols=10, failed_symbols=0, num_accounts=1)
    repo.finalize_run.assert_awaited_once()
    _, kwargs = repo.finalize_run.await_args
    assert kwargs["dropped_event_count"] == 1


@pytest.mark.asyncio
async def test_refresh_config_updates_enabled_flag():
    rec, repo = _recorder()
    repo.get_config = AsyncMock(return_value={
        "tracing_enabled": False, "retention_days": 30, "symbol_decision_cap": 99,
    })
    await rec.refresh_config()
    assert rec._enabled is False
    assert rec._retention_days == 30
    assert rec._symbol_decision_cap == 99
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_debug_trace_recorder.py -k "open_run or drain or close_run or refresh_config" -v`
Expected: FAIL with `AttributeError` (methods not defined).

- [ ] **Step 3: Implement run lifecycle + drainer**

Append to `DebugTraceRecorder` in `backend/services/debug_trace_recorder.py`:

```python
    # ── run open/close (async — called off the hot path) ──────
    async def open_run(self, ctx: RunContext, *, config_snapshot: Optional[dict] = None,
                       scan_started_at=None, scan_completed_at=None) -> None:
        try:
            ctx.run_id = await self._repo.create_run(
                scan_id=ctx.scan_id, trigger_source=ctx.trigger_source,
                schedule_id=ctx.schedule_id, schedule_execution_id=ctx.schedule_execution_id,
                scan_started_at=scan_started_at, scan_completed_at=scan_completed_at,
                config_snapshot=config_snapshot or {},
            )
        except Exception:
            logger.warning("debug_open_run_failed", exc_info=True)
            ctx.run_id = None  # disables emits for this run; trading unaffected

    async def close_run(self, ctx: RunContext, *, phase_reached: str,
                        total_symbols: int = 0, completed_symbols: int = 0,
                        failed_symbols: int = 0, num_accounts: int = 0) -> None:
        try:
            await self.drain_once()
            if ctx.run_id is not None:
                await self._repo.finalize_run(
                    ctx.run_id, phase_reached=phase_reached,
                    total_symbols=total_symbols, completed_symbols=completed_symbols,
                    failed_symbols=failed_symbols, num_accounts=num_accounts,
                    dropped_event_count=ctx.dropped_event_count,
                )
        except Exception:
            logger.warning("debug_close_run_failed", exc_info=True)

    # ── drainer ───────────────────────────────────────────────
    async def drain_once(self) -> None:
        if not self._buffer:
            return
        # Snapshot and clear quickly (single-threaded event loop — safe).
        batch = list(self._buffer)
        self._buffer.clear()
        grouped: dict[str, list[dict]] = {
            "account_traces": [], "lifecycle_events": [],
            "symbol_decisions": [], "exchange_snapshots": [],
        }
        for rec in batch:
            grouped.get(rec["_table"], []).append(rec)
        try:
            await self._repo.bulk_insert(
                account_traces=grouped["account_traces"] or None,
                lifecycle_events=grouped["lifecycle_events"] or None,
                symbol_decisions=grouped["symbol_decisions"] or None,
                exchange_snapshots=grouped["exchange_snapshots"] or None,
            )
        except Exception:
            logger.warning("debug_drain_failed", exc_info=True)  # data lost; trading unaffected

    async def refresh_config(self) -> None:
        try:
            cfg = await self._repo.get_config()
            self._enabled = bool(cfg.get("tracing_enabled", True))
            self._retention_days = int(cfg.get("retention_days", 60))
            self._symbol_decision_cap = int(cfg.get("symbol_decision_cap", 200))
        except Exception:
            logger.warning("debug_refresh_config_failed", exc_info=True)

    # ── lifecycle (lifespan-managed) ──────────────────────────
    async def start(self, *, drain_interval_s: float = 3.0, cleanup_interval_s: float = 86400.0) -> None:
        import asyncio
        await self.refresh_config()
        self._running = True
        self._drainer_task = asyncio.create_task(self._drain_loop(drain_interval_s))
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(cleanup_interval_s))

    async def shutdown(self) -> None:
        import asyncio
        self._running = False
        for t in (self._drainer_task, self._cleanup_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        await self.drain_once()  # final flush

    async def _drain_loop(self, interval_s: float) -> None:
        import asyncio
        while self._running:
            try:
                await asyncio.sleep(interval_s)
                await self.refresh_config()
                await self.drain_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("debug_drain_loop_error", exc_info=True)

    async def _cleanup_loop(self, interval_s: float) -> None:
        import asyncio
        while self._running:
            try:
                await asyncio.sleep(interval_s)
                deleted = await self._repo.delete_runs_older_than(self._retention_days)
                if deleted:
                    logger.info("debug_retention_deleted", extra={"count": deleted})
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("debug_cleanup_loop_error", exc_info=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_debug_trace_recorder.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/debug_trace_recorder.py tests/backend/test_debug_trace_recorder.py
git commit -m "feat(debug): add recorder run lifecycle, drainer, retention loop"
```

---

## Phase 3 — Instrumentation of the executor & scanner

**Performance note for the implementer:** every hook is a single synchronous `emit_*` call (no `await`, no I/O). Pass the recorder + active `RunContext` into the executor once; the executor stores them and calls hooks inline. If recorder or ctx is `None`, hooks are skipped — so all existing tests (which construct the executor without a recorder) keep working unchanged.

### Task 6: Thread recorder + RunContext into AutoTradeExecutor

**Files:**
- Modify: `backend/services/auto_trade_service.py` (`AutoTradeExecutor.__init__`, line ~37)
- Test: `tests/backend/test_auto_trade_service_unit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/test_auto_trade_service_unit.py`:

```python
@pytest.mark.asyncio
async def test_executor_accepts_recorder_and_context_optional():
    from backend.services.auto_trade_service import AutoTradeExecutor
    mock_accounts = AsyncMock()
    # Backwards compatible: no recorder passed → attributes default to None.
    ex = AutoTradeExecutor(mock_accounts, None)
    assert ex._recorder is None
    assert ex._debug_ctx is None
    # With recorder + ctx provided.
    rec = MagicMock()
    ctx = object()
    ex2 = AutoTradeExecutor(mock_accounts, None, recorder=rec, debug_ctx=ctx)
    assert ex2._recorder is rec
    assert ex2._debug_ctx is ctx
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py::test_executor_accepts_recorder_and_context_optional -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'recorder'`

- [ ] **Step 3: Modify the constructor**

In `backend/services/auto_trade_service.py`, change `AutoTradeExecutor.__init__` (currently line 37):

```python
    def __init__(self, accounts_service: Any, close_positions_service: Any = None, ai_manager_service: Any = None, sector_service: Any = None):
        self._accounts = accounts_service
        self._close_svc = close_positions_service
        self._ai_manager_service = ai_manager_service
        self._sector_service = sector_service
        self._state: Dict[str, _AccountState] = {}
        self._lock = asyncio.Lock()
        self._ai_manager_enabled_accounts: set = set()
```

to:

```python
    def __init__(self, accounts_service: Any, close_positions_service: Any = None, ai_manager_service: Any = None, sector_service: Any = None, *, recorder: Any = None, debug_ctx: Any = None):
        self._accounts = accounts_service
        self._close_svc = close_positions_service
        self._ai_manager_service = ai_manager_service
        self._sector_service = sector_service
        self._state: Dict[str, _AccountState] = {}
        self._lock = asyncio.Lock()
        self._ai_manager_enabled_accounts: set = set()
        self._recorder = recorder
        self._debug_ctx = debug_ctx

    def _emit_life(self, account_id: str, phase: str, event_type: str, **detail: Any) -> None:
        """Fail-open lifecycle emit helper. Never raises, never blocks."""
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_lifecycle(ctx, account_id=account_id, phase=phase, event_type=event_type, detail=detail or {})

    def _emit_snapshot(self, account_id: str, gate: str, positions, wallet=None, equity=None) -> None:
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_exchange_snapshot(ctx, account_id=account_id, gate=gate, positions=positions, wallet=wallet, equity=equity)

    def _emit_decision(self, account_id: str, phase: str, symbol: str, decision: str, reason_code: str, result: Dict[str, Any], **detail: Any) -> None:
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_symbol_decision(
            ctx, account_id=account_id, phase=phase, symbol=symbol,
            decision=decision, reason_code=reason_code, reason_detail=detail or {},
            scan_score=result.get("score"), scan_confidence=result.get("confidence"),
            scan_direction=result.get("direction"),
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -v`
Expected: PASS (all existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/services/auto_trade_service.py tests/backend/test_auto_trade_service_unit.py
git commit -m "feat(debug): thread optional recorder + ctx into AutoTradeExecutor"
```

### Task 7: Instrument `_try_trade` decision points

**Files:**
- Modify: `backend/services/auto_trade_service.py` (`_try_trade`, lines ~913-940 for early returns; success path ~1069; phase passed in)
- Test: `tests/backend/test_auto_trade_service_unit.py`

`_try_trade` gains an optional `phase` kwarg (default `"batch"`) and emits a decision at each exit. Add emits at these existing return points (keep all existing logic identical — only ADD emit calls):

| Existing code (in `_try_trade`) | Add emit before the return |
|---|---|
| blacklist hit (`return None` ~927) | `self._emit_decision(account_id, phase, symbol, "skipped", "blacklist", result)` |
| whitelist miss (~931) | `..."skipped", "whitelist", result` |
| `symbol in state.existing_symbols` (~935) | `..."skipped", "already_held", result` |
| max_signal_age exceeded (~944) | `..."skipped", "max_signal_age", result, age=age_minutes, max=max_age` |
| `direction == "hold"` (~950) | `..."skipped", "hold_signal", result` |
| max_same_direction (~959) | `..."skipped", "max_same_direction", result` |
| max_same_sector (~970) | `..."skipped", "max_same_sector", result, sector=sector` |
| adaptive blacklist (~978) | `..."skipped", "adaptive_blacklist", result` |
| signal_sides filter (~987) | `..."skipped", "signal_sides", result` |
| min_score (~993) | `..."skipped", "min_score", result, score=score, min_score=min_score` |
| confidence_filter (~1000) | `..."skipped", "confidence_filter", result` |
| max_trades reached (~1006) | `..."skipped", "max_trades", result` |
| target_goal trade_count (~1015) | `..."skipped", "target_goal_reached", result` |
| no base_capital (~1022) | `..."skipped", "no_balance", result` |
| price drift skip (~1036, ~1039) | `..."skipped", "price_drift", result, drift=drift_pct` |
| success (after `state.trades_executed += 1`, ~1069) | `..."placed", "placed_ok", result` then also set order_id via emit_symbol_decision's order_id |
| timeout (~1110) | `..."failed", "timeout", result` |
| exception (~1126) | `..."failed", "place_error", result, error=str(e)[:200]` |

Because the account_id is computed at line ~1018 (`account_id = cfg["account_id"]`), capture it once near the top of `_try_trade` for the emit helper: add `account_id = cfg.get("account_id", "")` right after `cfg = state.config` at the top.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/test_auto_trade_service_unit.py`:

```python
@pytest.mark.asyncio
async def test_try_trade_emits_min_score_skip_decision():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    rec = MagicMock()
    ctx = object()
    ex = AutoTradeExecutor(AsyncMock(), None, recorder=rec, debug_ctx=ctx)
    state = _AccountState(config={
        "account_id": "acc_1", "min_score": 7, "confidence_filter": "any",
        "execution_mode": "batch",
    })
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -3}  # |score|=3 < min_score 7
    out = await ex._try_trade(state, result, phase="batch")
    assert out is None
    # A skipped decision with reason min_score must have been emitted.
    rec.emit_symbol_decision.assert_called()
    _, kwargs = rec.emit_symbol_decision.call_args
    assert kwargs["reason_code"] == "min_score"
    assert kwargs["decision"] == "skipped"


@pytest.mark.asyncio
async def test_try_trade_emit_is_noop_without_recorder():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    ex = AutoTradeExecutor(AsyncMock(), None)  # no recorder
    state = _AccountState(config={"account_id": "acc_1", "min_score": 7, "execution_mode": "batch"})
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -3}
    out = await ex._try_trade(state, result)  # must not raise
    assert out is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -k try_trade_emits -v`
Expected: FAIL — `_try_trade` does not accept `phase` and does not emit.

- [ ] **Step 3: Implement the emits**

Apply two changes in `_try_trade`:

(a) Signature — change `async def _try_trade(self, state, result, *, relaxed=False)` to:
```python
    async def _try_trade(self, state: "_AccountState", result: Dict[str, Any], *, relaxed: bool = False, phase: str = "batch") -> Optional[TradeExecution]:
```
(b) Right after `cfg = state.config`, add: `account_id = cfg.get("account_id", "")`.

Then add `self._emit_decision(account_id, phase, symbol, ...)` lines per the table above, immediately before each corresponding `return`/at the success/timeout/exception points. The success emit must include the order_id — emit it AFTER `execution.order_id` is known:

```python
            # after: state.trades_executed += 1; state.executions.append(execution)
            if self._recorder is not None and self._debug_ctx is not None:
                self._recorder.emit_symbol_decision(
                    self._debug_ctx, account_id=account_id, phase=phase, symbol=symbol,
                    decision="placed", reason_code="placed_ok", reason_detail={},
                    scan_score=result.get("score"), scan_confidence=result.get("confidence"),
                    scan_direction=result.get("direction"), order_id=execution.order_id,
                )
```

> Implementer guidance: do NOT alter any existing control flow, counters, or return values — only insert emit calls. Keep each insert on its own line directly above the return it documents.

**Update all five `_try_trade` call sites to pass the correct `phase`** (the new kwarg defaults to `"batch"`, so unlabeled callers would mislabel decisions). Exact sites in `auto_trade_service.py`:
- Line ~385 (`evaluate_result`, immediate mode): `await self._try_trade(state, result, phase="immediate")`
- Line ~421 (`execute_batch`, strict pass): `await self._try_trade(state, result, phase="batch")`
- Line ~464 (`execute_batch` fill pass): `await self._try_trade(state, result, relaxed=True, phase="fill")`
- Line ~530 (`fill_immediate_remaining`): `await self._try_trade(state, result, relaxed=True, phase="fill")`
- Line ~886 (`post_scan_recheck`): `await self._try_trade(state, result, phase="post_scan_recheck")`

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -v`
Expected: PASS (all existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/auto_trade_service.py tests/backend/test_auto_trade_service_unit.py
git commit -m "feat(debug): emit per-symbol decisions from _try_trade"
```

### Task 8: Instrument init_balances + post_scan_recheck (snapshots, lifecycle, account traces)

**Files:**
- Modify: `backend/services/auto_trade_service.py` (`init_balances` ~191-206 skip branch, ~221-232 snapshot, rule creation; `post_scan_recheck` ~649-708, ~872-890; `get_summaries`/finalize emit account traces)
- Test: `tests/backend/test_auto_trade_service_unit.py`

Add these emits (additive only):

In `init_balances`:
- At the skip branch (positions open, ~202-206): `self._emit_snapshot(account_id, "scan_start", positions, ...)` then `self._emit_life(account_id, "init_balances", "marked_stopped", reason="positions_already_open", position_count=len(positions))`.
- After recording existing-position symbols (~228): `self._emit_snapshot(account_id, "scan_start", positions_cache[account_id], equity=state.base_capital)`.
- After successful rule creation block (~341, `rules_created_for.add(account_id)`): `self._emit_life(account_id, "init_balances", "rules_created", rule_ids=list(state.created_rule_ids))`.

In `post_scan_recheck`:
- On entry to per-account loop (~648): `self._emit_snapshot(account_id, "recheck", positions)` and `self._emit_life(account_id, "post_scan_recheck", "recheck_entered", position_count=len(positions))`.
- At `if has_positions and not force_closed: continue` (~701): `self._emit_life(account_id, "post_scan_recheck", "recheck_positions_still_open")`.
- After state reset (~771): `self._emit_life(account_id, "post_scan_recheck", "state_reset", new_balance=new_balance)`.
- Trades placed in recheck call `_try_trade(state, result, phase="post_scan_recheck")` (pass the phase).

Add a new method `emit_account_summaries(self)` called at finalize that, for each state, emits an account-trace record. It is **async** so it can resolve the human-readable account label off the hot path (finalize only):

```python
    async def emit_account_summaries(self) -> None:
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        # Resolve labels once per account (off the hot path — finalize only). Best-effort.
        label_cache: Dict[str, Optional[str]] = {}
        for state in self._state.values():
            aid = state.config.get("account_id", "")
            if aid and aid not in label_cache:
                try:
                    acct = await self._accounts.get_account(aid)
                    label_cache[aid] = (acct or {}).get("label")
                except Exception:
                    label_cache[aid] = None
            rec.emit_account_trace(
                ctx, account_id=aid,
                account_label=label_cache.get(aid),
                execution_mode=state.config.get("execution_mode"),
                final_stopped_reason=state.stopped_reason,
                gate_that_stopped=state.stopped_reason,
                rescued_by_recheck=getattr(state, "rescued_by_recheck", False),
                base_capital=state.base_capital,
                positions_at_start_count=len(state.existing_symbols),
                trades_executed=state.trades_executed,
                trades_failed=state.trades_failed,
                trades_skipped=state.trades_skipped,
                rules_created=[{"rule_id": r} for r in state.created_rule_ids],
                config_snapshot=_sanitize_config(state.config),
            )
```

> **`rescued_by_recheck` must be a real flag, not inferred.** Inferring it from `stopped_reason is None and trades_executed > 0` would be TRUE for every normal account that simply traded — wrong. Instead, add a field to `_AccountState` (Task: the dataclass near line 1142) — `rescued_by_recheck: bool = False` — and set it to `True` inside `post_scan_recheck` at the point where a previously `positions_already_open` account is reset and goes on to place at least one trade (right after the state reset / successful placement in the recheck loop, ~line 760-890). `emit_account_summaries` then reads that real flag.

Because `emit_account_summaries` is now `async`, update its single call site in the scanner finalize block (Task 11d) to `await executor.emit_account_summaries()` (already shown with `await` there).

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/test_auto_trade_service_unit.py`:

```python
@pytest.mark.asyncio
async def test_init_balances_emits_snapshot_and_skip_when_positions_open():
    from backend.services.auto_trade_service import AutoTradeExecutor
    rec = MagicMock()
    ctx = object()
    accounts = AsyncMock()
    accounts.get_account.return_value = {"id": "acc_1"}
    accounts.get_positions.return_value = [{"symbol": "AAPLUSDT", "side": "Sell", "size": "1"}]
    accounts.get_wallet.return_value = {"totalAvailableBalance": "1000", "totalWalletBalance": "1000"}
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    ex.init_configs([{"account_id": "acc_1", "skip_if_positions_open": True, "execution_mode": "batch"}])
    await ex.init_balances()
    # A scan_start snapshot and a marked_stopped lifecycle event were emitted.
    assert rec.emit_exchange_snapshot.called
    evs = [c.kwargs.get("event_type") for c in rec.emit_lifecycle.call_args_list]
    assert "marked_stopped" in evs


@pytest.mark.asyncio
async def test_emit_account_summaries_emits_one_per_state():
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState
    rec = MagicMock()
    ctx = object()
    accounts = AsyncMock()
    accounts.get_account.return_value = {"id": "acc_1", "label": "Dad - Demo"}
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    ex._state = {"acc_1_0": _AccountState(config={"account_id": "acc_1", "execution_mode": "batch"})}
    await ex.emit_account_summaries()
    rec.emit_account_trace.assert_called_once()
    _, kwargs = rec.emit_account_trace.call_args
    assert kwargs["account_label"] == "Dad - Demo"   # label resolved off the hot path
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -k "emits_snapshot or account_summaries" -v`
Expected: FAIL (`emit_account_summaries` undefined; snapshots not emitted).

- [ ] **Step 3: Implement the emits + helpers**

Add `_sanitize_config` (module level) and `emit_account_summaries` (method) as shown above, and insert the additive `self._emit_*` calls at the documented locations in `init_balances` and `post_scan_recheck`. Do not change existing control flow.

```python
def _sanitize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    bad = ("key", "secret", "token", "password")
    return {k: v for k, v in cfg.items() if not any(b in k.lower() for b in bad)}
```

**Add the `rescued_by_recheck` field to `_AccountState`** (the dataclass near line 1142, alongside `stopped`, `stopped_reason`, etc.):
```python
    rescued_by_recheck: bool = False
```
Then in `post_scan_recheck`, after a previously-skipped account is reset and successfully places at least one trade in the recheck loop (i.e. inside the `# Execute trades from scan results` block ~line 872-890, when `total_executed > 0` for that account), set `state.rescued_by_recheck = True` on each state for that account. Concretely, after the recheck trade loop computes `total_executed` (~line 893), add:
```python
                if total_executed > 0:
                    async with self._lock:
                        for state in states:
                            state.rescued_by_recheck = True
```
This makes `rescued_by_recheck` a real signal (only accounts that were rescued by the post-scan recheck), not an inference.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/services/auto_trade_service.py tests/backend/test_auto_trade_service_unit.py
git commit -m "feat(debug): emit snapshots, lifecycle events, and account summaries from executor"
```

---

## Phase 4 — Scanner/manual wiring, schemas, read API, lifespan

### Task 9: Repository read side — aggregate tree + sub-route queries

**Files:**
- Modify: `backend/services/debug_trace_repository.py`
- Test: `tests/backend/test_debug_trace_repository.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backend/test_debug_trace_repository.py`:

```python
@pytest.mark.asyncio
async def test_get_latest_run_for_scan_and_tree(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-tree", trigger_source="scheduled")
    await repo.bulk_insert(
        account_traces=[{"run_id": run_id, "account_id": "acc-1", "account_label": "Dad - Demo",
                         "execution_mode": "batch", "rescued_by_recheck": True,
                         "trades_executed": 3, "trades_failed": 0, "trades_skipped": 5,
                         "rules_created": [], "config_snapshot": {}}],
        lifecycle_events=[{"run_id": run_id, "account_id": "acc-1", "seq": 0,
                           "phase": "post_scan_recheck", "event_type": "state_reset", "detail": {}}],
        symbol_decisions=[{"run_id": run_id, "account_id": "acc-1", "phase": "post_scan_recheck",
                           "symbol": "B3USDT", "decision": "placed", "reason_code": "placed_ok",
                           "reason_detail": {}}],
        exchange_snapshots=[{"run_id": run_id, "account_id": "acc-1", "gate": "scan_start",
                             "positions": [], "position_count": 0, "wallet": {}}],
    )
    latest = await repo.get_latest_run_id_for_scan("scan-tree")
    assert latest == run_id
    tree = await repo.get_run_tree(run_id)
    assert tree["run"]["scan_id"] == "scan-tree"
    assert len(tree["accounts"]) == 1
    acct = tree["accounts"][0]
    assert acct["account_id"] == "acc-1"
    assert len(acct["lifecycle_events"]) == 1
    assert len(acct["symbol_decisions"]) == 1
    assert len(acct["exchange_snapshots"]) == 1
    # Linked-record keys are always present (spec §6.1), even when empty.
    assert "linked_trades" in acct
    assert "linked_close_rules" in acct
    assert "linked_close_executions" in acct


@pytest.mark.asyncio
async def test_list_runs_and_account_timeline(pool):
    repo = DebugTraceRepository(pool)
    r1 = await repo.create_run(scan_id="scan-x", trigger_source="scheduled")
    await repo.bulk_insert(account_traces=[{"run_id": r1, "account_id": "acc-9",
        "rules_created": [], "config_snapshot": {}}])
    runs = await repo.list_runs(limit=10, offset=0)
    assert any(r["id"] == r1 for r in runs["items"])
    tl = await repo.get_account_timeline("acc-9", limit=10)
    assert any(t["run_id"] == r1 for t in tl)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -k "tree or timeline" -v`
Expected: FAIL with `AttributeError` (read methods undefined).

- [ ] **Step 3: Implement read methods**

Append to `DebugTraceRepository`:

```python
    # ── reads ─────────────────────────────────────────────────
    async def get_latest_run_id_for_scan(self, scan_id: str) -> Optional[int]:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT id FROM debug_runs WHERE scan_id=$1 ORDER BY created_at DESC LIMIT 1",
                scan_id,
            )

    async def get_run_tree(self, run_id: int) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            run = await conn.fetchrow("SELECT * FROM debug_runs WHERE id=$1", run_id)
            if run is None:
                return {}
            accts = await conn.fetch("SELECT * FROM debug_account_traces WHERE run_id=$1 ORDER BY account_id", run_id)
            events = await conn.fetch("SELECT * FROM debug_lifecycle_events WHERE run_id=$1 ORDER BY account_id, seq", run_id)
            decisions = await conn.fetch("SELECT * FROM debug_symbol_decisions WHERE run_id=$1 ORDER BY account_id, ts", run_id)
            snaps = await conn.fetch("SELECT * FROM debug_exchange_snapshots WHERE run_id=$1 ORDER BY account_id, gate", run_id)
        by_acct_ev: dict[str, list] = {}
        for e in events:
            by_acct_ev.setdefault(e["account_id"], []).append(dict(e))
        by_acct_dec: dict[str, list] = {}
        for d in decisions:
            by_acct_dec.setdefault(d["account_id"], []).append(dict(d))
        by_acct_snap: dict[str, list] = {}
        for s in snaps:
            by_acct_snap.setdefault(s["account_id"], []).append(dict(s))
        accounts = []
        for a in accts:
            aid = a["account_id"]
            node = dict(a)
            node["lifecycle_events"] = by_acct_ev.get(aid, [])
            node["symbol_decisions"] = by_acct_dec.get(aid, [])
            node["exchange_snapshots"] = by_acct_snap.get(aid, [])
            # Linked external records (spec §6.1): trades by placed order_id; rules/closes by account+window.
            node["linked_trades"] = await self._linked_trades_for_account(run, aid, by_acct_dec.get(aid, []))
            node["linked_close_rules"], node["linked_close_executions"] = \
                await self._linked_rules_and_closes(run, aid)
            node["narrative"] = _build_narrative(node)
            accounts.append(node)
        return {"run": dict(run), "accounts": accounts}

    async def _linked_trades_for_account(self, run, account_id: str, decisions: list[dict]) -> list[dict]:
        """Resulting trades for this account in this run, matched by placed order_id.

        order_id is the precise run-scoped key: debug_symbol_decisions rows with
        decision='placed' carry the order_id returned by place_trade, which equals
        trades.order_id. Falls back to empty when no placements were recorded.
        """
        order_ids = [d.get("order_id") for d in decisions if d.get("decision") == "placed" and d.get("order_id")]
        if not order_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, symbol, side, status, close_reason, opened_at, closed_at,
                       realized_pnl, order_id, scan_result_id
                FROM trades WHERE account_id=$1 AND order_id = ANY($2::text[])
                ORDER BY opened_at
                """,
                account_id, order_ids,
            )
        return [dict(r) for r in rows]

    async def _linked_rules_and_closes(self, run, account_id: str):
        """close_rules and close_executions for this account within the run's time window.

        Window = [exec_started_at, coalesce(exec_completed_at, now) + 5 min]. This captures
        rules created during the run and any close that fired through the auto-trade phase.
        Returns (rules, executions). Best-effort: empty lists if the window is unknown.
        """
        start = run["exec_started_at"]
        end = run["exec_completed_at"]
        if start is None:
            return [], []
        async with self._pool.acquire() as conn:
            rules = await conn.fetch(
                """
                SELECT id, trigger_type, threshold_value, reference_value, status,
                       created_at, triggered_at, expires_at
                FROM close_rules
                WHERE account_id=$1
                  AND created_at >= $2
                  AND created_at <= COALESCE($3, now()) + interval '5 minutes'
                ORDER BY created_at
                """,
                account_id, start, end,
            )
            closes = await conn.fetch(
                """
                SELECT id, rule_id, trigger_source, total_positions, closed_count,
                       failed_count, executed_at
                FROM close_executions
                WHERE account_id=$1
                  AND executed_at >= $2
                  AND executed_at <= COALESCE($3, now()) + interval '5 minutes'
                ORDER BY executed_at
                """,
                account_id, start, end,
            )
        return [dict(r) for r in rules], [dict(r) for r in closes]

    async def list_runs(self, *, limit: int = 20, offset: int = 0,
                        trigger_source: Optional[str] = None,
                        account_id: Optional[str] = None,
                        from_ts: Optional[str] = None,
                        to_ts: Optional[str] = None) -> dict[str, Any]:
        # Build args positionally; track each placeholder index explicitly to avoid drift.
        args: list = []
        join = ""
        where: list[str] = []
        if account_id:
            args.append(account_id)
            join = f"JOIN debug_account_traces a ON a.run_id=r.id AND a.account_id=${len(args)}"
        if trigger_source:
            args.append(trigger_source)
            where.append(f"r.trigger_source=${len(args)}")
        if from_ts:
            args.append(from_ts)
            where.append(f"r.created_at >= ${len(args)}::timestamptz")
        if to_ts:
            args.append(to_ts)
            where.append(f"r.created_at <= ${len(args)}::timestamptz")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT count(DISTINCT r.id) FROM debug_runs r {join} {clause}", *args
            )
            args.append(limit); limit_ph = len(args)
            args.append(offset); offset_ph = len(args)
            rows = await conn.fetch(
                f"SELECT DISTINCT r.* FROM debug_runs r {join} {clause} "
                f"ORDER BY r.created_at DESC LIMIT ${limit_ph} OFFSET ${offset_ph}",
                *args,
            )
        return {"items": [dict(r) for r in rows], "total": total or 0, "limit": limit, "offset": offset}

    async def get_account_timeline(self, account_id: str, *, limit: int = 50,
                                   from_ts: Optional[str] = None,
                                   to_ts: Optional[str] = None) -> list[dict]:
        args: list = [account_id]
        where = ["a.account_id=$1"]
        if from_ts:
            args.append(from_ts); where.append(f"r.created_at >= ${len(args)}::timestamptz")
        if to_ts:
            args.append(to_ts); where.append(f"r.created_at <= ${len(args)}::timestamptz")
        args.append(limit); limit_ph = len(args)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT a.*, r.scan_id, r.trigger_source, r.created_at AS run_created_at
                FROM debug_account_traces a JOIN debug_runs r ON r.id=a.run_id
                WHERE {' AND '.join(where)} ORDER BY r.created_at DESC LIMIT ${limit_ph}
                """,
                *args,
            )
        return [dict(r) for r in rows]

    async def get_symbol_decisions(self, symbol: str, *, scan_id: Optional[str] = None,
                                   limit: int = 200) -> list[dict]:
        async with self._pool.acquire() as conn:
            if scan_id:
                rows = await conn.fetch(
                    """
                    SELECT d.*, r.scan_id FROM debug_symbol_decisions d
                    JOIN debug_runs r ON r.id=d.run_id
                    WHERE d.symbol=$1 AND r.scan_id=$2 ORDER BY d.ts DESC LIMIT $3
                    """,
                    symbol, scan_id, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM debug_symbol_decisions WHERE symbol=$1 ORDER BY ts DESC LIMIT $2",
                    symbol, limit,
                )
        return [dict(r) for r in rows]
```

Also add the narrative builder (module level, above the class):

```python
def _build_narrative(node: dict) -> str:
    """Plain-English per-account story from the trace node.

    Mirrors the spec example: entry state → mid-scan close (from linked
    close_executions) → recheck rescue → trades placed.
    """
    aid = node.get("account_label") or node.get("account_id")
    reason = node.get("final_stopped_reason")
    executed = node.get("trades_executed", 0)
    skipped = node.get("trades_skipped", 0)
    rescued = node.get("rescued_by_recheck")
    parts = [f"Account {aid}:"]
    snaps = {s["gate"]: s for s in node.get("exchange_snapshots", [])}
    start = snaps.get("scan_start")
    recheck = snaps.get("recheck")
    if start:
        parts.append(f"at scan-start held {start['position_count']} position(s)")
    if reason == "positions_already_open":
        parts.append("→ skipped (positions already open at scan-start)")
    # If positions closed mid-scan, surface the close time from linked close_executions.
    closes = node.get("linked_close_executions", []) or []
    if closes and start and start["position_count"] > 0:
        last_close = max(closes, key=lambda c: c.get("executed_at") or "")
        when = str(last_close.get("executed_at", ""))[:19]
        parts.append(f"→ prior positions closed during scan ({when})")
    elif recheck is not None and start and start["position_count"] > 0 and recheck["position_count"] == 0:
        parts.append("→ positions cleared during scan (recheck saw 0)")
    if rescued:
        parts.append("→ rescued by post-scan recheck")
    if executed:
        placed_syms = [d["symbol"] for d in node.get("symbol_decisions", []) if d.get("decision") == "placed"]
        sym_str = f" ({'/'.join(placed_syms[:6])})" if placed_syms else ""
        parts.append(f"→ placed {executed} trade(s){sym_str}")
    if skipped:
        parts.append(f"(skipped {skipped} candidate signals)")
    if not executed and reason and reason != "positions_already_open":
        parts.append(f"→ no trades (stopped: {reason})")
    return " ".join(parts)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_debug_trace_repository.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/services/debug_trace_repository.py tests/backend/test_debug_trace_repository.py
git commit -m "feat(debug): add aggregate-tree + sub-route read queries with narrative"
```

### Task 10: Debug API schemas + router

**Files:**
- Create: `backend/schemas/debug.py`
- Create: `backend/routers/debug.py`
- Test: `tests/backend/test_debug_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_debug_router.py`:

```python
"""Tests for the /api/v1/debug router using a stubbed recorder/repository on app.state."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.debug import router as debug_router


def _app(repo, recorder):
    app = FastAPI()
    app.state.debug_trace_recorder = recorder
    recorder._repo = repo
    app.include_router(debug_router, prefix="/api/v1")
    return app


def test_get_scan_tree_returns_aggregate():
    repo = MagicMock()
    repo.get_latest_run_id_for_scan = AsyncMock(return_value=7)
    repo.get_run_tree = AsyncMock(return_value={
        "run": {"id": 7, "scan_id": "s1", "trigger_source": "scheduled"},
        "accounts": [{"account_id": "a1", "account_label": "Dad - Demo",
                      "lifecycle_events": [], "symbol_decisions": [],
                      "exchange_snapshots": [], "narrative": "Account Dad - Demo: ..."}],
    })
    recorder = MagicMock()
    client = TestClient(_app(repo, recorder))
    resp = client.get("/api/v1/debug/scan/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["scan_id"] == "s1"
    assert body["accounts"][0]["account_label"] == "Dad - Demo"


def test_get_scan_tree_404_when_no_run():
    repo = MagicMock()
    repo.get_latest_run_id_for_scan = AsyncMock(return_value=None)
    recorder = MagicMock()
    client = TestClient(_app(repo, recorder))
    resp = client.get("/api/v1/debug/scan/missing")
    assert resp.status_code == 404


def test_get_and_update_config():
    repo = MagicMock()
    repo.get_config = AsyncMock(return_value={"tracing_enabled": True, "retention_days": 60, "symbol_decision_cap": 200})
    repo.update_config = AsyncMock(return_value={"tracing_enabled": False, "retention_days": 30, "symbol_decision_cap": 200})
    recorder = MagicMock()
    recorder.refresh_config = AsyncMock()
    client = TestClient(_app(repo, recorder))
    assert client.get("/api/v1/debug/config").json()["retention_days"] == 60
    resp = client.put("/api/v1/debug/config", json={"tracing_enabled": False, "retention_days": 30})
    assert resp.status_code == 200
    assert resp.json()["tracing_enabled"] is False
    recorder.refresh_config.assert_awaited()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_debug_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.routers.debug'`

- [ ] **Step 3: Implement schemas + router**

Create `backend/schemas/debug.py`:

```python
"""Pydantic v2 models for the debug API."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class DebugConfigUpdate(BaseModel):
    tracing_enabled: Optional[bool] = None
    retention_days: Optional[int] = Field(None, ge=1, le=3650)
    symbol_decision_cap: Optional[int] = Field(None, ge=0, le=100000)
```

Create `backend/routers/debug.py`:

```python
"""Auto-trade debug forensics API (/api/v1/debug)."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.debug import DebugConfigUpdate

router = APIRouter(tags=["debug"])


def _repo(request: Request):
    recorder = getattr(request.app.state, "debug_trace_recorder", None)
    if recorder is None or getattr(recorder, "_repo", None) is None:
        raise HTTPException(503, detail="Debug tracing not available")
    return recorder, recorder._repo


@router.get("/debug/scan/{scan_id}")
async def get_scan_tree(request: Request, scan_id: str, run_id: Optional[int] = Query(None)):
    _, repo = _repo(request)
    rid = run_id or await repo.get_latest_run_id_for_scan(scan_id)
    if rid is None:
        raise HTTPException(404, detail="No debug run found for this scan")
    tree = await repo.get_run_tree(rid)
    if not tree:
        raise HTTPException(404, detail="Debug run not found")
    return tree


@router.get("/debug/scan/{scan_id}/account/{account_id}")
async def get_scan_account(request: Request, scan_id: str, account_id: str, run_id: Optional[int] = Query(None)):
    _, repo = _repo(request)
    rid = run_id or await repo.get_latest_run_id_for_scan(scan_id)
    if rid is None:
        raise HTTPException(404, detail="No debug run found for this scan")
    tree = await repo.get_run_tree(rid)
    for acct in tree.get("accounts", []):
        if acct["account_id"] == account_id:
            return {"run": tree["run"], "account": acct}
    raise HTTPException(404, detail="Account not found in this run")


@router.get("/debug/runs")
async def list_runs(request: Request, limit: int = Query(20, ge=1, le=100),
                    offset: int = Query(0, ge=0), trigger_source: Optional[str] = None,
                    account_id: Optional[str] = None,
                    from_ts: Optional[str] = Query(None, alias="from"),
                    to_ts: Optional[str] = Query(None, alias="to")):
    _, repo = _repo(request)
    return await repo.list_runs(limit=limit, offset=offset,
                                trigger_source=trigger_source, account_id=account_id,
                                from_ts=from_ts, to_ts=to_ts)


@router.get("/debug/account/{account_id}/timeline")
async def account_timeline(request: Request, account_id: str, limit: int = Query(50, ge=1, le=200),
                           from_ts: Optional[str] = Query(None, alias="from"),
                           to_ts: Optional[str] = Query(None, alias="to")):
    _, repo = _repo(request)
    return {"items": await repo.get_account_timeline(account_id, limit=limit,
                                                     from_ts=from_ts, to_ts=to_ts)}


@router.get("/debug/symbol/{symbol}")
async def symbol_decisions(request: Request, symbol: str, scan_id: Optional[str] = None,
                           limit: int = Query(200, ge=1, le=1000)):
    _, repo = _repo(request)
    return {"items": await repo.get_symbol_decisions(symbol, scan_id=scan_id, limit=limit)}


@router.get("/debug/config")
async def get_config(request: Request):
    _, repo = _repo(request)
    return await repo.get_config()


@router.put("/debug/config")
async def update_config(request: Request, body: DebugConfigUpdate):
    recorder, repo = _repo(request)
    cfg = await repo.update_config(
        tracing_enabled=body.tracing_enabled,
        retention_days=body.retention_days,
        symbol_decision_cap=body.symbol_decision_cap,
    )
    await recorder.refresh_config()
    return cfg
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_debug_router.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/debug.py backend/routers/debug.py tests/backend/test_debug_router.py
git commit -m "feat(debug): add /api/v1/debug router with aggregate tree + sub-routes"
```

### Task 11: Wire recorder into ScannerService (scheduled path) + manual route

**Files:**
- Modify: `backend/services/scanner_service.py` (`__init__` line 320; executor construction lines 416, 576; finalize block ~777-862)
- Modify: `backend/routers/scanner.py` (`_run_auto_trade`, ~205-247)
- Test: `tests/backend/test_scanner_service.py` (add a wiring test) and manual check

**Key ordering constraint:** the `RunContext` must exist BEFORE `init_balances()` so scan-start snapshots are captured. So: create the ctx, construct the executor WITH `recorder` + `debug_ctx`, call `recorder.open_run(ctx, ...)`, THEN `init_balances()`.

- [ ] **Step 1: Add a wiring test**

Append to `tests/backend/test_scanner_service.py`:

```python
@pytest.mark.asyncio
async def test_scanner_passes_recorder_to_executor(monkeypatch):
    """ScannerService stores a debug_recorder and builds a RunContext for the auto-trade phase."""
    from backend.services.scanner_service import ScannerService
    rec = MagicMock()
    rec.new_run_context = MagicMock(return_value=MagicMock(run_id=None))
    rec.open_run = AsyncMock()
    svc = ScannerService(analysis_service=MagicMock(), db=None, debug_recorder=rec)
    assert svc._debug_recorder is rec
```

> Note: `MagicMock`/`AsyncMock` import already present in this test file; if not, add `from unittest.mock import AsyncMock, MagicMock`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_scanner_service.py::test_scanner_passes_recorder_to_executor -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'debug_recorder'`

- [ ] **Step 3: Implement scanner wiring**

(a) In `backend/services/scanner_service.py`, change `__init__` (line 320) signature to add the param and store it:

```python
    def __init__(self, analysis_service: Any, db: Any = None, ws_manager: Any = None, accounts_service: Any = None, close_positions_service: Any = None, ai_manager_service: Any = None, sector_service: Any = None, debug_recorder: Any = None):
```
and after `self._sector_service = sector_service` (line 327) add:
```python
        self._debug_recorder = debug_recorder
```

(b) At the scheduled executor construction (lines 416-419), replace with:

```python
            debug_ctx = None
            if self._debug_recorder is not None:
                debug_ctx = self._debug_recorder.new_run_context(
                    scan_id=scan_id,
                    trigger_source=("scheduled" if scan.get("schedule_id") else "run_now"),
                    schedule_id=scan.get("schedule_id"),
                )
            executor = AutoTradeExecutor(
                self._accounts, self._close_svc, self._ai_manager_service,
                sector_service=self._sector_service,
                recorder=self._debug_recorder, debug_ctx=debug_ctx,
            )
            if self._debug_recorder is not None and debug_ctx is not None:
                await self._debug_recorder.open_run(
                    debug_ctx,
                    config_snapshot={"num_configs": len(auto_configs)},
                )
            executor.init_configs(auto_configs)
            await executor.init_balances()
            scan["auto_trade_executor"] = executor
            scan["debug_ctx"] = debug_ctx
```

The `config_snapshot` deliberately stores only `{"num_configs": ...}` (a count, not the raw configs) to avoid persisting any per-account config containing potentially sensitive fields; per-account sanitized config is captured separately by `emit_account_summaries` in Task 8.

(c) The second executor construction (line 576, resume path, inside `resume_incomplete_scans`) — apply the same pattern, with these specifics: the resume `scan` dict does **not** carry a `schedule_id`, so build the ctx as:
```python
            debug_ctx = None
            if self._debug_recorder is not None:
                debug_ctx = self._debug_recorder.new_run_context(
                    scan_id=scan_id, trigger_source="scheduled", schedule_id=None,
                )
            executor = AutoTradeExecutor(
                self._accounts, self._close_svc, self._ai_manager_service,
                sector_service=self._sector_service,
                recorder=self._debug_recorder, debug_ctx=debug_ctx,
            )
            if self._debug_recorder is not None and debug_ctx is not None:
                await self._debug_recorder.open_run(debug_ctx, config_snapshot={"num_configs": len(auto_configs), "resumed": True})
            executor.init_configs(auto_configs)
            # ... existing restore_state(...) call stays ...
            await executor.init_balances()
            # ... after scan["auto_trade_executor"] = executor:
            scan["debug_ctx"] = debug_ctx
```

> **Immediate-mode note (no extra run needed):** immediate-mode configs trade *during* the scan via `evaluate_result` (called from `_handle_completed_analysis`), not at finalize. Because the executor instance was constructed with `debug_ctx` and `open_run` set `ctx.run_id` *before* `init_balances`, those during-scan `_try_trade` emits are already captured under the same run. Do **not** open a second run for immediate mode.

(d) **CRITICAL — variable scope.** `final_completed` and `final_failed` are top-level locals (assigned at lines 773-774 and reassigned ~848-849), so they are always in scope at the `if executor:` block (~853). But `total` is assigned **only inside** the `if not scan_error:` block (~line 784), so referencing `total` at the `if executor:` block raises `NameError` whenever `scan_error` is truthy (the executor can still be truthy on the error path because it is re-read at ~834). **Do not use `total`.** Capture the symbol count from the `scan` dict under the finalize lock instead.

In the finalize block, after `scan["auto_trade_summaries"] = executor.get_summaries()` (~862), add:

```python
            # Debug: emit account summaries and close the debug run.
            try:
                await executor.emit_account_summaries()
            except Exception:
                pass
            debug_ctx = scan.get("debug_ctx") if scan else None
            if self._debug_recorder is not None and debug_ctx is not None:
                # Read symbol counts from the scan dict (NOT `total`, which is only
                # defined inside the `if not scan_error:` block above).
                async with self._lock:
                    _scan = self._scans.get(scan_id)
                    _total = (_scan.get("total", 0) if _scan else 0)
                num_accounts = len({s.config.get("account_id") for s in executor._state.values()})
                await self._debug_recorder.close_run(
                    debug_ctx, phase_reached=("failed" if scan_error else "finalized"),
                    total_symbols=_total, completed_symbols=final_completed,
                    failed_symbols=final_failed, num_accounts=num_accounts,
                )
```

> Note: `final_completed` / `final_failed` are guaranteed defined (top-level init at ~773-774). `scan_error` is in scope throughout `_run_scan`. This avoids the `total` NameError entirely.

(e) In `backend/routers/scanner.py` `_run_auto_trade` (~205): construct the recorder ctx and open/close a run around the manual executor, mirroring (b)+(d). Get the recorder via `getattr(request.app.state, "debug_trace_recorder", None)`. Trigger source = `"manual"`. This guarantees a manual re-trigger creates a NEW run (never overwrites).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_scanner_service.py -v`
Expected: PASS (existing + new wiring test).

- [ ] **Step 5: Commit**

```bash
git add backend/services/scanner_service.py backend/routers/scanner.py tests/backend/test_scanner_service.py
git commit -m "feat(debug): wire recorder + run lifecycle into scheduled and manual auto-trade"
```

### Task 12: Lifespan wiring in main.py + router registration

**Files:**
- Modify: `backend/main.py` (instantiate recorder ~before ScannerService at line 218; start/stop in lifespan; register router near line 561)
- Test: `tests/backend/test_main.py` (smoke: app starts, `/api/v1/debug/config` reachable when recorder present)

- [ ] **Step 1: Add a smoke test**

Append to `tests/backend/test_main.py` (follow the file's existing app-construction pattern; if it uses a TestClient fixture, reuse it):

```python
def test_debug_router_registered():
    """The debug router is registered under /api/v1 (route exists even if 503 without recorder)."""
    from backend.main import create_app
    app = create_app()
    paths = {r.path for r in app.routes}
    assert "/api/v1/debug/config" in paths
    assert "/api/v1/debug/scan/{scan_id}" in paths
```

> If the factory is not named `create_app`, use the actual factory/app object this test file already imports. The assertion is on registered route paths.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/backend/test_main.py::test_debug_router_registered -v`
Expected: FAIL — route not registered.

- [ ] **Step 3: Implement lifespan wiring**

(a) Register the router. Near line 560-561 (where `trading_cycles_router` is imported and included), add:
```python
    from backend.routers.debug import router as debug_router
    app.include_router(debug_router, prefix="/api/v1")
```

(b) Instantiate the recorder in the lifespan BEFORE `ScannerService` is constructed (line 218). Insert just after `app.state.db = db` (line 203) area, once `db` exists:
```python
        from backend.services.debug_trace_repository import DebugTraceRepository
        from backend.services.debug_trace_recorder import DebugTraceRecorder
        debug_repo = DebugTraceRepository(db.pool)
        debug_recorder = DebugTraceRecorder(debug_repo)
        app.state.debug_trace_recorder = debug_recorder
        await debug_recorder.start()
```

(c) Pass it into `ScannerService(...)` (line 218):
```python
        app.state.scanner_service = ScannerService(
            analysis_service=app.state.analysis_service,
            db=db,
            ws_manager=ws_manager,
            debug_recorder=debug_recorder,
        )
```

(d) Shut it down in the shutdown section (near the other `_safe_shutdown` calls ~476-498):
```python
        if getattr(app.state, "debug_trace_recorder", None):
            await _safe_shutdown("debug_trace_recorder", app.state.debug_trace_recorder.shutdown())
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat(debug): instantiate recorder in lifespan and register debug router"
```

---

## Phase 5 — Performance gate, fault-injection, and end-to-end forensics

### Task 13: Performance gate — emit overhead, on/off parity, non-blocking under stalled drainer

**Files:**
- Create: `tests/backend/test_debug_trace_performance.py`

This is the binding performance constraint from spec Section 4. These tests assert the money path is not slowed.

- [ ] **Step 1: Write the performance tests**

Create `tests/backend/test_debug_trace_performance.py`:

```python
"""Performance gate for DebugTraceRecorder — the money path must never be slowed."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.debug_trace_recorder import DebugTraceRecorder


def _recorder(buffer_max=200000):
    repo = MagicMock()
    repo.bulk_insert = AsyncMock()
    rec = DebugTraceRecorder(repo, buffer_max=buffer_max)
    rec._enabled = True
    rec._symbol_decision_cap = 1000000  # don't truncate during perf test
    return rec


def test_emit_overhead_is_sub_microsecond():
    """Each enabled emit must be cheap (< ~5 microseconds average)."""
    rec = _recorder()
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    N = 50000
    start = time.perf_counter()
    for i in range(N):
        rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol="FOO",
                                 decision="skipped", reason_code="min_score", reason_detail={})
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / N) * 1_000_000
    assert per_call_us < 5.0, f"emit too slow: {per_call_us:.3f} us/call"


def test_emit_when_disabled_is_effectively_free():
    rec = _recorder()
    rec._enabled = False
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    N = 100000
    start = time.perf_counter()
    for i in range(N):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / N) * 1_000_000
    assert per_call_us < 1.0, f"disabled emit too slow: {per_call_us:.3f} us/call"
    assert rec.buffered_count() == 0


@pytest.mark.asyncio
async def test_trading_unblocked_when_drainer_stalled():
    """Simulate a hung drainer: emits must still return instantly and drop on overflow."""
    rec = _recorder(buffer_max=100)
    # bulk_insert hangs forever — simulates a dead DB.
    hang = asyncio.Event()
    async def _hang(**kwargs):
        await hang.wait()
    rec._repo.bulk_insert = AsyncMock(side_effect=_hang)
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    # Fire 10k emits; must complete near-instantly despite a dead drainer.
    start = time.perf_counter()
    for i in range(10000):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"emits blocked: {elapsed:.3f}s"
    assert rec.buffered_count() == 100      # capped
    assert ctx.dropped_event_count == 9900  # rest dropped, not blocked
    hang.set()


@pytest.mark.asyncio
async def test_try_trade_timing_parity_on_vs_off():
    """Batch _try_trade timing with tracing ON must be within tolerance of OFF."""
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState

    def make_executor(with_recorder):
        rec = _recorder() if with_recorder else None
        ctx = rec.new_run_context(scan_id="s1") if rec else None
        if ctx:
            ctx.run_id = 1
        accounts = AsyncMock()
        return AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)

    async def run(executor, n):
        state = _AccountState(config={"account_id": "a", "min_score": 9,
                                      "confidence_filter": "any", "execution_mode": "batch"})
        state.base_capital = 1000.0
        result = {"status": "completed", "ticker": "FOO", "direction": "sell",
                  "confidence": "high", "score": -3}  # always skipped at min_score
        start = time.perf_counter()
        for _ in range(n):
            await executor._try_trade(state, result, phase="batch")
        return time.perf_counter() - start

    N = 20000
    off = await run(make_executor(False), N)
    on = await run(make_executor(True), N)
    # Allow generous absolute headroom; the emit is a dict build + append.
    assert on < off + 0.5, f"tracing added too much: on={on:.3f}s off={off:.3f}s"
```

- [ ] **Step 2: Run the performance gate**

Run: `python -m pytest tests/backend/test_debug_trace_performance.py -v`
Expected: PASS (4 tests). If `test_emit_overhead_is_sub_microsecond` fails on a slow CI box, the threshold may be relaxed to `< 8.0` us, but investigate any regression first — the emit must remain a pure in-memory dict build + append.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_debug_trace_performance.py
git commit -m "test(debug): add performance gate — emit overhead, on/off parity, non-blocking"
```

### Task 14: Fault injection — recorder failure never breaks a trade

**Files:**
- Create: `tests/backend/test_auto_trade_instrumentation.py`

- [ ] **Step 1: Write the fault-injection test**

Create `tests/backend/test_auto_trade_instrumentation.py`:

```python
"""Verify recorder failures never break trading (fail-open contract)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState


def _exploding_recorder():
    rec = MagicMock()
    rec.emit_symbol_decision.side_effect = RuntimeError("boom")
    rec.emit_lifecycle.side_effect = RuntimeError("boom")
    rec.emit_exchange_snapshot.side_effect = RuntimeError("boom")
    rec.emit_account_trace.side_effect = RuntimeError("boom")
    return rec


@pytest.mark.asyncio
async def test_trade_succeeds_even_if_recorder_raises():
    """A successful trade must complete even when every emit raises."""
    accounts = AsyncMock()
    accounts.place_trade.return_value = {"trade_id": "t1", "side": "Sell"}
    accounts.get_mark_price.return_value = 100.0
    rec = _exploding_recorder()
    ctx = MagicMock()
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    state = _AccountState(config={
        "account_id": "a1", "min_score": 0, "confidence_filter": "any",
        "execution_mode": "batch", "leverage": 5, "capital_pct": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "direction": "straight",
    })
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -7, "id": 1}
    out = await ex._try_trade(state, result, phase="batch")
    assert out is not None
    assert out.status == "success"
    assert state.trades_executed == 1
```

> Implementer note: the executor's `_emit_*` helpers MUST swallow exceptions (the recorder's own emits are fail-open, but the helper call site must also be safe). If `_try_trade` calls `self._recorder.emit_symbol_decision(...)` directly anywhere (e.g. the success path), wrap that direct call in `try/except Exception: pass`. Adjust the helpers/success-path so this test passes.

- [ ] **Step 2: Run to verify**

Run: `python -m pytest tests/backend/test_auto_trade_instrumentation.py -v`
Expected: Initially may FAIL if the success-path emit is not wrapped. Wrap the direct emit call in try/except, then PASS.

- [ ] **Step 3: Harden the direct emit call (if needed)**

In `_try_trade`'s success path, ensure the direct `emit_symbol_decision` call is wrapped:
```python
            try:
                if self._recorder is not None and self._debug_ctx is not None:
                    self._recorder.emit_symbol_decision(... order_id=execution.order_id)
            except Exception:
                pass
```
Confirm the `_emit_life` / `_emit_snapshot` / `_emit_decision` helpers also guard their inner call (the recorder methods are fail-open, but defensive try/except at the call site protects against an exploding mock and any future non-fail-open path).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/backend/test_auto_trade_instrumentation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/auto_trade_service.py tests/backend/test_auto_trade_instrumentation.py
git commit -m "test(debug): assert recorder failure never breaks a trade (fail-open)"
```

### Task 15: End-to-end forensics integration test (replays the real incident)

**Files:**
- Create: `tests/backend/test_debug_end_to_end.py`

Replays the exact scenario from the RCA: an account holds positions at scan-start (skipped), positions close mid-scan, `post_scan_recheck` rescues it and places trades. Asserts the aggregate tree narrates the full story. Uses the real DB (skips if unavailable).

- [ ] **Step 1: Write the integration test**

Create `tests/backend/test_debug_end_to_end.py`:

```python
"""End-to-end: recorder + repository produce a full forensic tree for a rescue scenario."""

import os
import asyncpg
import pytest
import pytest_asyncio

from backend.services.debug_trace_repository import DebugTraceRepository
from backend.services.debug_trace_recorder import DebugTraceRecorder

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


@pytest_asyncio.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(dsn=_TEST_DSN, min_size=1, max_size=3)
    except Exception:
        pytest.skip("PostgreSQL not available")
        return
    from backend.async_persistence import _MIGRATIONS
    async with p.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = await conn.fetchrow("SELECT version FROM schema_version")
        current = row["version"] if row else 0
        if not row:
            await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for ver, sql in _MIGRATIONS:
            if ver > current:
                if callable(sql):
                    await sql(conn)
                else:
                    for stmt in sql.split(";"):
                        if stmt.strip():
                            await conn.execute(stmt)
                await conn.execute("UPDATE schema_version SET version=$1", ver)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM debug_runs")
    await p.close()


@pytest.mark.asyncio
async def test_rescue_scenario_full_tree(pool):
    repo = DebugTraceRepository(pool)
    rec = DebugTraceRecorder(repo)
    rec._enabled = True
    rec._symbol_decision_cap = 200

    ctx = rec.new_run_context(scan_id="scan-rescue", trigger_source="scheduled", schedule_id="sch-1")
    await rec.open_run(ctx, config_snapshot={"num_configs": 1})

    # Scan-start: account holds 3 positions → skipped.
    rec.emit_exchange_snapshot(ctx, account_id="dad", gate="scan_start",
                               positions=[{"symbol": "AAPLUSDT", "size": "1"},
                                          {"symbol": "NOKIAUSDT", "size": "1"},
                                          {"symbol": "BARDUSDT", "size": "1"}],
                               wallet={"totalEquity": "500"}, equity=500.0)
    rec.emit_lifecycle(ctx, account_id="dad", phase="init_balances",
                       event_type="marked_stopped", detail={"reason": "positions_already_open"})

    # Recheck: positions now gone → state reset → trades placed.
    rec.emit_exchange_snapshot(ctx, account_id="dad", gate="recheck", positions=[],
                               wallet={"totalEquity": "508"}, equity=508.0)
    rec.emit_lifecycle(ctx, account_id="dad", phase="post_scan_recheck", event_type="recheck_entered")
    rec.emit_lifecycle(ctx, account_id="dad", phase="post_scan_recheck", event_type="state_reset")
    for sym in ("B3USDT", "MUUSDT", "IBMUSDT"):
        rec.emit_symbol_decision(ctx, account_id="dad", phase="post_scan_recheck", symbol=sym,
                                 decision="placed", reason_code="placed_ok", reason_detail={},
                                 scan_score=-7, scan_confidence="high", scan_direction="sell",
                                 order_id=f"ord-{sym}")
    rec.emit_account_trace(ctx, account_id="dad", account_label="Dad - Demo",
                           execution_mode="batch", final_stopped_reason=None,
                           rescued_by_recheck=True, trades_executed=3, trades_skipped=0,
                           rules_created=[], config_snapshot={})

    await rec.close_run(ctx, phase_reached="finalized", total_symbols=580,
                        completed_symbols=580, failed_symbols=0, num_accounts=1)

    run_id = await repo.get_latest_run_id_for_scan("scan-rescue")
    tree = await repo.get_run_tree(run_id)
    assert tree["run"]["num_accounts"] == 1
    acct = tree["accounts"][0]
    assert acct["account_label"] == "Dad - Demo"
    assert acct["rescued_by_recheck"] is True
    assert len(acct["exchange_snapshots"]) == 2          # scan_start + recheck
    gates = {s["gate"] for s in acct["exchange_snapshots"]}
    assert gates == {"scan_start", "recheck"}
    placed = [d for d in acct["symbol_decisions"] if d["decision"] == "placed"]
    assert len(placed) == 3
    assert "rescued by post-scan recheck" in acct["narrative"]
    assert "placed 3 trade" in acct["narrative"]
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest tests/backend/test_debug_end_to_end.py -v`
Expected: PASS (skips if no test DB).

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_debug_end_to_end.py
git commit -m "test(debug): end-to-end forensic tree replays the rescue scenario"
```

### Task 16: Full suite + type check

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest tests/backend/ -q`
Expected: All pass (debug tests + no regressions in existing auto-trade/scanner tests).

- [ ] **Step 2: Sanity-check imports compile**

Run: `python -c "import backend.main, backend.routers.debug, backend.services.debug_trace_recorder, backend.services.debug_trace_repository; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore(debug): finalize auto-trade debug tracing feature"
```

---

## Manual Verification (post-merge, against a real environment)

After deploying, validate the feature end-to-end:
1. Trigger (or wait for) a scheduled scan with auto-trade configs.
2. `GET /api/v1/debug/runs` → the run appears with correct `trigger_source` and timing.
3. `GET /api/v1/debug/scan/{scan_id}` → full tree: every account has entry state, lifecycle events, exchange snapshots (scan_start), per-symbol decisions, and a narrative.
4. Manually trigger "Auto Trade" on the same scan → a **new** run appears (the scheduled run's record is preserved — not overwritten).
5. `PUT /api/v1/debug/config {"tracing_enabled": false}` → subsequent runs record nothing; set back to `true`.
6. `PUT /api/v1/debug/config {"retention_days": 30}` → confirm cleanup respects the new window over time.
7. Confirm trade latency/throughput is unchanged (compare order placement timings before/after).

---

## Notes for the implementer
- **Never alter existing trade control flow** in `auto_trade_service.py` — only ADD emit calls. Every emit is additive and fail-open.
- The recorder's `_enabled` flag is refreshed by the drainer loop every few seconds and on every `PUT /debug/config`, so the kill-switch takes effect within one drain interval.
- `account_label` resolution happens off the hot path: `emit_account_summaries` (async, called at finalize) resolves labels via `accounts_service.get_account(aid)["label"]`, cached per account, best-effort/try-except.
- Storage: with the default 200 symbol-decision cap and 60-day retention, a 21-account / 3-hourly schedule produces bounded growth; the nightly cleanup keeps it in check.

---

## Review-Findings Changelog (decisions baked into this plan)

These are non-obvious correctness decisions made during a verification review against the live codebase. Do not "simplify" them away.

1. **`total` is NOT used at the `if executor:` finalize block** (Task 11d). `total` is only assigned inside `if not scan_error:` (~line 784); the finalize/close-run code runs even on the error path. Using `total` there raises `NameError`. The plan re-reads the symbol count from the `scan` dict under the lock instead, and `final_completed`/`final_failed` are top-level locals (safe).
2. **JSONB via `copy_records_to_table` uses `json.dumps(...)` STRINGS** (Task 3). asyncpg's built-in `jsonb` codec is binary and accepts `str`. This is correct ONLY while no global *text* json codec is registered (none is). The round-trip assertion in `test_bulk_insert_events_and_read_back` is the regression guard.
3. **`rescued_by_recheck` is a real `_AccountState` field**, set in `post_scan_recheck`, NOT inferred from `stopped_reason is None and trades_executed > 0` (which would be true for every normal trading account).
4. **Exchange snapshots shallow-copy** `positions`/`wallet` in `emit_exchange_snapshot` — the executor reuses those structures, so without the copy the persisted snapshot would mutate.
5. **Linked records (`close_rules`, `close_executions`, `trades`) are joined into the tree** (spec §6.1): trades by placed `order_id` (precise), rules/closes by `account_id` within `[exec_started_at, exec_completed_at + 5min]`.
6. **Immediate-mode needs no second run**: immediate configs trade during the scan via `evaluate_result`; the executor already holds `debug_ctx` (set before `init_balances`), so those emits land under the same run.
7. **`schedule_execution_id` is left NULL** in this iteration (the scanner does not thread the schedule-execution id into the scan dict). The `schedule_id` + timing window is sufficient for correlation; wiring the exec id is a future enhancement, not a gap that blocks forensics.







