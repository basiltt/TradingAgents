---
title: Backend Performance Overhaul — Implementation Plan
feature: backend-performance
version: 1.0
date: 2026-05-12
spec: specs/backend-performance-spec.md
---

# Backend Performance Overhaul — Implementation Plan

## Overview

4 phases. **Phase 1 must be deployed first** — Phases 2 and 4 depend on executors and concurrency controls it creates. Phase 3 is independent. Phase 1 gives immediate relief; Phase 2 is the biggest structural change; Phases 3-4 are polish.

**Python requirement:** 3.9+ (uses `asyncio.to_thread`, `dict |` union syntax, `asyncpg` type hints).

**Estimated effort:** Phase 1 (2-3 hours), Phase 2 (8-12 hours), Phase 3 (2 hours), Phase 4 (1-2 hours)

---

## Phase 1: Thread Pool & Concurrency Fixes

### Task 1.1: Set Explicit Default Executor (FR-001)

**File:** `backend/main.py`

**Changes:**
1. Add import at top: `import concurrent.futures`
2. Add env var validation helper (used by all executor/pool configs throughout all phases):
```python
def _validated_int(name: str, default: int, min_val: int, max_val: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = int(raw)
    if not (min_val <= val <= max_val):
        raise ValueError(f"{name}={val} out of range [{min_val}, {max_val}]")
    return val
```
3. In `lifespan()`, after `loop = asyncio.get_running_loop()` (line 91), add:
```python
_default_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("THREADPOOL_MAX_WORKERS", "32")),
    thread_name_prefix="default",
)
loop.set_default_executor(_default_executor)
```
3. In teardown (before `db.close()`), add:
```python
_default_executor.shutdown(wait=False, cancel_futures=True)
```

**Test:** Start app, verify `THREADPOOL_MAX_WORKERS` is logged, run analysis, confirm health endpoint responds.

### Task 1.2: Dedicated LangGraph Executor (FR-002)

**File:** `backend/services/analysis_service.py`

**Changes:**
1. Add import: `import concurrent.futures`
2. Add module-level executor:
```python
_graph_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("GRAPH_EXECUTOR_WORKERS", "8")),
    thread_name_prefix="langgraph",
)
```
3. In `_run_analysis()` (~line 298), change:
```python
# Before:
await asyncio.to_thread(self._execute_graph, run_id, ...)
# After (MUST preserve wait_for timeout):
loop = asyncio.get_running_loop()
await asyncio.wait_for(
    loop.run_in_executor(_graph_executor, self._execute_graph, run_id, ...),
    timeout=_WALL_TIMEOUT,
)
```
4. In `shutdown()`, add `_graph_executor.shutdown(wait=False, cancel_futures=True)`
5. Expose a module-level shutdown function:
```python
def shutdown_executors():
    _graph_executor.shutdown(wait=False, cancel_futures=True)
```

**Test:** Run 4 analyses simultaneously, verify health endpoint responds < 500ms.

### Task 1.3: Configurable Max Concurrent Analyses (FR-003)

**File:** `backend/services/analysis_service.py`

**Changes:**
1. Replace line 28:
```python
_MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_ANALYSES", "8"))
```

**Test:** Set `MAX_CONCURRENT_ANALYSES=2`, start 3 analyses, verify 3rd is rejected with 429.

### Task 1.4: Fix LLM Spacing Race Condition (FR-004)

**File:** `tradingagents/llm_clients/base_client.py`

**Changes:** Replace lines 64-74 in `llm_rate_limited_invoke()`:
```python
if _llm_min_spacing_ms > 0:
    gap = 0.0
    with _llm_spacing_lock:
        now = time.monotonic()
        min_next = _llm_last_request_ts + (_llm_min_spacing_ms / 1000)
        if now < min_next:
            gap = min_next - now
        _llm_last_request_ts = max(now, min_next)
    if gap > 0:
        logger.debug("Spacing LLM call: waiting %.1fms", gap * 1000)
        time.sleep(gap)
```

**Test:** Set `LLM_MIN_SPACING_MS=500`, run 2 concurrent analyses, verify logs show spacing is enforced without serialization.

### Task 1.5: Fix parallel_debate Timeout (FR-005)

**File:** `tradingagents/graph/parallel_debate.py`

**Changes:**

