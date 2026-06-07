# Phase P0 — Walking Skeleton

**Goal:** Prove the entire MCP spine end-to-end — DB → two-phase mount → core registry/dispatch/auth/audit → ONE read tool (`scans_list`) → control-plane toggle → in-memory ASGI test — with the app unchanged when MCP is OFF. No optimizer, no breadth. This phase gates all later phases.

**Entry criteria:** on `main`, clean tree, worktree created (Step 9). Baseline tests green.
**Exit criteria:** `initialize→tools/list→tools/call(scans_list)` green via in-memory ASGI client emitting exactly one audit row; OFF-path regression green (`/mcp/rpc`→503, no MCP task, <50 ms startup delta); `app.state.mcp_server is None` when init forced to raise and app still starts; multi-worker leader guard tested.

**Requirements covered:** FR-001..006, FR-026/027/032/034, FR-011(scans_list only), NFR-007/009/010/011, AC-001/002/012/013/015.

---

## I. Database/Migration Plan (TASK-P0-01)

**File:** `backend/async_persistence.py` — append to `_MIGRATIONS` list (after `(42, ...)`).

**TASK-P0-01a — Migration v43 (callable, all 6 tables in one txn).**
Add `_migrate_mcp_v43(conn)` and the tuple `(43, _migrate_mcp_v43)`. The callable executes (in order, all `IF NOT EXISTS`):

