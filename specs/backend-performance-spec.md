---
title: Backend Performance Overhaul — Specification
feature: backend-performance
version: 1.0
date: 2026-05-12
status: draft
---

# Backend Performance Overhaul — Specification

## 1. Problem Statement

When Market Scan runs 8+ parallel analyses, the entire FastAPI application becomes unresponsive. All endpoints — health checks, UI data, account queries — stop responding. Users must restart the application.

### Root Cause Analysis

The application runs in a single process with a single asyncio event loop. All heavy work (LangGraph agents, LLM calls, DB queries, external API calls) is offloaded to threads via `asyncio.to_thread()`. With 172+ call sites sharing the default executor (~8 threads), 8 parallel analyses saturate the thread pool, starving API request handling.

## 2. Goals

1. **API stays responsive** during 8+ parallel analyses (p99 < 500ms for non-scan endpoints)
2. **Health endpoint** responds within 200ms regardless of load
3. **No data loss** during migration from psycopg2 to asyncpg
4. **Backward-compatible** API — frontend works without changes

## 3. Non-Goals

- Microservices architecture
- Multi-user / multi-tenant support
- Prometheus / Grafana monitoring stack
- Zero-downtime deployment (single-user tool)
- ORM / repository layer abstraction

---

## 4. Functional Requirements

### Phase 1: Thread Pool & Concurrency Fixes (Immediate Impact)

#### FR-001: Explicit Default Executor Sizing

**File:** `backend/main.py` (lifespan function, ~line 91)

Set an explicit `ThreadPoolExecutor` as the default executor:
```python
import concurrent.futures
executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("THREADPOOL_MAX_WORKERS", "32"))
)
loop.set_default_executor(executor)
```

Shut it down in the lifespan teardown:
```python
executor.shutdown(wait=False, cancel_futures=True)
```

**Acceptance Criteria:**
- Default executor has configurable size (env: `THREADPOOL_MAX_WORKERS`, default: 32)
- Executor is properly shut down on app teardown
- All existing `asyncio.to_thread()` calls benefit without code changes

#### FR-002: Dedicated Executor for LangGraph Graph Execution

**File:** `backend/services/analysis_service.py` (~line 533 in `_execute_graph`)

Create a separate named executor for LangGraph work:
```python
_graph_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("GRAPH_EXECUTOR_WORKERS", "8")),
    thread_name_prefix="langgraph",
)
```

Use it in `_run_analysis()` (the async caller), NOT inside `_execute_graph` (which is sync):
```python
loop = asyncio.get_running_loop()
await asyncio.wait_for(
    loop.run_in_executor(_graph_executor, self._execute_graph, run_id, ...),
    timeout=_WALL_TIMEOUT,
)
```

**Acceptance Criteria:**
- LangGraph execution uses a dedicated executor, not the default
- Configurable via `GRAPH_EXECUTOR_WORKERS` (default: 8)
- Properly shut down on app teardown

#### FR-003: Reduce Max Concurrent Analyses

**File:** `backend/services/analysis_service.py` (line 28)

Change `_MAX_CONCURRENT = 25` to be configurable:
```python
_MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_ANALYSES", "8"))
```

**Acceptance Criteria:**
- Default reduced from 25 to 8
- Configurable via env var
- Requests exceeding limit get `ConcurrencyLimitError` (already mapped to 429)

#### FR-004: Fix LLM Spacing Race Condition

**File:** `tradingagents/llm_clients/base_client.py` (lines 59-74)

Current code (BROKEN — sleep outside lock allows race):
```python
with _llm_spacing_lock:
    _llm_last_request_ts = time.monotonic() + gap
if gap > 0:
    time.sleep(gap)  # Outside lock — RACE CONDITION
```

Fixed code (atomic timestamp reservation, sleep outside lock):
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
        time.sleep(gap)  # Outside lock — threads sleep concurrently