1. Add imports: `import concurrent.futures` and `from concurrent.futures import wait as futures_wait`
2. Add module-level executor:
```python
_debate_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("DEBATE_EXECUTOR_WORKERS", "4")),
    thread_name_prefix="debate",
)

def shutdown_debate_executor():
    _debate_executor.shutdown(wait=False, cancel_futures=True)
```
3. Rewrite `create_parallel_risk_round1` inner function:
```python
def node(state: Dict[str, Any]) -> Dict[str, Any]:
    ordered_futures = [_debate_executor.submit(fn, state) for fn in debater_nodes]
    done, not_done = futures_wait(ordered_futures, timeout=300)
    for f in not_done:
        f.cancel()
    if not_done:
        raise RuntimeError(f"{len(not_done)}/{len(ordered_futures)} risk debate futures timed out")
    if not done:
        raise RuntimeError("All risk debate futures timed out")
    # Preserve original ordering (done is a set)
    results = []
    for future in ordered_futures:
        if future in done:
            try:
                results.append(future.result())
            except Exception:
                logger.exception("Parallel risk debater failed")
                raise
    merged = _merge_risk_debate_states(state, results)
    return {"risk_debate_state": merged}
```
4. Apply same pattern to `create_parallel_researcher_round1`.

**File:** `backend/main.py` — In teardown, call:
```python
from tradingagents.graph.parallel_debate import shutdown_debate_executor
shutdown_debate_executor()
```

**Test:** Run analysis, verify debate completes. Manually test timeout by mocking a hanging LLM.

### Task 1.6: Align Scanner Batch Size with Analysis Limit

**File:** `backend/services/scanner_service.py`

**Changes:** In `_run_scan()` (~line 594), cap batch_size to analysis limit:
```python
from backend.services.analysis_service import _MAX_CONCURRENT
batch_size = min(config_batch, _MAX_PARALLEL_CAP, _MAX_CONCURRENT)
```

**Test:** Run scan with batch_size=25, verify it's capped to MAX_CONCURRENT_ANALYSES.

---

## Phase 2: Async Database Migration (psycopg2 → asyncpg)

### Task 2.1: Add asyncpg Dependency

**File:** `pyproject.toml` or `requirements.txt`

Add `asyncpg>=0.29.0` to dependencies.

### Task 2.2: Create AsyncAnalysisDB Class

**File:** `backend/async_persistence.py` (new)

This is the largest single task. Create `AsyncAnalysisDB` with:

1. **Pool management:**
```python
class AsyncAnalysisDB:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._sync_pool: psycopg2.pool.ThreadedConnectionPool | None = None
        self._instance_id = str(uuid.uuid4())

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=int(os.environ.get("DB_POOL_MIN", "2")),
            max_size=int(os.environ.get("DB_POOL_MAX", "10")),
            command_timeout=int(os.environ.get("DB_COMMAND_TIMEOUT", "10")),
            max_inactive_connection_lifetime=300,
        )
        # Thin sync pool for in-thread callers (graph execution)
        # Size MUST match GRAPH_EXECUTOR_WORKERS to avoid pool exhaustion
        _sync_max = int(os.environ.get("DB_SYNC_POOL_MAX",
                        os.environ.get("GRAPH_EXECUTOR_WORKERS", "8")))
        self._sync_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=_sync_max, dsn=self._dsn, connect_timeout=10,
        )
        await self._apply_migrations()
```

2. **Transaction helper:**
```python
@asynccontextmanager
async def _transaction(self):
    async with self._pool.acquire() as conn:
        async with conn.transaction():
            yield conn
```

3. **Migration method** — use dedicated connection (not pool) for advisory lock:
```python
async def _apply_migrations(self):
    conn = await asyncpg.connect(dsn=self._dsn)
    try:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version ...")
        await conn.execute("SELECT pg_advisory_lock(8675309)")
        try:
            row = await conn.fetchrow("SELECT version FROM schema_version")
            current = row["version"] if row else 0
            # ... run each migration in a transaction ...
        finally:
            await conn.execute("SELECT pg_advisory_unlock(8675309)")
    finally:
        await conn.close()
```

4. **Convert all methods.** Group by pattern (counts are approximate — verify against actual file during implementation):

**Simple reads (32 methods):** `%s` → `$N`, `fetchone` → `fetchrow`, `fetchall` → `fetch`, wrap return in `dict()`.