```python
async def _migrate_mcp_v43(conn: asyncpg.Connection) -> None:
    # 1. mcp_config singleton
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_config (
            id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            enabled BOOLEAN NOT NULL DEFAULT false,
            bind_host TEXT NOT NULL DEFAULT '127.0.0.1',
            access_token_hash TEXT,
            capability_tier TEXT NOT NULL DEFAULT 'READ_ONLY'
                CHECK (capability_tier IN ('READ_ONLY','BACKTEST','MUTATING_DEMO','LIVE_MONEY')),
            enabled_groups JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(enabled_groups)='array'),
            enabled_tools JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(enabled_tools)='object'),
            safe_mode_flags JSONB NOT NULL
                DEFAULT '{"read_only":true,"allow_real_trades":false,"allow_debug":false}'
                CHECK (jsonb_typeof(safe_mode_flags)='object'),
            config_schema_version INT NOT NULL DEFAULT 1,
            row_version BIGINT NOT NULL DEFAULT 0,
            config_epoch BIGINT NOT NULL DEFAULT 0,
            kill_epoch BIGINT NOT NULL DEFAULT 0,
            installation_id UUID NOT NULL DEFAULT gen_random_uuid(),
            leader_host TEXT,
            leader_pid INT,
            heartbeat_at TIMESTAMPTZ,
            audit_retention_days INT NOT NULL DEFAULT 365 CHECK (audit_retention_days BETWEEN 1 AND 3650),
            sweep_retention_days INT NOT NULL DEFAULT 90 CHECK (sweep_retention_days BETWEEN 1 AND 3650),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    await conn.execute("INSERT INTO mcp_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # 2. mcp_sweep_jobs
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_sweep_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','completed','cancelled','failed','interrupted')),
            strategy TEXT,
            param_space JSONB NOT NULL,
            objective_metric TEXT NOT NULL,
            total_combos INT NOT NULL CHECK (total_combos > 0),
            completed_combos INT NOT NULL DEFAULT 0 CHECK (completed_combos <= total_combos),
            best_result_id UUID,
            idempotency_key TEXT,
            principal_token_id TEXT,
            session_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            CHECK (completed_at IS NULL OR completed_at >= started_at)
        )""")
    await conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_sweep_idem
        ON mcp_sweep_jobs (principal_token_id, session_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL""")
    await conn.execute("""CREATE INDEX IF NOT EXISTS idx_mcp_sweep_jobs_status
        ON mcp_sweep_jobs (status) WHERE status IN ('queued','running')""")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_sweep_jobs_created ON mcp_sweep_jobs (created_at)")
    # 3. mcp_sweep_results
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_sweep_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sweep_id UUID NOT NULL REFERENCES mcp_sweep_jobs(id) ON DELETE CASCADE,
            config JSONB NOT NULL,
            config_hash CHAR(64) NOT NULL,
            backtest_id UUID,
            metrics JSONB NOT NULL,
            objective_value NUMERIC(20,8),
            result_rank INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (sweep_id, config_hash)
        )""")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_sweep_results_rank ON mcp_sweep_results (sweep_id, result_rank)")
    # 3b. circular FK added by ALTER (cannot be inline; guard idempotently)
    await conn.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_mcp_best_result') THEN
            ALTER TABLE mcp_sweep_jobs ADD CONSTRAINT fk_mcp_best_result
                FOREIGN KEY (best_result_id) REFERENCES mcp_sweep_results(id)
                ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
        END IF; END $$""")
    # 4. mcp_audit_log
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_audit_log (
            id BIGSERIAL PRIMARY KEY,
            seq BIGINT NOT NULL UNIQUE,
            prev_hash TEXT,
            entry_hash TEXT NOT NULL,
            tool_name TEXT,
            tool_group TEXT,
            safety_class TEXT,
            mutating BOOLEAN NOT NULL DEFAULT false,
            principal_token_id TEXT,
            session_id TEXT,
            correlation_id UUID,
            args_redacted JSONB,
            sensitive_payload BYTEA,
            status TEXT NOT NULL CHECK (status IN ('ok','error','rejected','rate_limited','timeout','interrupted')),
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            duration_ms INT CHECK (duration_ms >= 0)
        )""")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_audit_started ON mcp_audit_log (started_at DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_audit_session ON mcp_audit_log (session_id, started_at DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_audit_tool ON mcp_audit_log (tool_name, tool_group, status)")
    # 5. mcp_proposals
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sweep_id UUID REFERENCES mcp_sweep_jobs(id) ON DELETE SET NULL,
            target_schedule_id TEXT,
            target_config_index INT,
            config JSONB NOT NULL,
            diff JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected','expired','applied','reverted')),
            approver TEXT,
            applied_config_version TEXT,
            risk_verdict JSONB,
            config_schema_version INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )""")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_proposals_status ON mcp_proposals (status, created_at DESC)")
    # 6. mcp_tokens (modeled, empty in MVP)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT, token_hash TEXT NOT NULL, scope JSONB, principal TEXT,
            expires_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
```
- `target_schedule_id` FK to `scheduled_scans(id)` is added only if `scheduled_scans` exists at v43 time (it does — created earlier); add as `ON DELETE SET NULL` via the same guarded `DO $$` pattern if a hard FK is desired, else keep it a plain TEXT with app-level validation (chosen: plain TEXT + app validation, to avoid migration-order coupling).

**TASK-P0-01b — Migration v44 (additive `backtest_runs`).**
`(44, "ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'ui'; ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS sweep_id UUID; CREATE INDEX IF NOT EXISTS idx_backtest_runs_source ON backtest_runs (source) WHERE source <> 'ui'")` — plain string migration (no `;`-in-body hazard; the runner splits on `;` and runs each).

**Tests (TASK-P0-01):** `tests/backend/mcp/test_migrations.py`
- `test_v43_creates_six_tables` — apply migrations on a temp DB, assert all 6 `mcp_*` tables exist + the singleton row (`enabled=false`).
- `test_v43_reapply_idempotent` — running the callable twice doesn't error (IF NOT EXISTS + guarded FK).
- `test_v43_atomic_rollback` — inject a failure mid-callable (monkeypatch one execute to raise), assert zero `mcp_*` objects remain (per-version transaction).
- `test_v44_additive_columns` — `backtest_runs.source` defaults `'ui'`, `sweep_id` nullable.
- `test_singleton_fail_safe_defaults` — `safe_mode_flags` = `{read_only:true, allow_real_trades:false, allow_debug:false}`.
- `test_migration_version_contiguity` — assert `_MIGRATIONS` versions are contiguous 1..44, unique (the CI contiguity gate).