```

The key insight: update the timestamp inside the lock to "reserve a slot" in the future, then release the lock so other threads can reserve their own slots. Each thread sleeps independently without serializing.

**Acceptance Criteria:**
- Timestamp reservation is atomic (inside lock)
- Sleep is outside the lock (no serialization)
- No two threads can fire at the same instant

#### FR-005: Timeout on parallel_debate Futures

**File:** `tradingagents/graph/parallel_debate.py` (~lines 107, 128)

The `with ThreadPoolExecutor() as pool:` context manager calls `shutdown(wait=True)` on exit, which means `future.result()` is only reached after all futures are done — a timeout there is useless.

Fix: Remove the context manager, use `concurrent.futures.wait()` with timeout:
```python
executor = _debate_executor  # module-level, from FR-010
futures = [executor.submit(fn, args) for fn in debaters]
done, not_done = concurrent.futures.wait(futures, timeout=300)
for f in not_done:
    f.cancel()
    logger.warning("Debate future timed out for %s", ticker)
results = [f.result() for f in done]
```

**Acceptance Criteria:**
- `concurrent.futures.wait(futures, timeout=300)` enforces the deadline
- Timed-out futures are cancelled and logged
- Partial results are returned when one debater times out
- No `with ThreadPoolExecutor() as pool:` pattern (use shared executor from FR-010)

### Phase 2: Async Database Migration (psycopg2 → asyncpg)

**Critical Design Decision — Dual-Layer DB Access:**

The `_execute_graph()` method in `analysis_service.py` runs synchronously inside a thread (via the graph executor). It makes direct DB calls (e.g., `self._db.save_report_section()`). After migrating to asyncpg, these become coroutines — calling them from a sync thread will crash with `RuntimeError: no running event loop`.

**Solution: Keep a thin sync psycopg2 connection for in-thread writes.**

The `AsyncAnalysisDB` class will hold:
1. An asyncpg pool for all async callers (routers, services)
2. A single psycopg2 connection (or small pool of 2-3) exclusively for sync callers running inside thread executors (graph execution, callbacks)

This avoids the complexity of event-loop bridging while isolating the sync DB path to a minimal surface.

#### FR-006: Create AsyncDB Class with asyncpg

**File:** `backend/async_persistence.py` (new file)

Create `AsyncAnalysisDB` that mirrors all 50+ methods from `AnalysisDB` but uses asyncpg:

```python
import asyncpg

class AsyncAnalysisDB:
    def __init__(self, dsn: str, min_size=2, max_size=10, command_timeout=10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._command_timeout = command_timeout
        self._pool: asyncpg.Pool | None = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=int(os.environ.get("DB_POOL_MAX", str(self._max_size))),
            command_timeout=self._command_timeout,
            max_inactive_connection_lifetime=300,
        )
        await self._apply_migrations()

    async def close(self):
        if self._pool:
            await self._pool.close()