Example conversion:
```python
# Before (psycopg2):
def get_run(self, run_id: str) -> Optional[Dict]:
    with self._get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM analysis_runs WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None

# After (asyncpg):
async def get_run(self, run_id: str) -> Optional[Dict]:
    row = await self._pool.fetchrow(
        "SELECT * FROM analysis_runs WHERE run_id = $1", run_id
    )
    return dict(row) if row else None
```

**Write methods (15 methods):** Use `pool.execute()` for single statements (auto-commits):
```python
async def insert_run(self, run: Dict[str, Any]) -> None:
    try:
        await self._pool.execute(
            "INSERT INTO analysis_runs "
            "(run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            run["run_id"], run["ticker"], run["analysis_date"], run["status"],
            run.get("config", "{}"), run["started_at"], self._instance_id,
            run.get("asset_type", "stock"),
        )
    except asyncpg.UniqueViolationError:
        raise ValueError(f"Run {run['run_id']} already exists")
```

**rowcount methods (24 methods):** Parse status string:
```python
async def update_run_status(self, run_id, status, error, completed_at) -> bool:
    result = await self._pool.execute(
        "UPDATE analysis_runs SET status=$1, error=$2, completed_at=$3 "
        "WHERE run_id=$4",
        status, error, completed_at, run_id,
    )
    return int(result.split()[-1]) > 0
```

**Dynamic SQL methods (11 methods):** Use counter-based placeholder:
```python
async def update_scan(self, scan_id: str, **updates) -> bool:
    if not updates:
        return False
    parts, vals = [], []
    for i, (k, v) in enumerate(updates.items(), 1):
        parts.append(f"{k} = ${i}")
        vals.append(v)
    vals.append(scan_id)
    result = await self._pool.execute(
        f"UPDATE scans SET {', '.join(parts)} WHERE scan_id = ${len(vals)}",
        *vals,
    )
    return int(result.split()[-1]) > 0
```

**Batch insert (1 method — insert_hf_snapshots):**
```python
async def insert_hf_snapshots(self, rows):
    async with self._transaction() as conn:
        await conn.executemany(
            "INSERT INTO hf_snapshots (account_id, ts, ...) VALUES ($1, $2, ...)",
            [(r["account_id"], r["ts"], ...) for r in rows],
        )
```

**INTERVAL methods:** Fix `%s * INTERVAL '1 day'` → `make_interval(days => $1)`.

**Sync bridge methods** (for graph executor thread callers):
```python
from contextlib import contextmanager

@contextmanager
def _get_sync_conn(self):
    """Context manager to safely acquire/release sync pool connections."""
    conn = self._sync_pool.getconn()
    try:
        yield conn
    finally:
        self._sync_pool.putconn(conn)

def sync_save_report_section(self, run_id: str, section: str, content: str) -> None:
    with self._get_sync_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO report_sections (run_id, section, content) VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
            (run_id, section, content),
        )
        conn.commit()
```

5. **Health check:**
```python
def is_healthy(self) -> bool:
    return self._pool is not None and not self._pool.is_closing()
```

6. **Close method:**
```python
async def close(self):
    if self._sync_pool:
        self._sync_pool.closeall()
    if self._pool:
        await self._pool.close()
```

### Task 2.3: Update main.py Lifespan

**File:** `backend/main.py`

**Changes:**
1. Replace `from backend.persistence import AnalysisDB` with `from backend.async_persistence import AsyncAnalysisDB`
2. In lifespan:
```python
db = AsyncAnalysisDB(dsn=dsn)
await db.connect()
try:
    await db.recover_orphans()
except Exception:
    await db.close()
    raise
```
3. In teardown — the FULL updated shutdown sequence after all phases:
```python
# Phase 4: Cancel watchdog first to avoid spurious stall warnings
_watchdog_task.cancel()

# Existing shutdown order (preserved):
await app.state.scheduler_service.shutdown()
if getattr(app.state, "rule_evaluator", None):
    await app.state.rule_evaluator.shutdown()
if app.state.snapshot_scheduler:
    await app.state.snapshot_scheduler.shutdown()
    await asyncio.sleep(0.5)
if app.state.account_ws_manager:
    await app.state.account_ws_manager.shutdown()
if app.state.accounts_service:
    await app.state.accounts_service.shutdown()
await app.state.scanner_service.shutdown()
await app.state.analysis_service.shutdown()  # Task 4.2: includes 30s drain + graph executor shutdown
await ws_manager.shutdown()

# Phase 1: Shut down executors
from tradingagents.graph.parallel_debate import shutdown_debate_executor
shutdown_debate_executor()
_default_executor.shutdown(wait=False, cancel_futures=True)

# Phase 2: Close async DB pool (MUST be await, not sync)
await db.close()  # Line 193 in current code — MUST change from db.close() to await db.close()
```