---

## K. Backend Implementation Plan

### TASK-P0-02 — Repositories base (`backend/mcp/repositories/`)
**Files:** `config_repo.py`, `audit_repo.py` (sweep/proposal repos stubbed in P0, filled P4).
- `MCPConfigRepository(pool: asyncpg.Pool)`:
  - `async def get(self) -> MCPConfig` — `SELECT * FROM mcp_config WHERE id=1`; on missing row return fail-safe defaults (enabled=false). Boot-repair: if `safe_mode_flags` NULL/missing keys → coerce to fail-safe + force `enabled=false` (FR R-308/513).
  - `async def update(self, patch: dict, *, expected_row_version: int) -> MCPConfig` — single UPSERT `UPDATE mcp_config SET <fields>, row_version=row_version+1, config_epoch=config_epoch+1, updated_at=now() WHERE id=1 AND row_version=$expected RETURNING *`; raise `MCPConflictError` if 0 rows (optimistic-concurrency, FR R-260/447).
  - `async def bump_kill_epoch(self) -> int` — `UPDATE … SET kill_epoch=kill_epoch+1, enabled=false … RETURNING kill_epoch` (kill-switch).
  - `async def set_token_hash(self, token_hash: str) -> None`.
- `AuditRepository(pool)`:
  - `async def reserve(self) -> tuple[int, uuid.UUID]` — returns `(seq, correlation_id)`; `seq` reserved by the single writer (see TASK-P0-08), NOT here.
  - `async def append(self, record: AuditRecord) -> None` — INSERT one row with computed `seq`/`prev_hash`/`entry_hash`.
  - `async def last_chain(self) -> tuple[int, str | None]` — `SELECT seq, entry_hash FROM mcp_audit_log ORDER BY seq DESC LIMIT 1` (chain continuation on boot).
  - `async def recover_dangling(self) -> int` — on boot, stamp any begin-without-end as `status='interrupted', duration_ms=NULL` (gap-recovery contract, AC-021).
- **Pattern:** mirror `debug_trace_repository.py`; all SQL here, no asyncpg elsewhere; every acquire goes through the MCP DB semaphore (TASK-P0-12).
- **Tests:** `test_config_repo.py` (get/update optimistic-concurrency conflict, boot-repair, kill_epoch bump), `test_audit_repo.py` (append chain continuity, recover_dangling).

### TASK-P0-03 — Two-phase mount seam (`backend/mcp/mount.py` + `backend/main.py`)
- `def register_mcp(app: FastAPI) -> None` — called in `create_app()` body AFTER existing `include_router` calls:
  - `app.state.mcp_asgi = _gate_503_app` (a tiny ASGI app returning `503 {"detail":"feature disabled","code":"MCP_DISABLED"}` for http; no-ops/acks `lifespan`).
  - `app.mount("/mcp/rpc", _Indirection(app))` where `_Indirection.__call__` dispatches `scope["type"] in ("http","websocket")` to `app.state.mcp_asgi`, and ACKs `lifespan` itself (no downstream forward).
  - `app.include_router(mcp_control_router, prefix="/api/v1")` (control-plane).
- `async def mcp_boot(app: FastAPI) -> None` — called in `lifespan` AFTER migrations + `recover_stale_runs` + `resume_incomplete_scans`:
  - acquire the leader advisory lock on a dedicated connection (TASK-P0-11); if not leader → `app.state.mcp_server=None`, return.
  - read `mcp_config`; run `AuditRepository.recover_dangling()` + sweep boot-recovery (P4).
  - if `enabled` and preflight passes (TASK-P0-10) → build the FastMCP app (TASK-P0-05) + start its session manager + `app.state.mcp_asgi = <fastmcp_asgi>`; else leave the 503 gate.
  - wrap in `try/except` → on failure `app.state.mcp_server=None`, log `mcp_boot_failed`, NEVER raise (FR-005/NFR-007).