```

**Acceptance Criteria:**
- All methods from `AnalysisDB` have async equivalents
- Connection pool is created in lifespan startup, closed in teardown
- `command_timeout=10` prevents runaway queries
- psycopg2-style `%s` placeholders converted to asyncpg's `$1` positional style
- All existing data preserved (same schema, same queries)

**asyncpg Migration Hazards (must be addressed per-method):**

1. **Placeholder syntax**: `%s` → `$1, $2, ...` (numbered). Dynamic SQL builders that use `", ".join(["%s"] * N)` must use a counter: `", ".join(f"${i}" for i in range(1, N+1))`.
2. **Row access**: asyncpg returns `Record` objects, not dicts. Use `dict(row)` for dict conversion. All `cur.fetchone()` returns must be handled — asyncpg `fetchrow()` returns `Record|None`.
3. **rowcount**: psycopg2 `cur.rowcount` → asyncpg returns status string like `"UPDATE 3"`. Parse with `int(result.split()[-1])`.
4. **Transactions**: Use `async with conn.transaction():` for multi-statement operations. Single-statement `pool.execute()` auto-commits.
5. **Advisory locks in migrations**: Use a dedicated `asyncpg.connect()` (not pool) for the entire migration block so the advisory lock stays on the same backend connection.
6. **execute_batch**: Use `conn.executemany()` or `conn.copy_records_to_table()` for bulk inserts.
7. **INTERVAL arithmetic**: `$1 * INTERVAL '1 day'` fails — use `make_interval(days => $1)` or `$1::int * INTERVAL '1 day'`.
8. **BYTEA columns**: asyncpg returns `memoryview` for BYTEA — wrap with `bytes()` on reads.
9. **UUID columns**: asyncpg returns `asyncpg.pgproto.UUID` — `str(v)` works, but `isinstance(v, uuid.UUID)` fails. Register a codec or cast.
10. **Sync DB path**: Keep a thin psycopg2 `ThreadedConnectionPool(minconn=1, maxconn=3)` for sync callers in graph executor threads. Expose as `db.sync_*()` methods.

#### FR-007: Migrate All Call Sites from asyncio.to_thread(db.*) to await async_db.*

**Files (exhaustive list):**
- `backend/routers/*.py` — all routers
- `backend/services/scanner_service.py` — ~25 call sites (hot scan path, highest priority)
- `backend/services/analysis_service.py` — ~15 call sites
- `backend/services/scan_scheduler_service.py` — ~50 call sites (background loop)
- `backend/services/accounts_service.py` — ~23 call sites (includes `asyncio.gather` patterns)
- `backend/services/close_rule_evaluator.py` — ~7 call sites (background loop)
- `backend/services/close_positions_service.py` — ~16 call sites
- `backend/services/account_ws_manager.py` — startup DB call
- `backend/routers/ws.py` — WebSocket handler DB call

Replace every:
```python
result = await asyncio.to_thread(request.app.state.db.some_method, args)
```
With:
```python
result = await request.app.state.db.some_method(args)
```

**Special pattern — asyncio.gather:**
```python
# Before:
a, b = await asyncio.gather(
    asyncio.to_thread(db.method_a, x),
    asyncio.to_thread(db.method_b, y),
)
# After:
a, b = await asyncio.gather(db.method_a(x), db.method_b(y))
```

**Exception — sync callers in graph executor:**
Call sites inside `_execute_graph()` (runs in thread) must use `db.sync_save_report_section()` etc.

**Acceptance Criteria:**
- Zero `asyncio.to_thread()` calls remain for DB operations (except sync graph path)
- All routers and services use the async DB directly
- `threading.Semaphore` guard removed (asyncpg pool handles this natively)

#### FR-008: Migrate Lifespan to Async DB

**File:** `backend/main.py` (lifespan function)

Replace:
```python
db = AnalysisDB(dsn=dsn)
```
With:
```python
db = AsyncAnalysisDB(dsn=dsn)
await db.connect()
```

And in teardown:
```python
await db.close()
```

**Acceptance Criteria:**
- App starts with asyncpg pool
- Pool is properly closed on shutdown
- Migrations run at startup (async)

### Phase 3: Rate Limiter Fixes

#### FR-009: Non-Blocking CoinGecko Rate Limiter

**File:** `tradingagents/dataflows/coingecko_data.py` (lines 42-59)

The current `_RateLimiter.wait()` uses `time.sleep()` which blocks a thread for up to 60+ seconds. Since CoinGecko calls happen inside `asyncio.to_thread()` from the scan path, this wastes a thread pool slot.

Create an async version:
```python
class _AsyncRateLimiter:
    def __init__(self, max_per_min: int = 10):
        self._lock = asyncio.Lock()
        self._timestamps: list[float] = []
        self._max = max_per_min

    async def wait(self) -> None:
        while True:
            async with self._lock:
                now = time.time()
                self._timestamps = [t for t in self._timestamps if now - t < 60]
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                sleep_for = 60 - (now - self._timestamps[0]) + 0.1
            await asyncio.sleep(sleep_for)
```

**Note:** Since CoinGecko calls originate from LangGraph (synchronous), the async limiter needs to be called from the async layer _before_ dispatching to the thread pool, or the sync `requests.get()` calls need to be converted to `httpx.AsyncClient`. The simpler approach is to keep the sync rate limiter but reduce its maximum sleep to a reasonable bound (e.g., 10s) and add jitter.

**Pragmatic implementation:**
```python
def wait(self) -> None:
    while True:
        with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return
            sleep_for = min(60 - (now - self._timestamps[0]) + 0.1, 10.0)
        time.sleep(sleep_for)
```

Cap sleep at 10s max per iteration, add jitter, and log when rate-limited.

**Acceptance Criteria:**
- CoinGecko rate limiter never sleeps more than 10s per iteration
- Rate limit wait is logged at WARNING level
- Thread is not held for 60+ seconds

#### FR-010: Lifecycle-Managed Debate Executor

**File:** `tradingagents/graph/parallel_debate.py`

Replace per-invocation `ThreadPoolExecutor()` with a module-level managed executor:
```python
_debate_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("DEBATE_EXECUTOR_WORKERS", "4")),
    thread_name_prefix="debate",
)
```

**Acceptance Criteria:**
- Single executor instance per process lifetime
- Configurable via `DEBATE_EXECUTOR_WORKERS` (default: 4)
- Proper shutdown on app teardown

### Phase 4: Health & Resilience

#### FR-011: Non-Blocking Health Endpoint

**File:** `backend/main.py` (line 240-243)

Replace:
```python
@app.get("/api/v1/health")
async def health(request: Request):
    db_status = await asyncio.to_thread(request.app.state.db.health_check)
    return {"status": "ok", "db": db_status}
```

With (after asyncpg migration):
```python
@app.get("/api/v1/health")
async def health(request: Request):
    db = request.app.state.db
    pool = db._pool
    db_ok = pool is not None and not pool.is_closing()
    analysis_svc = request.app.state.analysis_service
    active = len([r for r in analysis_svc._active_runs.values() if r["status"] == "running"])
    max_cap = _MAX_CONCURRENT
    status = "ok" if db_ok else "unhealthy"
    if active > max_cap * 0.75:
        status = "degraded"
    return {
        "status": status,
        "db": "ok" if db_ok else "unavailable",
        "analyses_active": active,
        "analyses_max": max_cap,
    }
```

**Acceptance Criteria:**
- Health endpoint never acquires a DB connection
- Reports `degraded` when analysis load > 75%
- Responds within 200ms under any load

#### FR-012: Event Loop Watchdog

**File:** `backend/main.py` (lifespan startup)

```python
async def _event_loop_watchdog():
    while True:
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.1)
        drift = asyncio.get_event_loop().time() - start - 0.1
        if drift > 0.5:
            logger.warning("Event loop stall detected: %.1fms drift", drift * 1000)

watchdog_task = asyncio.create_task(_event_loop_watchdog())
```

Cancel in teardown.

**Acceptance Criteria:**
- Logs WARNING when event loop stalls > 500ms
- Does not impact performance (lightweight sleep check)
- Properly cancelled on shutdown

#### FR-013: Graceful Shutdown Drain

**File:** `backend/main.py` (lifespan teardown) and `backend/services/analysis_service.py`

Enhance shutdown to:
1. Stop accepting new analyses (set a flag)
2. Wait up to 30s for in-flight to complete
3. Cancel remaining futures
4. Log shutdown summary

**Acceptance Criteria:**
- New analysis requests during shutdown get 503
- In-flight analyses get 30s grace period
- After 30s, remaining are cancelled
- Log shows: "Shutdown complete: N analyses completed, M cancelled"

---

## 5. Migration Strategy

**Order of implementation (each phase is independently deployable):**

1. **Phase 1** — Thread pool fixes (FR-001 through FR-005): Immediate relief, no schema changes
2. **Phase 2** — asyncpg migration (FR-006 through FR-008): Biggest structural change
3. **Phase 3** — Rate limiter fixes (FR-009, FR-010): Independent improvements
4. **Phase 4** — Health & resilience (FR-011 through FR-013): Polish

**Database migration approach:**
- Same PostgreSQL, same schema, same data
- Only the driver changes (psycopg2 → asyncpg)
- Query syntax changes: `%s` → `$1`, `cur.execute()` → `pool.execute()`
- Brief restart required (acceptable for single-user tool)

## 6. Environment Variables (New)

| Variable | Default | Description |
|----------|---------|-------------|
| `THREADPOOL_MAX_WORKERS` | 32 | Default asyncio executor size |
| `GRAPH_EXECUTOR_WORKERS` | 8 | Dedicated LangGraph executor size |
| `DEBATE_EXECUTOR_WORKERS` | 4 | Debate round executor size |
| `MAX_CONCURRENT_ANALYSES` | 8 | Max simultaneous analyses |
| `DB_POOL_MAX` | 10 | asyncpg pool max connections |

## 7. Testing Strategy

- Unit tests for async DB methods (mock asyncpg pool)
- Integration test: start scan, verify health endpoint responds < 500ms
- Manual test: run 8 parallel analyses, verify UI remains responsive
- Verify all existing tests pass after migration

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| asyncpg query syntax bugs | Medium | High | Test every method individually |
| Thread pool too small | Low | Medium | Configurable via env var |
| CoinGecko rate limiter regression | Low | Low | Existing retry logic handles it |
| Shutdown race conditions | Low | Medium | Drain deadline + force cancel |