### Task 2.4: Migrate Router Call Sites

**Files:** All files in `backend/routers/`

**DB-direct calls** — replace `await asyncio.to_thread(request.app.state.db.method, args)` with `await request.app.state.db.method(args)`:
- `checkpoints.py` — 3 calls
- `ws.py` — 1 call (`db.get_run`)

**Service-wrapping calls** — these wrap sync service methods, NOT db methods directly. They become bugs only AFTER Task 2.5 makes those service methods async. Convert them in Task 2.5, not here:
- `accounts.py` — 4 calls (wrap accounts_service sync methods)
- `analytics.py` — 12 calls (wrap accounts_service sync methods)
- `strategies.py` — 7 calls (wrap strategy_service sync methods)
- `memory.py` — 1 call (wraps file I/O — keep as `to_thread`)

**DO NOT REMOVE these to_thread calls (they wrap non-DB blocking I/O):**
- `symbols.py` — 1 call (`get_valid_symbols` — blocking HTTP via `requests.Session`)
- `memory.py` — 1 call (sync file I/O)

**Routers with zero to_thread calls (no changes needed):**
- `analysis.py`, `scanner.py`, `close_positions.py`, `config.py`, `models.py`, `portfolio.py`, `scheduled_scans.py`, `ws_accounts.py`

**Verification after this task:**
```
grep -rn "asyncio.to_thread.*\.db\." backend/routers/
# Should return zero results
```

### Task 2.5: Migrate All Service Call Sites

**Files:** All files in `backend/services/`

This task has THREE sub-categories:

**A. Replace `asyncio.to_thread(self._db.method, args)` with `await self._db.method(args)`:**
- `scanner_service.py` — 24 DB sites (lines 355-867). PRESERVE 2 non-DB `to_thread` calls: line 456 (`get_valid_symbols`) and line 571 (`get_valid_symbols`)
- `analysis_service.py` — ~15 sites in async methods (lines 71, 126, 318, 331, 340, 355, etc.)
- `scan_scheduler_service.py` — 44 sites (including `shutdown()` at lines 210-213)
- `accounts_service.py` — 29 `to_thread` sites. PRESERVE: line 92 (`_build_client` closure — see below)
- `close_rule_evaluator.py` — 7 sites (preserve keyword arg signatures, e.g., `status="active"`)
- `close_positions_service.py` — 14 DB sites
- `account_ws_manager.py` — 2 DB sites (lines 26, 53). PRESERVE: line 59 (`_decrypt` — sync CPU work)
- `config_service.py`, `strategy_service.py`, `memory_service.py` — audit for any to_thread calls

**B. Convert sync service methods that call `self._db.*` directly (no `to_thread`) to async:**

`accounts_service.py` has 14+ sync public methods that call `self._db.*` directly without `to_thread`:
- `list_accounts` (L264) → `async def list_accounts`
- `get_account` (L267) → `async def get_account`
- `update_account` (L275/278) → `async def update_account`
- `get_snapshots` (L621) → `async def get_snapshots`
- `get_portfolio_snapshots` (L630) → `async def get_portfolio_snapshots`
- `get_hf_snapshots` (L701/708) → `async def get_hf_snapshots`
- `compute_analytics` (L744/750) → `async def compute_analytics`
- `compute_portfolio_analytics` (L863) → `async def compute_portfolio_analytics`
- `set_analytics_inclusion` (L1080-1084) → `async def set_analytics_inclusion`
- `cleanup_snapshot_data` (L1131) → `async def cleanup_snapshot_data`
- `count_snapshot_data` (L1149) → `async def count_snapshot_data`

After converting these, update ALL router call sites that wrap them in `to_thread`:
- `accounts.py` — 4 calls: remove `to_thread`, use `await svc.method()`
- `analytics.py` — 12 calls: remove `to_thread`, use `await svc.method()`
- `strategies.py` — 7 calls: remove `to_thread`, use `await svc.method()`

**C. Special case — sync callers in graph executor threads:**