- **`backend/main.py` edits (exactly two):** (1) in `create_app()` body: `from backend.mcp.mount import register_mcp; register_mcp(app)` (after the router includes, ~line 600). (2) in `lifespan`, AFTER `scheduler_service.start()` (~line 275, so the leader guard + sweep boot-recovery run after the scheduler is up — codebase-verified C-F10): `from backend.mcp.mount import mcp_boot; await mcp_boot(app)`. Shutdown: `if getattr(app.state,'mcp_server',None): await _safe_shutdown("mcp_server", app.state.mcp_server.shutdown())`.
- **Tests:** `test_mount.py` — `register_mcp` adds the mount + control router, reads no DB, opens no connection (assert via a spy pool); startup-order test asserts `mcp_boot` runs after scanner-resume.

### TASK-P0-04 — Core tool registry (`backend/mcp/core/registry.py`)
- `class ToolGroup(StrEnum)`: `SCANS, ACCOUNTS, POSITIONS, TRADES, PORTFOLIO, ANALYTICS, SCHEDULED, STRATEGIES, SYMBOLS, BACKTEST, DEBUG, OPTIMIZER, ADVANCED` (append-only).
- `class SafetyClass(StrEnum)`: `READ_ONLY, BACKTEST, LIVE_MONEY`.
- `@dataclass(frozen=True) class ToolSpec`: `name, group, handler, input_schema, output_schema, safety_class, mutating, exchange_facing, description`.
- `_REGISTRY: dict[str, ToolSpec] = {}`.
- `def tool(*, name, group, input_schema, output_schema, safety_class, mutating=False, exchange_facing=False)` decorator → validates name matches `^[a-z]+_[a-z_]+$`, unique, captures the handler's docstring as `ToolSpec.description` (required — completeness test fails if empty), registers, returns the handler unchanged. (This keyword-only form is canonical; the summary §F is aligned to it.)
- `def discover_tools() -> None` — import-scan `backend/mcp/tools/**` so decorators run (called once in `mcp_boot`).
- `def resolve_enabled(config: MCPConfig) -> list[ToolSpec]` — filter `_REGISTRY` by `enabled_groups`/`enabled_tools` (most-restrictive) AND `tier_allows(spec.safety_class, config.capability_tier)` AND backing service not None.
- **Tier ordering map (`core/registry.py`):** `_TIER_RANK = {READ_ONLY:0, BACKTEST:1, MUTATING_DEMO:2, LIVE_MONEY:3}`; `SafetyClass` maps to a minimum tier: `READ_ONLY→READ_ONLY, BACKTEST→BACKTEST, LIVE_MONEY→LIVE_MONEY` (no SafetyClass maps to MUTATING_DEMO — that tier exists for future demo-trade tools). `tier_allows(sc, tier) = _TIER_RANK[min_tier_for(sc)] <= _TIER_RANK[tier]`. Used by dispatch tier-gate (TASK-P0-06).
- **`BacktestRunner` Protocol home (P-F3 fix):** declared in **`backend/mcp/core/runner.py`** (P0-owned, trading-free interface only): `class BacktestRunner(Protocol): async def run_one(self, config, signals, snapshot, instrument_info, *, deadline) -> dict[str, Any]: ...`. P3 makes `BacktestService` satisfy it; P4's `tools/optimizer/runner.py` imports the Protocol from `core/runner.py`. `FakeBacktestRunner` (conftest) implements it.
- `PRESETS: dict[str, Callable[[ToolSpec], bool]]` — predicates: `minimal = lambda t: t.safety_class==READ_ONLY and t.group in CORE_READ_GROUPS`, `backtest_only`, `read_only`, `standard`, `full` (R-381).
- **Registration-time deny-list** `_DENY_METHODS` (config/token/kill/audit writers + `update_scheduled_scan`/`create_scheduled_scan` + `apply_auto_trade_config_atomic` (the P4 apply writer — arch-R1-F3) + exchange order/leverage) — a build-time test asserts no `ToolSpec.handler` call-graph reaches them (TASK-P0-04 test + P4 call-graph test with a negative control).
- **`core/shape.py` + `core/redact.py` are explicit P0 deliverables** (minimal: shape = summary projection + keyset cursor; redact = pass-through stub) so the P0 `scans_list` slice is self-contained; both finalized in P1 (arch-R1-F11).
- **Tests:** `test_registry.py` — register/resolve (group+individual most-restrictive), preset predicates, name-regex reject, duplicate reject; `test_registry_completeness.py` (parametrized over `_REGISTRY`): each tool has schema+handler+valid safety_class+description, and (added per phase) an error-map entry + audit emission.

### TASK-P0-05 — Transport (`backend/mcp/core/transport.py`)
- `class MCPServer`: wraps a FastMCP instance built from `resolve_enabled(config)`; exposes `.asgi_app`, `.start()` (start session manager task group), `.shutdown()` (drain+stop), `.rebuild(config)` (atomic: build new → swap `app.state.mcp_asgi` → drain old; for master enable/disable only — tool toggles use registry filtering, ADR-7).
- `initialize` response: `serverInfo={name:"tradingagents-mcp", version:<app_ver>}`, `protocolVersion` negotiated within floor `2025-03-26` .. ceiling `2025-06-18`, `capabilities={tools:{listChanged:true}, resources:{subscribe:false}, prompts:{}}`, `instructions=<steer to optimize_config/sweep_run>`.
- Host/Origin allowlist + `MCP-Protocol-Version` lenient handling at the transport edge (TASK-P0-09).
- **Tests:** `test_transport.py` (in-memory ASGI): `initialize` returns the contract; `capabilities ⊆ implemented` (init-contract test).

### TASK-P0-06 — Dispatch pipeline (`backend/mcp/core/dispatch.py`)
- `async def dispatch(call: ToolCall, ctx: CallContext) -> ToolResult` applies, in order: Host/Origin (transport-level, asserted) → auth (TASK-P0-07) → rate-limit (token bucket, P2+) → tier-gate (`spec.safety_class ≤ ctx.tier` else `-32601`/denied) → kill_epoch-fence capture (re-checked at the rate-gate chokepoint for exchange_facing, P3) → audit-begin (`ctx.correlation_id`) → `asyncio.wait_for(handler(args, ctx), spec.timeout)` → audit-end (status/duration) → error-map → shape/redact.
- `CallContext` dataclass: `principal: str, session_id: str, tier: str, correlation_id: UUID, services: ServiceAccessors, clock: Clock`.
- Catch-all: any unmapped exception → generic internal-error `isError` envelope (logged w/ correlation_id), never crash the session (FR R-265).
- **Tests:** `test_dispatch.py` — disabled tool → `-32601`; handler raises domain exc → mapped `isError`; handler raises unknown → generic internal-error + audit row with `status='error'`; tier-gate denies an over-tier tool.

### TASK-P0-07 — Auth (`backend/mcp/core/auth.py`)
- `class TokenAuthenticator(Protocol)`: `async def authenticate(self, headers) -> Principal | None`.
- `class BearerAuthenticator`: extract `Authorization: Bearer <t>`; `hmac.compare_digest(sha256(t), stored_hash)` (constant-time, structurally tested); None → 401. Token never logged.
- `def generate_token() -> tuple[str, str]` — CSPRNG `secrets.token_urlsafe(32)` (≥256-bit) → `(plaintext, sha256_hash)`.
- **Tests:** `test_auth.py` — valid/invalid/missing/malformed token; assert `hmac.compare_digest` is the code path (structural); token never appears in logs (canary).