These run in thread pool executors. They MUST use `db.sync_*()` bridge methods:
- `analysis_service._execute_graph` (line 541) — `db.sync_save_report_section()`
- `analysis_service._persist_signal_sections` (line 440) — `db.sync_save_report_section()`
- `analysis_service._save_snapshot` (lines 411-413) — OPTION A (preferred): convert `_save_snapshot` to `async def`, remove its `asyncio.to_thread` wrapper at lines 310 and 364, and `await` it directly. OPTION B: keep sync and use `db.sync_save_report_section()`.

Also update `psycopg2.pool.PoolError` catch in `_save_snapshot` (line 414) to `asyncpg.exceptions.InterfaceError` if using Option A.

**D. Special pattern — `_build_client` closure:**

`accounts_service.py` line 84-92 has a closure that calls `self._db.get_account_credentials()` inside `asyncio.to_thread(_create)`. Unwrap:
```python
# Before:
async def _build_client(self, account_id):
    def _create():
        creds = self._db.get_account_credentials(account_id)
        return BybitClient(...)
    return await asyncio.to_thread(_create)

# After:
async def _build_client(self, account_id):
    creds = await self._db.get_account_credentials(account_id)
    return BybitClient(...)
```

**Verification after this task:**
```
grep -rn "asyncio.to_thread.*self\._db" backend/services/
# Should return zero results EXCEPT _execute_graph sync bridge calls
grep -rn "asyncio.to_thread" backend/routers/
# Should return ONLY: symbols.py (get_valid_symbols), memory.py (file I/O)
```

### Task 2.6: Update Health Endpoint

**File:** `backend/main.py`

```python
@app.get("/api/v1/health")
async def health(request: Request):
    db = request.app.state.db
    db_ok = db.is_healthy()
    svc = request.app.state.analysis_service
    active = len([r for r in svc._active_runs.values() if r.get("status") == "running"])
    status = "ok"
    if not db_ok:
        status = "unhealthy"
    elif active > _MAX_CONCURRENT * 0.75:
        status = "degraded"
    return {
        "status": status,
        "db": "ok" if db_ok else "unavailable",
        "analyses_active": active,
        "analyses_max": svc.max_concurrent,
    }
```

Note: Import `_MAX_CONCURRENT` via a property on `AnalysisService`:
```python
@property
def max_concurrent(self) -> int:
    return _MAX_CONCURRENT
```

### Task 2.7: Remove Old persistence.py Import References

After all call sites are migrated, update any remaining imports of `AnalysisDB` from `backend.persistence`. Keep the old file for reference but it should no longer be imported.

**psycopg2 exception conversions required across the codebase:**

| psycopg2 Exception | asyncpg Equivalent | Locations |
|--------------------|--------------------|-----------|
| `psycopg2.IntegrityError` | `asyncpg.UniqueViolationError` | persistence.py:381 (insert_run), :419 (save_report_section), :1565 (insert_scheduled_scan) |
| `psycopg2.pool.PoolError` (raised) | Remove — asyncpg pool raises natively | persistence.py:279, :281 (in `_get_conn` — eliminated by asyncpg) |
| `psycopg2.pool.PoolError` (caught) | `asyncpg.InterfaceError` | analysis_service.py:414 (_save_snapshot) |
| `psycopg2.extras.RealDictCursor` | Remove — asyncpg `Record` supports `dict(row)` | ~25 cursor_factory sites |
| `psycopg2.extras.execute_batch` | `conn.executemany()` | persistence.py insert_hf_snapshots |

### Task 2.8: Convert strategy_service.py to Async

**File:** `backend/services/strategy_service.py`

All 6 public methods (`create_strategy`, `list_strategies`, `get_strategy`, `update_strategy`, `delete_strategy`, `import_strategies`) are sync and call `self._db.*` directly. Convert to `async def` with `await`:

```python
# Before:
def list_strategies(self):
    return self._db.list_strategies()

# After:
async def list_strategies(self):
    return await self._db.list_strategies()
```

Special attention:
- `update_strategy` L54,58: both internal `self.get_strategy()` calls must use `await`
- `import_strategies` L72: `self.create_strategy(s)` inside loop must use `await`

Then update `backend/routers/strategies.py` — replace all 7 `asyncio.to_thread(svc.method, ...)` with `await svc.method(...)`.

### Task 2.9: Update Test Files for asyncpg