### TASK-P0-08 — Audit writer (`backend/mcp/core/audit.py`)
- `class AuditWriter`: a single serialized consumer task draining an `asyncio.Queue`; assigns `seq=last+1`, `prev_hash`, `entry_hash=sha256(canonical_plaintext(prev_hash, record))` (hash over PLAINTEXT pre-encryption); writes via `AuditRepository.append`. Non-blocking: `enqueue()` returns immediately; on queue-full → synchronous fallback through the SAME writer lock (never a direct write). Flush-on-shutdown.
- Secret scrub: `args_redacted = mask_secrets(strip_credential_keys(args))`; sensitive fields (account ids/amounts) → `sensitive_payload` (Fernet via `ACCOUNTS_ENCRYPTION_KEY`).
- **Tests:** `test_audit.py` — chain continuity across interleaved appends; tamper a row → `verify_chain()` detects; queue-full sync fallback still serializes; `audit_completeness==1.0` (every begin has a terminal status incl. interrupted).

### TASK-P0-09 — Host/Origin allowlist (`backend/mcp/core/transport.py`)
- Reject if `Host` not in `{127.0.0.1:<port>, localhost:<port>, [::1]:<port>}`; reject if `Origin` present AND not loopback (absent Origin allowed for local bridges).
- **Tests:** `test_security_net.py` — forged Host rejected; non-loopback Origin rejected; absent Origin allowed (DNS-rebind, AC-013).

### TASK-P0-10 — Enable preflight (`backend/mcp/core/preflight.py`)
- `async def preflight(app) -> PreflightResult` checks (UNCONDITIONAL): token set+strong; bind loopback; `safe_mode_flags.read_only`; zero mutating/live tools enabled; migrations at expected version (44); single-worker-or-leader; DB-pool/`max_connections` budget. **Conditional on the OPTIMIZER group being enabled (backend-R1-F6/arch-F9):** shm free-space ≥ snapshot budget; breaker-input live-SLIs present. In P0–P3 (no sweep) these two are no-ops/stubs, activated in P4 — so MCP is enableable per phase. `PreflightResult` returns pass/fail + the failed-invariant NAME (surfaced in the enable response — AC-002).
- Dry-connect self-test: loop an in-process MCP client → `initialize→tools/list→one read tool`; assert auth enforced + only read-only advertised.
- **Tests:** `test_preflight.py` — each invariant failure keeps OFF AND the response names the failed invariant (AC-002); dry-connect failure auto-reverts.

### TASK-P0-14 — Import-linter boundary contracts (`.importlinter` + CI) (arch-R1-F1/F4)
- Define import-linter contracts: (a) `backend.mcp.core` may NOT import `backend.mcp.tools|resources|prompts`; (b) nothing outside `backend.mcp` imports `backend.mcp` EXCEPT `backend.main` (the single seam); (c) `backend.mcp.core` imports no trading module (`backend.services.*`, `tradingagents.*`); (d) `backend.schemas` does NOT import `backend.mcp` (removability — control-plane Pydantic models live IN-package, re-export is one-way mcp→schemas only via duplication, never schemas→mcp).
- Add `import-linter` to dev deps; wire `lint-imports` into CI.
- **Tests:** the contracts run in CI; a deliberate violating import makes `lint-imports` fail (negative control).

### TASK-P0-11 — Leader election (`backend/mcp/core/leader.py`)
- `async def acquire_leader(dsn) -> asyncpg.Connection | None` — open a DEDICATED connection (not pooled), `SELECT pg_try_advisory_lock(<MCP_LOCK_KEY=8675310>)`; on True hold it for the worker's lifetime + run a liveness loop re-asserting + writing `heartbeat_at` to `mcp_config`; on False return None (degrade). Reconnect+retry with backoff on drop.
- **Tests:** `test_leader.py` — two acquirers → exactly one leader; lock survives a simulated >300 s idle (dedicated conn, not recycled); on close another acquires.

### TASK-P0-12 — DB semaphore + control-plane router (`backend/mcp/core/db_gate.py`, `backend/mcp/router.py`)
- DB semaphore is **lazy-initialized in `mcp_boot`** from the actual pool's max size (stored on `app.state.mcp_db_sem` — NOT a module-global, since `pool_max` isn't known at import — backend-R1-F10): `app.state.mcp_db_sem = asyncio.Semaphore(pool_max - live_floor)`. Every MCP/repo acquire wraps `async with app.state.mcp_db_sem: async with pool.acquire() as c:` (brackets the FULL hold).
- Control-plane `router.py` (P0 endpoints): `GET/PATCH /api/v1/mcp/config`, `POST /enable` (preflight-gated), `POST /disable?kill=`, `GET /status` (200/503; payload includes `running/leader/leader_host/sessions/last_error/pending_proposals`), `GET /mcp/health` (200 when OFF; includes `pending_proposals`), `GET /tools` (P0 ships a MINIMAL stub returning enabled names; P2 TASK-P2-07 enriches it with full registry + est_tokens + presets — single owner = P2 for the rich form), `GET /audit` (keyset activity feed — created here in P0 so P2's Activity section has its data source), `POST /token/regenerate`, `POST /test-connection` (in-process). `pending_proposals` = `SELECT count(*) FROM mcp_proposals WHERE status='pending'`. Availability gate: 503 when `app.state.mcp_server is None` AND module absent; 200 `{state:"off"}` when present-but-disabled.
- **Tests:** `test_control_plane.py` — config get/patch (optimistic-concurrency), enable preflight, disable+kill, status 503-vs-200-off, OFF-path zero MCP control calls from nav.

### TASK-P0-13 — `scans_list` read tool (`backend/mcp/tools/scans/list_scans.py`)
- `@tool(name="scans_list", group=SCANS, input_schema=ScansListIn, output_schema=ScansListOut, safety_class=READ_ONLY, mutating=False)`; handler calls a NEW side-effect-free repo read (list recent scans, paginated, summary projection); never re-runs a scan.
- **Tests:** `test_scans_list.py` — returns stored scans (no scanner invocation, asserted via spy); pagination; redaction.

---

## L. Security Implementation Plan (P0)
- Bearer auth (TASK-P0-07), Host/Origin allowlist (TASK-P0-09), constant-time compare, token-never-logged canary, audit hash-chain + scrub (TASK-P0-08), deny-list registration check (TASK-P0-04), 503 gate zero-surface OFF, fail-closed preflight (TASK-P0-10).
- **Security tests (P0):** DNS-rebind (AC-013), auth 401 (FR-026), token-leak canary, registration deny-list build-fail.

## M. Testing Plan (P0)
- Unit: registry, dispatch, auth, audit, config-repo, preflight, leader. Integration (in-memory ASGI): `initialize→tools/list→tools/call(scans_list)` emitting one audit row. Regression: OFF-path zero-overhead (`/mcp/rpc`→503, no MCP task, <50 ms startup delta, existing suite unchanged); core-trading isolation (force `mcp_boot` to raise → app starts, `mcp_server is None`). Migration: v43/v44 (TASK-P0-01).
- **conftest.py seams:** in-memory ASGI client helper, `FakeClock`, temp-DB fixture, spy pool.

## N. Manual Verification (P0)
1. Start app (MCP OFF default) → `/mcp/rpc` returns 503; `/api/v1/mcp/health` returns 200 `{state:"off"}`.
2. `PATCH /api/v1/mcp/config` to set a token + enable → preflight runs → status flips ON.
3. Connect an in-memory client → `tools/list` shows only `scans_list` → `tools/call` returns scans → one audit row in `mcp_audit_log`.
4. `POST /disable?kill=true` → `/mcp/rpc` returns 503 again; sessions dropped.

## O. Completion Criteria (P0)
All TASK-P0-* tests green; OFF-path regression green; existing backend suite unchanged; `cd frontend && npx tsc --noEmit` unaffected. Commit `feat(mcp): P0 walking skeleton (mount, registry, dispatch, auth, audit, scans_list)`.