**Files affected by migration:**
- `tests/backend/test_persistence.py` — replace `psycopg2.connect()` with `asyncpg.connect()`, update `_get_conn` usage, make tests async with `pytest-asyncio`
- `tests/backend/test_persistence_scanner.py` — same as above
- `tests/backend/test_analysis_service.py` — update `AnalysisDB` import to `AsyncAnalysisDB`, make sync DB calls async
- `tests/test_scanner_service_async.py` — remove `asyncio.to_thread` mocks, update inline `AnalysisDB` usage
- `tests/backend/test_config_service.py` — replace real `AnalysisDB` with `MagicMock` (ConfigService doesn't use DB)
- `tests/backend/test_main.py` — update `recover_orphans` patch to `AsyncMock`

---

## Phase 3: Rate Limiter Fixes

### Task 3.1: Cap CoinGecko Rate Limiter Sleep (FR-009)

**File:** `tradingagents/dataflows/coingecko_data.py`

**Changes:** In `_RateLimiter.wait()` (line 50-59):
```python
import random

def wait(self) -> None:
    while True:
        with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return
            sleep_for = min(60 - (now - self._timestamps[0]) + 0.1, 10.0)
            sleep_for += random.uniform(0, 0.5)  # jitter to avoid thundering herd
        logger.warning("CoinGecko rate limit: sleeping %.1fs", sleep_for)
        time.sleep(sleep_for)
```

### Task 3.2: Verify Debate Executor (FR-010)

Already done in Task 1.5. Verify it's working correctly.

---

## Phase 4: Health & Resilience

### Task 4.1: Event Loop Watchdog (FR-012)

**File:** `backend/main.py`

Add to lifespan startup:
```python
async def _event_loop_watchdog():
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(0.1)
        drift = loop.time() - start - 0.1
        if drift > 0.5:
            logger.warning("Event loop stall: %.0fms drift", drift * 1000)

_watchdog_task = asyncio.create_task(_event_loop_watchdog())
```

Cancel in teardown — MUST be FIRST, before any service shutdown:
```python
# First: stop watchdog to avoid spurious stall warnings during drain
_watchdog_task.cancel()
```

### Task 4.2: Graceful Shutdown Drain (FR-013)

**File:** `backend/services/analysis_service.py`

Enhance `shutdown()` — REPLACE the existing body (lines 112-123), not append:
```python
async def shutdown(self):
    self._shutting_down = True
    # Signal all runs to cancel via cancel_event
    async with self._lock:
        for rid, run in list(self._active_runs.items()):
            if run.get("cancel_event"):
                run["cancel_event"].set()

    # Drain: wait up to 30s for in-flight analyses to finish
    active = [r for r in self._active_runs.values() if r.get("status") == "running"]
    initial_active = len(active)
    if active:
        logger.info("Draining %d active analyses (30s deadline)...", initial_active)
        deadline = asyncio.get_running_loop().time() + 30
        while active and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            active = [r for r in self._active_runs.values() if r.get("status") == "running"]

    # Force-cancel anything still running after drain
    tasks_to_await = []
    async with self._lock:
        for rid, run in list(self._active_runs.items()):
            task = run.get("task")
            if task and not task.done():
                task.cancel()
                tasks_to_await.append(task)
    if tasks_to_await:
        await asyncio.gather(*tasks_to_await, return_exceptions=True)

    completed = initial_active - len(tasks_to_await)
    cancelled = len(tasks_to_await)
    logger.info("Shutdown complete: %d analyses completed, %d cancelled", completed, cancelled)

    # Shut down the graph executor
    _graph_executor.shutdown(wait=False, cancel_futures=True)
```

In `start_analysis()`, check `self._shutting_down` and raise 503.

---

## Validation Plan

After each phase:
1. Run existing test suite
2. Start the app, verify health endpoint responds
3. Start a scan with 8 parallel analyses
4. While scan runs, verify:
   - Health endpoint responds < 500ms
   - Scanner status endpoint responds
   - Account endpoints respond
   - WebSocket connections stay alive

## File Change Summary

| Phase | Files Modified | Files Created |
|-------|---------------|---------------|
| 1 | main.py, analysis_service.py, base_client.py, parallel_debate.py, scanner_service.py | — |
| 2 | main.py, all routers (14), all services (10) | async_persistence.py |
| 3 | coingecko_data.py | — |
| 4 | main.py, analysis_service.py | — |

**Total: ~30 files modified, 1 new file**
