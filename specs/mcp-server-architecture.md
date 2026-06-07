# Architecture: MCP Server (AI Agent Integration)

**Requirements:** `specs/mcp-server-requirements.md` (586 requirements, C1–C20 resolved)
**Status:** SPEC-READY — 5 architecture review rounds; both final reviewers converged ("Security: money-path & secret-path provably closed"; "Architecture spec-ready"). §14/§15 (review revisions) SUPERSEDE earlier sections where marked.
**Scope note:** This document defines the architecture for the **MVP (Phases P0–P4)** with explicit seams for the deferred phases (P5–P6 per R-393..399). It RESOLVES the load-bearing decisions and gives every requirement an architectural home.

---

## 1. Architecture Decision Record (ADR)

### ADR-1 — Embedded FastMCP sub-app on the existing FastAPI process
- **Decision:** Mount the MCP server as an ASGI sub-app on the existing FastAPI app (`backend/main.py:create_app()`), using the official `mcp` Python SDK's **FastMCP** with the **streamable-HTTP** transport. (R-58, R-575)
- **Context:** MCP tools must call in-process services (`BacktestService`, accounts/positions/scanner repositories, `bybit_rate_gate`) with zero IPC. The app is a single FastAPI process with services wired onto `app.state.*`.
- **Alternatives rejected:**
  - *Standalone stdio process* — full isolation but loses in-process service access; forces localhost HTTP loopback + duplicated config/DB wiring. Kept only as a documented fallback (R-60).
  - *Legacy HTTP+SSE transport* — weaker session/resumption semantics; SDK default is streamable-HTTP (R-59).
  - *Real HTTP to localhost* — network round-trips, re-implements CSRF/auth per call (R-65).
- **Consequences:** MCP lifecycle is coupled to the trading app's; mitigated by failure isolation (degrade to `None`, never abort startup — R-84) and hard resource priority for live trading (R-292/548). Single-process correctness requires a multi-worker guard (ADR-9).

### ADR-2 — In-process service-layer call path (no ASGI loopback for the default)
- **Decision:** MCP tool handlers invoke app services directly (in-process), reusing the services' Pydantic validation; CSRF/CORS do not apply in-process and are replaced by MCP-layer bearer auth + safe-mode gating. (R-63, R-66)
- **Alternatives rejected:** ASGI loopback via httpx (double validation, 1 MB cap applies — R-64); real HTTP (R-65).
- **Consequences:** Mutating tools must re-run the same validators the routers use (R-539); a registration-time deny-list prevents wrapping sensitive methods (R-288).

### ADR-3 — Transport mounted at `/mcp/rpc`; control-plane at `/api/v1/mcp/*`; SPA page at `/mcp`
- **Decision:** Three distinct surfaces (resolves **C11**):
  - **Data-plane** (JSON-RPC, bearer-auth, agent-facing): mounted at **`/mcp/rpc`**, `include_in_schema=False`, CSRF-exempt for that exact subtree only (R-61/236/233).
  - **Control-plane** (config/status/audit-read/proposal-approval, same-origin browser API, existing app auth): a normal FastAPI router at **`/api/v1/mcp/*`** (R-386).
  - **Operator UI page**: the SPA route **`/mcp`** (R-134) — served by the frontend, distinct path from the transport.
- **Context:** R-134 (SPA `/mcp`) and R-58/61 (transport `/mcp`) collided (C11). Separating the transport prefix removes the collision and scopes the CSRF exemption tightly.
- **Consequences:** The browser only ever talks to `/api/v1/mcp/*` (R-410); the "test connection" button hits a control-plane proxy, never `/mcp/rpc` (R-557).

### ADR-4 — OFF = transport unmounted + a tiny always-mounted 503 gate (resolves C1)
- **Decision:** When `enabled=false`, the full JSON-RPC transport (sessions, dispatch, handlers) is **not mounted** (zero attack surface — R-37); a tiny always-present gate route at the transport prefix returns **503 "feature disabled"** (R-36). All references pinned to **503** (resolves C1, C20). (R-43/362 → 503 only.)
- **Consequences:** Enable/disable mounts/unmounts the transport at runtime via atomic rebuild-and-swap (ADR-7).

### ADR-5 — Capability tier is the single authoritative ceiling (resolves C10)
- **Decision:** Collapse the four overlapping gating concepts into ONE model:
  - **Capability tier** (`READ_ONLY` → `BACKTEST` → `MUTATING_DEMO` → `LIVE_MONEY`) is the authoritative ceiling, enforced server-side per call (R-101).
  - The **access-mode selector** in the UI simply sets the tier.
  - **Presets** (Minimal/Standard/Full) choose *tools within* the tier (predicates over registry metadata — R-381), renamed to remove the "Read-only/Full" collision with modes.
  - `safe_mode_flags` are the persisted projection of the tier + `allow_real_trades`/`allow_debug` booleans.
- **Consequences:** Default tier = `READ_ONLY`; Minimal preset = read-only tools only, no sweep (resolves C4); "Backtest-only" is a separate selectable posture; term standardized as "Backtest-only" everywhere (resolves C17).

### ADR-6 — Optimizer is a server-side composite tool; primitives are an Advanced, default-OFF group (resolves C3)
- **Decision:** Canonical tools: `backtest_run/get/list/compare` + `sweep_run/status/results/cancel` + composite `optimize_config(objective, constraints)`. The low-level primitive loop (`backtest_run` in a tight agent loop) lives in an **Advanced group, default-OFF**; the server-side sweep is the default optimization path; `initialize.instructions` steers the agent to `optimize_config`/`sweep_run`. (R-29/501; resolves C3.)
- **Consequences:** Agents make ONE call for an optimization; the sweep orchestrator fans out internally (ADR-8).

### ADR-7 — Dynamic tool registration: registry-filter for tool changes, rebuild-swap only for enable/disable (resolves C12; revised R1-F1/F2/F3)
- **Decision (revised):** Two distinct mechanisms:
  - **Enable/disable a tool or group** (frequent): NO rebuild. The dispatcher consults the persisted enabled-set; `tools/list` returns only enabled tools and disabled tools are rejected at dispatch with `-32601` (R-53/100/187). Emit `notifications/tools/list_changed`. This keeps sessions and in-flight `sweep_status` polling alive.
  - **Master enable/disable** (rare): rebuild-and-swap via a **permanent indirection Mount**. `register_mcp(app)` (at `create_app` body time) installs ONE permanent `Mount("/mcp/rpc", app=_indirection)` where `_indirection` is a tiny ASGI callable dispatching to `app.state.mcp_asgi`. Swap = reassign that ref (→ live FastMCP app with its streamable-HTTP session-manager started, or → the 503 gate). The swap sequence: start the new session-manager task group → assign the ref → drain+stop the old manager with a timeout. Master toggle drops live sessions (documented; clients reconnect).
- **Rationale:** Per-checkbox full rebuild would nuke all sessions + storm `list_changed` (R1-F3/F10). Config writes are debounced/apply-on-Save (R1-F10).

### ADR-8 — Sweep orchestrator: separate process pool, inject pre-loaded snapshot, decomposed (revised R1-F2/F3/F5/F7/F10)
- **Decision (revised):** Decomposed into `ComboGenerator` (pure, Hypothesis-tested), `SweepRanker` (pure), `SweepRunner` (fan-out/persist), and a thin `SweepOrchestrator` (lifecycle) — placed under **`backend/mcp/tools/optimizer/`** (trading-specific, NOT core — R1-F12). Backtests run via a **`BacktestRunner` Protocol** with method `run_one(config, signals, klines, instrument_info) -> metrics` that **bypasses `_load_klines`/`_resolve_instrument_info`/buy-hold-fetch** and accepts a pre-loaded immutable snapshot (R1-F3). The snapshot (incl. BTC for buy-hold) is loaded ONCE via gathered fetches (R1-F17), stored **columnar** (numpy/array, ~8× smaller than list[dict]) under a sweep-specific RSS budget well below the 3M single-backtest cap (R1-F7). CPU-bound combo evaluation runs in a **dedicated `ProcessPoolExecutor`** (not the shared 3-thread pool, not the event loop) so the live event-loop GIL stays uncontended (R1-F2) — **this process-pool isolation is pulled into MVP** because it is the only real live-protection lever (R1-F6); R-294's adaptive circuit-breaker remains P6 but a basic RSS/loop-lag breaker ships in MVP. Incremental crash-safe per-combo persistence; resume by completed-config-hash set (R-276).
- **Throughput is re-stated honestly:** the real engine is pure-Python candle iteration (~0.1–0.5 s+/combo depending on window/symbols), so a 5000-combo sweep is **minutes, not seconds**; the ≥500/sec figure applies to the `FakeBacktestRunner` (orchestration only). §11 carries the corrected, candle-count-relative SLOs (R1-F1/F5).

### ADR-9 — Single-worker-when-enabled (transport); advisory-lock leader is a corruption guard only (revised R1-F4/F9/F1/F12)
- **Decision (revised):** When MCP is enabled, the supported serving topology is **single-worker**. Multi-worker is NOT a supported serving model: with a shared same-port socket the kernel round-robins `/mcp/rpc` to any worker, but the transport is mounted only on the leader → non-leaders 503 nondeterministically (R1-F4/F9). Therefore:
  - The **enable preflight (R-506) FAILS** if more than one worker is detected without single-worker config.
  - Worker-count detection is NOT relied on for correctness (uvicorn `--workers` doesn't set `WEB_CONCURRENCY` — R1-F12); instead **every worker attempts a dedicated pg advisory lock; non-acquirers always degrade `mcp_server=None`**. The lock is held on a **dedicated, never-pooled, lifetime-scoped asyncpg connection** (like the migration runner) so `max_inactive_connection_lifetime=300` cannot silently release it and cause split-brain (R1-F1, CRITICAL).
  - The leader writes its identity (host/pid + `heartbeat_at`) to `mcp_config` so any worker's `/status`/`/health` can report who the leader is, read from cache (R1-F13).
  - Kill-switch/config propagation uses **LISTEN/NOTIFY (sub-second) with an epoch-poll fallback**, started only on enable and torn down on disable (zero-overhead OFF — R1-F11). True multi-worker serving (sticky sessions + shared session store) is deferred to P6.

### ADR-12 — Apply-to-live: the MCP control-plane owns sanitize→ceiling→validate, writes via the existing persistence seam (revised R1-F6 — the "existing scanner config-write service" does NOT exist)
- **Decision (revised):** There is no pre-existing scheduled-scanner config-write *service*; `AutoTradeConfig` is persisted via the generic `AsyncAnalysisDB.update_scheduled_scan(schedule_id, fields)`. So the **MCP control-plane approve handler** (`backend/mcp/router.py`) OWNS the safety pipeline: agent PROPOSES (R-282) → human approves → handler runs **sanitize (strip `allow_real_trades`/live-binding/auto-trade-on — R-284) → absolute non-overridable sanity ceiling (R-538) → the existing `AutoTradeConfig` Pydantic validators + a new shared config-sanity validator (R-539)** → writes via `update_scheduled_scan`. This persistence method is NOT in the R-503 hot-path set (`scanner_service`/`auto_trade_service`/`close_rule_evaluator`/`position_reconciler`/`accounts_service`/lifespan), so the gate holds. The "owned by existing scanner service" wording is dropped. **Revert** (R-329) restores `diff.before`, which MUST carry the FULL prior config (snapshotted into the proposal at approve time), not just changed fields (R1-F16).

### ADR-10 — MVP token model: single hashed bearer, optional-disabled TTL (resolves C5/C19)
- **Decision:** MVP ships a single CSPRNG bearer token stored hashed on `mcp_config` (R-87..92); the `mcp_tokens` table (multi-token, per-client, TTL) is **modeled now but populated in P6** (resolves C5). TTL is optional and **defaults to no-expiry** so a UI-only user can't be locked out (resolves C19); `MCP_TOKEN_TTL` documented, default off.

### ADR-11 — Same-port mount; `bind_host` is display/validation only (resolves C18)
- **Decision:** The transport shares uvicorn's socket (same-port). Loopback is enforced by deployment (`uvicorn --host 127.0.0.1`) + Host/Origin allowlist (R-277/278). `mcp_config.bind_host` is retained for display/validation and the remote-hardening path (P6) but is NOT used for socket binding in MVP (resolves C18). No separate `bind_port` listener in MVP.

### ADR-12 — Apply-to-live: the MCP control-plane owns sanitize→ceiling→validate (see §14.4 for the revised, binding version)
- **Superseded by the revised ADR-12 above and §14.4/§14.12.** Binding decision: the MCP control-plane approve handler owns sanitize→ceiling→validate and writes via `AsyncAnalysisDB.update_scheduled_scan` (NOT a pre-existing scanner service, which does not exist). See the revised ADR-12 block above.

---

## 2. System Context Diagram

```
External MCP client (agent: Claude Desktop via mcp-remote bridge / Claude Code --header)
   │  streamable-HTTP, JSON-RPC, Authorization: Bearer <token>
   │  POST /mcp/rpc   (tools/list, tools/call, resources/*, prompts/*)
   ▼
TradingAgents FastAPI process ───────────────────────────────────────────────┐
   backend/mcp/  (the new package)                                            │
     core/ (transport, dispatch, registry, audit, auth, shape, errors)        │
     tools/<group>/ (thin handlers) ── in-process calls ──▶ app.state:        │
     resources/  prompts/  repositories/  router.py                backtest_service
   ▲                                                               scanner_service
   │  same-origin HTTPS (browser, existing app auth)               accounts_service
   │  GET/PATCH /api/v1/mcp/{config,status,audit,proposals,approve} bybit_rate_gate
Operator browser  ── React /mcp page                              db (asyncpg pool)
                                                                          │
   ┌──────────────────────────────────────────────────────────────────────┤
   ▼                              ▼                                         ▼
PostgreSQL (mcp_* + existing)   Bybit REST klines (shared rate gate)   LLM providers
```

- **External systems:** the MCP client (an LLM agent host) over streamable-HTTP; Bybit (klines for backtests via the shared rate gate — **never live orders from MCP in MVP**); PostgreSQL; the operator's browser.
- **User types:** (1) the **operator** (human) — configures via `/mcp`, approves proposals; (2) the **agent** (machine) — calls tools/resources/prompts over `/mcp/rpc` with a bearer token.
- **Data flow:** agent → `/mcp/rpc` → dispatch pipeline (auth → tier-gate → audit → handler → service → shape/redact) → response. Operator → `/api/v1/mcp/*` → control-plane service → repositories. Apply path: agent proposes → `mcp_proposals` → operator approves on `/mcp` → MCP control-plane approve handler (sanitize→ceiling→validate) → `AsyncAnalysisDB.update_scheduled_scan` (NOT a scanner service; §14.4).

---

## 3. Component Architecture

### 3.1 Package layout (R-372/383/386)
```
backend/mcp/
  __init__.py            # exposes mount_mcp(app); constructs NOTHING at import (R-375)
  mount.py               # the single integration seam: mount_mcp(app) (R-374)
  core/                  # TRADING-FREE plumbing (R-383)
    transport.py         # FastMCP wiring, streamable-HTTP, sessions, Host/Origin allowlist
    registry.py          # @tool decorator, ToolGroup enum, preset predicates (R-376/380/381)
    dispatch.py          # cross-cutting pipeline: auth→tier→audit→timeout→handler→error-map→shape (R-378)
    auth.py              # TokenAuthenticator interface + bearer impl (R-389)
    audit.py             # non-blocking durable writer + hash-chain (R-261/262)
    shape.py             # verbosity/projection/truncation/keyset-pagination (R-385)
    errors.py            # exception→JSON-RPC mapping table assembled from per-tool entries (R-264)
    context_budget.py    # per-tool schema token counting for the budget meter (R-467)
    ping.py              # core_ping reference tool (dependency-free) (R-384)
  tools/                 # TRADING-SPECIFIC handlers, one module per group
    scans/ accounts/ positions/ trades/ portfolio/ analytics/
    scheduled/ strategies/ symbols/ backtest/ debug/ optimizer/ advanced/
  resources/             # static resources (tradingagents://scan/latest, config, portfolio)
  prompts/               # bundled prompt templates
  repositories/          # MCPConfigRepository, AuditRepository, SweepRepository, ProposalRepository
  schemas.py             # control-plane Pydantic models (re-exported into backend/schemas)
  router.py              # control-plane FastAPI router → /api/v1/mcp/*
  manage.py              # headless token bootstrap/rotate command (R-417)
```

### 3.2 Component responsibilities (single responsibility each)
| Component | Responsibility | Errors |
|-----------|---------------|--------|
| `mount_mcp(app)` | Sole touchpoint in `create_app()`; read config, wire `app.state.mcp_server`, mount transport+router or the 503 gate | logs+degrades to None (R-84) |
| `MCPServer` (core/transport) | Own the FastMCP instance, sessions, transport lifecycle, atomic rebuild-and-swap (ADR-7) | bind/port errors → degrade |
| `ToolRegistry` (core/registry) | Discover `@tool` modules, resolve enabled subset from config, compute presets | unknown group/method → build-fail |
| `Dispatcher` (core/dispatch) | Apply cross-cutting pipeline around every handler | maps all exceptions (R-265) |
| `Authenticator` (core/auth) | Validate bearer, bind session to principal | 401 fail-closed (R-92) |
| `AuditWriter` (core/audit) | Non-blocking durable hash-chained append | overflow→sync fallback (R-261) |
| `MCPService` | Orchestrate tool handlers, hold injected service refs | domain exceptions |
| `SweepOrchestrator` | Generate/dedup combos, fan-out via BacktestRunner, rank, persist | partial-fail aggregation (R-191) |
| `ToolGroup handlers` | Thin adapters: validate→call service→return domain object (R-251) | raise domain exceptions |
| `*Repository` | All SQL for `mcp_*` tables (no asyncpg outside) | DB errors → service-unavailable |
| Control-plane `router.py` | `/api/v1/mcp/*` config/status/audit/proposal endpoints | 503 when feature absent |

### 3.3 Dependency direction (R-373, import-linter enforced)
`mount.py` → `core` + `tools` + `repositories`. `tools/*` → `core` + `app.state` services (lazy, at call time). `core/*` → NOTHING trading-specific. Nothing outside `backend/mcp/` imports `backend/mcp/` (sole exception: the one `mount_mcp` call in `create_app()`).

---

## 4. Data Architecture

Migration **version 43** (next after current max 42), appended to `_MIGRATIONS` in `backend/async_persistence.py`, **all SIX tables + indexes + singleton seed in ONE version/transaction** (R-509; see §14.5 — the six are `mcp_config`, `mcp_sweep_jobs`, `mcp_sweep_results`, `mcp_audit_log`, `mcp_proposals`, `mcp_tokens`), supplied as a `callable(conn)` migration to avoid the `split(";")` hazard (R-441). The `backtest_runs` `source`/`sweep_id` columns are a SEPARATE additive migration (§14.4), version-pinned at merge time.

### 4.1 `mcp_config` (singleton, R-444/445/446/447/449/456)
| Column | Type | Notes |
|--------|------|-------|
| `id` | `INT PK CHECK(id=1)` | singleton |
| `enabled` | `BOOLEAN NOT NULL DEFAULT false` | master toggle (R-35) |
| `bind_host` | `TEXT NOT NULL DEFAULT '127.0.0.1'` | display/validation only (ADR-11) |
| `access_token_hash` | `TEXT` | MVP single bearer (ADR-10); null until first enable |
| `capability_tier` | `TEXT NOT NULL DEFAULT 'READ_ONLY' CHECK(tier IN ('READ_ONLY','BACKTEST','MUTATING_DEMO','LIVE_MONEY'))` | authoritative ceiling (ADR-5) |
| `enabled_groups` | `JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof=...'array')` | tool groups on |
| `enabled_tools` | `JSONB NOT NULL DEFAULT '{}'` | per-tool overrides |
| `safe_mode_flags` | `JSONB NOT NULL DEFAULT '{"read_only":true,"allow_real_trades":false,"allow_debug":false}'` | fail-safe (R-308/445) |
| `config_schema_version` | `INT NOT NULL DEFAULT 1` | JSONB shape version (R-446) |
| `row_version` | `BIGINT NOT NULL DEFAULT 0` | optimistic-concurrency precondition (R-447) |
| `config_epoch` | `BIGINT NOT NULL DEFAULT 0` | bumped on every config change; workers poll for config propagation (R-404) |
| `kill_epoch` | `BIGINT NOT NULL DEFAULT 0` | bumped ONLY by disable/kill/tier-downgrade; the TOCTOU epoch-fence signal (§15.5) — narrow so benign edits don't abort in-flight calls |
| `installation_id` | `UUID NOT NULL DEFAULT gen_random_uuid()` | restore-safety; refuse `enabled=true` if mismatch (R-456) |
| `audit_retention_days` | `INT NOT NULL DEFAULT 365 CHECK(BETWEEN 1 AND 3650)` | R-449 |
| `sweep_retention_days` | `INT NOT NULL DEFAULT 90` | R-449 |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Seed: `INSERT INTO mcp_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING` (R-444). Boot repairs an incomplete row to fail-safe defaults and forces `enabled=false` (R-513).

### 4.2 `mcp_sweep_jobs` (R-432/436/448/450)
`id UUID PK DEFAULT gen_random_uuid()`, `status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','cancelled','failed','interrupted'))`, `strategy TEXT`, `param_space JSONB NOT NULL`, `objective_metric TEXT NOT NULL`, `total_combos INT NOT NULL CHECK(>0)`, `completed_combos INT NOT NULL DEFAULT 0 CHECK(<=total_combos)`, `best_result_id UUID` (→ 4.3, deferrable), `idempotency_key TEXT`, `principal_token_id TEXT`, `session_id TEXT`, `created_at/started_at/completed_at TIMESTAMPTZ` with `CHECK(completed_at IS NULL OR completed_at>=started_at)`. Partial-unique `(principal_token_id, session_id, idempotency_key) WHERE idempotency_key IS NOT NULL` (R-448). Index: partial `(status) WHERE status IN ('queued','running')` (R-452), `(created_at)` (R-450).

### 4.3 `mcp_sweep_results` (R-433/434/435/437/439)
`id UUID PK`, `sweep_id UUID NOT NULL REFERENCES mcp_sweep_jobs(id) ON DELETE CASCADE`, `config JSONB NOT NULL` (money fields as decimal strings — R-584), `config_hash CHAR(64) NOT NULL`, `backtest_id UUID REFERENCES backtest_runs(id) ON DELETE SET NULL` (R-439), `metrics JSONB NOT NULL` (money as decimal strings — R-434), `objective_value NUMERIC(20,8)` (NaN/Inf→NULL, R-435), `result_rank INT` (reserved-word-safe rename, R-431), `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. `UNIQUE(sweep_id, config_hash)` (R-433). Index `(sweep_id, result_rank)`. `mcp_sweep_jobs.best_result_id` → `mcp_sweep_results(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED` (R-438).

### 4.4 `mcp_audit_log` (R-430/431/451/452/453/457)
`id BIGSERIAL PK`, `seq BIGINT NOT NULL UNIQUE`, `prev_hash TEXT`, `entry_hash TEXT NOT NULL`, `tool_name TEXT`, `tool_group TEXT` (reserved-word-safe, R-431), `safety_class TEXT`, `mutating BOOLEAN NOT NULL`, `principal_token_id TEXT`, `session_id TEXT`, `correlation_id UUID`, `args_redacted JSONB`, `sensitive_payload BYTEA` (Fernet via `ACCOUNTS_ENCRYPTION_KEY`, R-453), `status TEXT NOT NULL CHECK(status IN ('ok','error','rejected','rate_limited','timeout'))`, `error TEXT`, `started_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `duration_ms INT CHECK(>=0)`. Hash over canonical PLAINTEXT pre-encryption (R-454). Indexes: `(started_at DESC)`, `(session_id, started_at DESC)`, `(tool_name, tool_group, status)`, BRIN `(started_at)`.

### 4.5 `mcp_proposals` (R-582/586) — the apply→live handoff
`id UUID PK`, `sweep_id UUID REFERENCES mcp_sweep_jobs(id) ON DELETE SET NULL`, `config JSONB NOT NULL` (decimal-string money), `diff JSONB NOT NULL`, `status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','expired','applied','reverted'))`, `approver TEXT`, `applied_config_version TEXT`, `risk_verdict JSONB`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `expires_at TIMESTAMPTZ NOT NULL`. Status transitions validated + audited (R-586). FK is intra-MCP (allowed; R-412 only bars FKs FROM existing tables INTO mcp).

### 4.6 `mcp_tokens` (modeled, populated P6 — R-280/C5)
`id UUID PK`, `name TEXT`, `token_hash TEXT NOT NULL`, `scope JSONB`, `principal TEXT`, `expires_at TIMESTAMPTZ`, `revoked_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. MVP uses `mcp_config.access_token_hash`; this table is created empty for forward-compat.

### 4.7 Data lifecycle
- **Config:** created at migration seed; updated via control-plane (optimistic-concurrency `row_version`); never deleted.
- **Sweeps:** queued→running→terminal; results streamed per-combo (crash-safe); purged by `sweep_retention_days` (whole job by age, CASCADE removes results).
- **Audit:** append-only, hash-chained; chain-aware purge re-anchors on retention (R-451); GDPR tombstoning nulls `sensitive_payload` keeping `entry_hash` (R-454/302, P6).
- **Proposals:** pending→terminal; TTL expiry; never auto-applied.
- **JSONB shapes:** validated by versioned Pydantic models on write+read (R-455).

---

## 5. API Architecture

### 5.1 Data-plane (JSON-RPC over streamable-HTTP, `/mcp/rpc`, bearer-auth, NOT in OpenAPI)
- MCP methods: `initialize` (serverInfo+capabilities+instructions — R-222/223), `tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources/templates/list`, `prompts/list`, `prompts/get`, `ping`, `notifications/{tools/list_changed,progress,cancelled}`.
- Tool naming: `group_action` (e.g. `scans_list`, `backtest_run`, `sweep_run`, `optimize_config`) — immutable once published (R-247/487).
- Errors: tool execution failures → JSON-RPC success with `isError:true` + agent-visible content (R-225); protocol errors → JSON-RPC `-32700/-32600/-32601/-32602/-32603` + server range (R-226); disabled/unknown tool → `-32601` (R-187).
- Tool annotations: `readOnlyHint/destructiveHint/idempotentHint/openWorldHint` from registry (R-228).

### 5.2 Control-plane (REST, `/api/v1/mcp/*`, same-origin, existing app auth + CSRF)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/mcp/config` | current config, enabled groups/tools, tier, budget estimate |
| PATCH | `/api/v1/mcp/config` | optimistic-concurrency update (toggle, groups, tools, tier, safe-mode) |
| POST | `/api/v1/mcp/enable` | preflight-gated OFF→ON (R-506/507) |
| POST | `/api/v1/mcp/disable` | + kill-switch variant (R-39) |
| POST | `/api/v1/mcp/token/regenerate` | rotate bearer (R-90) |
| GET | `/api/v1/mcp/status` | running/leader/sessions/last-error (R-159) |
| GET | `/api/v1/mcp/health` | ops probe, 200 when OFF (R-416) |
| GET | `/api/v1/mcp/audit` | paginated activity feed (keyset) |
| GET | `/api/v1/mcp/proposals` | pending/historical proposals (R-585) |
| GET | `/api/v1/mcp/proposals/{id}` | proposal + diff + server risk verdict |
| POST | `/api/v1/mcp/proposals/{id}/approve` | human apply (sanitized, validated, sanity-ceiling) |
| POST | `/api/v1/mcp/proposals/{id}/reject` | |
| POST | `/api/v1/mcp/proposals/{id}/revert` | restore prior config (R-329) |
| POST | `/api/v1/mcp/test-connection` | loopback-only SSRF-guarded probe (R-557) |

- Availability gate: control-plane returns 503 when `app.state.mcp_server is None`/feature absent (mirrors debug router).
- Rate limiting: per-token tool-call bucket (R-116); separate stricter exchange-facing throttle via the shared `bybit_rate_gate` with a reserved live floor (R-548).

---

## 6. Integration Architecture

- **MCP SDK (FastMCP, official `mcp` Python SDK ≥1.12):** streamable-HTTP transport; we override its defaults (bind, auth, CORS, session caps), disable verbose/debug, enumerate+lock down auto-registered routes (R-290/555/556).
- **BacktestService:** the ONLY backtest engine; sweeps drive it via a `BacktestRunner` Protocol (R-259/268); sweep-spawned backtests tagged `source=mcp_sweep` + `sweep_id` (R-242).
- **Kline cache:** MCP warmup writes to the SAME store/keys as BacktestService (R-243), with a coexistence quota protecting the live path (R-516).
- **Bybit (klines):** via the shared `bybit_rate_gate` in a subordinate lane with a reserved live floor; a 429/ban breaker halts MCP fetches first (R-548/549).
- **Scanner config write (apply-owner):** the MCP control-plane approve handler writes the approved config via the existing `AsyncAnalysisDB.update_scheduled_scan` persistence method — there is NO pre-existing scanner config-write *service* (§14.4/ADR-12).
- **External MCP client:** Claude Desktop via `mcp-remote` stdio bridge (R-244); Claude Code via `--header`; `Authorization: Bearer` only (R-281).
- **Failure/fallback:** any integration unavailable → the tool returns a defined service-unavailable `isError`; MCP init failure → degrade to None (R-84).

---

## 7. Infrastructure & Deployment

- **No new infra** — same FastAPI process, same PostgreSQL, same uvicorn. New: **6 DB tables (v43)** + a SEPARATE additive `backtest_runs` `source`/`sweep_id` migration, `backend/mcp/` package, frontend `/mcp` route.
- **Topology:** single-worker when enabled, else advisory-lock leader (ADR-9).
- **Env vars** (`TRADINGAGENTS_MCP_*` / `MCP_*`, via `_validated_int`): `MCP_ENABLED` (tri-state), `MCP_BIND_HOST`, `MCP_TOKEN` (bootstrap), `MCP_INSTALLATION_ID` (out-of-band restore-safety, §14.9), `MCP_MAX_SWEEP_BACKTESTS` (5000), `MCP_MAX_CONCURRENT_BACKTESTS`, `MCP_SWEEP_WORKERS` (process-pool size, ≤ cores−1), `MCP_RATE_LIMIT_PER_MIN`, `MCP_SESSION_TTL`, `MCP_TOKEN_TTL` (default off), `MCP_DB_POOL_RESERVE` (live floor), `MCP_ALLOW_REMOTE_BIND`. Precedence: env > DB > default; security fields env-only (R-405/406/407).
- **Rollout:** ship dark (code present, `enabled=false`, zero-overhead R-362); enable dev→staging→single prod canary; preflight gate + dry-connect self-test on enable (R-506/507); enable-window heightened watch + auto-disable on live-trading regression (R-520).
- **Rollback ladder:** UI kill-switch (instant) → DB `UPDATE enabled=false` (polled) → `MCP_ENABLED=false` env (restart) — at least one works under a saturated loop (R-505).
- **Resource budget:** dedicated bounded sweep executor (R-424); container mem sized so a max sweep (+512 MB) can't OOM-kill the trading process (R-423).

---

## 8. Security Architecture

- **Auth flow:** agent sends `Authorization: Bearer <token>` → `Authenticator` constant-time-compares the hash (R-89) → binds session to principal → else 401 fail-closed (R-92). Host/Origin allowlist + DNS-rebinding guard precede auth (R-277/278).
- **Authorization model:** capability tier ceiling (ADR-5) re-read per call (R-101); TOCTOU epoch-fence before any side-effecting call (R-305); registration-time deny-list bars wrapping config/token/kill-switch/audit methods as tools (R-288).
- **Default-safe:** OFF → unmounted (R-37); first-enable forces a strong token (R-306); default tier READ_ONLY, zero mutating/live tools (R-307); live-money forbidden without separate opt-in (R-98).
- **Secrets:** canonical deny-list + positive leak test over results/errors/logs/audit (R-553/554); token never returned by any tool (R-109); audit `sensitive_payload` encrypted at rest (R-453).
- **Untrusted content:** market/scan/symbol text fenced in a typed "untrusted" envelope, injection-neutralized, never in instruction position (R-532/533); no untrusted-data-driven capability path (R-534).
- **Apply path (the only money bridge):** human-only out-of-band approval (R-282); server-computed risk verdict independent of agent (R-535); per-high-risk-field ack + typed-confirm (R-536); absolute non-overridable sanity ceiling + existing validators (R-538/539); sanitization strips live-enabling fields (R-284).
- **Attack surface:** SDK auto-routes locked down (R-555); activity-feed XSS-hardened + strict CSP (R-542/543); resource-URI params validated (R-544); panic/revoke-all action (R-547); data-egress consent (R-551).

---

## 9. Observability Architecture

- **Logging:** structured, `MCP_LOG_LEVEL` (default INFO), per-call `correlation_id` linking request→service→backtest→audit; token scrubbed (R-126/421).
- **Metrics** (into the EXISTING `metrics.prometheus_text()` `/metrics`, R-420): `mcp_tool_calls_total{tool,group,status}`, `mcp_tool_latency_seconds`, `mcp_sweeps_active`, `mcp_sweep_throughput`, `mcp_active_sessions`, `mcp_audit_queue_depth`, `mcp_audit_completeness`, `mcp_rate_limited_total`, `mcp_circuit_breaker_state`, `mcp_enabled`, `mcp_leader`. OFF → series absent/zero.
- **Audit:** append-only hash-chained, every tool call (R-112); `mcp_audit_completeness == 1.0` asserted (R-367).
- **Alerting:** tool_error_rate, audit_queue near cap, breaker open, auth-failure spike, stuck sweep, leader-lock lost (R-422).
- **Health:** `/api/v1/health` gains `mcp:{enabled,state,leader,active_sessions,last_error_at}` (degraded ≠ 503, R-415); `/api/v1/mcp/health` ops probe (R-416).

---

## 10. Resilience & Failure Modes

| Scenario | Behavior |
|----------|----------|
| MCP init fails (bad port/config/SDK) | degrade `app.state.mcp_server=None`, log, NEVER abort trading startup (R-84/207) |
| DB lost mid-call | tool returns service-unavailable promptly, no hang (R-205) |
| BacktestService is None | backtest/sweep tools return defined service-unavailable (R-206) |
| Backend restart mid-sweep | atomic boot recovery claims `running`→`interrupted`/resumable (by completed config-hash set), BEFORE advertising tools (R-275/276) |
| Live-trading health degrades | circuit-breaker suspends MCP work (hysteresis + flap cap), attributes to active sweeps (R-294/518/519) |
| Toggle OFF mid-sweep | cancel in-flight tool calls, persist running sweeps to `interrupted` (resumable); kill-switch hard-cancels everything (R-182/C13) |
| Network drop to client | detect dead session, clean up tasks, free resources (R-208) |
| Bybit 429/ban | breaker halts MCP fetches first, preserving live API budget (R-549) |
| Multi-worker + enabled | leader election or refuse-mount; config/kill-switch propagate to all workers (R-401/404) |
| Consistency | per-combo committed txn; idempotency unique constraints; optimistic-concurrency config writes |

---

## 11. Performance Architecture

- **Latency budgets:** read tools p50<50ms/p95<200ms (R-353); audit write adds <5ms p95 (non-blocking, R-357).
- **Sweep:** throughput is candle-count-relative and benchmarked per-engine in CI (SUPERSEDED §14.13 — the "≥50/sec/core" figure is REMOVED; `FakeBacktestRunner` ≥500 combos/sec is orchestration-only; a real 5000-combo sweep is **minutes to ~1 hour** depending on candle count/pool size); max 5000 combos; sweep snapshot held columnar in shared memory, RSS budgeted separately (§15).
- **Context budget:** per-tool schema ≤~300-500 tokens; presets Minimal≤2k/Standard≤8k/Full≤20k tokens; estimate within ±10% (R-358/458/467).
- **Output:** equity ≤1000 pts, trade page ≤500 rows, summary payload ≤256KB; keyset pagination; top-N+drill-down (R-356/500).
- **Caching:** symbols/sectors/config cached short-TTL, invalidated on config change; financial data not stale (R-464). Sweep pre-warms klines once, reuses across combos (R-256/462).
- **Concurrency:** bounded process-pool below `max_concurrent_backtests` (capped ≤ cores−1, reserving ≥1 core for the live loop); CPU work in a `ProcessPoolExecutor` (spawn, shared-memory snapshot — §15); live trading has scheduling priority via `os.nice`/`oom_score_adj` on sweep workers (§15) (R-257/292/424/463).

---

## 12. Technology Decisions

- **Backend:** Python 3.12, asyncio, asyncpg, Pydantic v2 — matches the codebase.
- **MCP library:** official `mcp` Python SDK's **FastMCP**, version-pinned (≥1.12), hash-pinned in the lockfile (R-289/575); SBOM + pip-audit CVE + license gate (R-291/581).
- **Transport:** streamable-HTTP (ADR-1).
- **Frontend:** React 18, TanStack Router/Query, zod v4, neumorphism `@/components/ui` primitives — matches the codebase; `/mcp` decomposed into per-section components (R-491).
- **Testing:** pytest + pytest-asyncio (`tests/backend/mcp/`), in-memory ASGI transport (no port), `FakeBacktestRunner`, seeded klines/scan fixtures, golden sweep; Hypothesis for the combo generator; vitest for the frontend; import-linter for boundaries (R-339..371/479..482).
- **Migrations:** versioned `_MIGRATIONS` callable at v43 (R-440/441).

---

## 13. Requirement Coverage Map (orphan check)

Every requirement category has an architectural home:
- TOGGLE (R-35..44) → ADR-4, `mcp_config`, control-plane enable/disable.
- TOOLBUDGET (R-45..57) → `ToolRegistry` + preset predicates + `context_budget` + `/mcp` Tools section.
- CORE tools (R-1..16) → `tools/<group>/` + `resources/` + `prompts/`.
- OPTIMIZER (R-17..34, 309..338) → `SweepOrchestrator` + `optimize_config` + `mcp_proposals`.
- TRANSPORT/CALLPATH (R-58..71) → ADR-1/2/3, `core/transport`+`dispatch`.
- DATA (R-72..79, 430..457, 582..586) → §4.
- SECURITY (R-87..124, 277..308, 492..558) → §8 + dispatch pipeline + apply path.
- ASYNC/LIFECYCLE (R-80..86, 245..248) → `SweepOrchestrator` + `mount_mcp` lifespan + boot recovery.
- MULTIWORKER (R-400..404) → ADR-9.
- OBSERVABILITY (R-125..128, 420..422) → §9.
- PERF (R-129..133, 353..358, 458..467) → §11.
- UI (R-134..179, 585) → frontend `/mcp` per-section components.
- DEVOPS/MIGRATION (R-405..429, 503..531) → §7 + §10 + runbooks.
- MAINTAINABILITY (R-372..399, 468..491) → package layout, registry pattern, ADRs, docs.
No requirement is orphaned. Deferred items (P5/P6 per R-393..399) have seams (transport/auth interfaces, `mcp_tokens` table, circuit-breaker hook).

---

## 14. Round 1 Review Revisions (Critical/High findings folded in)

This section records the binding resolutions from architecture-review Round 1 (5 reviewers, codebase-grounded). They REVISE/SUPERSEDE earlier sections where noted.

### 14.1 Mount mechanics — two-phase, no runtime route mutation (R1-F1/F2/F7; devops-F4)
`create_app()` registers routes in its body but services/DB pool are created in `lifespan` — so a single `mount_mcp` cannot both register routes and read config. Split:
- **`register_mcp(app)`** — called in the `create_app` body. Installs (a) ONE permanent `Mount("/mcp/rpc", app=_indirection)` where `_indirection` dispatches to `app.state.mcp_asgi` (initialized to the 503-gate ASGI app), and (b) the control-plane router at `/api/v1/mcp/*`. Reads NOTHING, opens no DB connection (R-375).
- **`async mcp_boot(app)`** — called in `lifespan` AFTER existing migrations, stale-backtest-recovery, and `resume_incomplete_scans` (R-510 ordering). Acquires the leader lock, reads `mcp_config`, runs MCP boot-recovery (claim `running`→`interrupted`), and if enabled builds the FastMCP app + starts its session manager + points `app.state.mcp_asgi` at it. On failure: degrade `app.state.mcp_server=None`, leave the 503 gate (R-84).
- A startup-order test asserts this sequence (R-510).

### 14.2 Reserved DB-connection floor for live trading (perf-F4; devops-F2, CRITICAL)
The asyncpg pool is `max_size=10` and shared with the live loop. MCP MUST NOT exhaust it. Mechanism: a single **MCP DB semaphore** caps concurrent MCP/sweep connection acquisitions at `(pool_max − live_floor)` with `live_floor ≥ 4` (reconciler+scanner+auto_trade+close_eval). The floor is validated in the enable preflight (R-506) and asserted by a load test (R-360 re-scoped: "50 calls + 5 sweeps" only holds if `pool_max` is raised or MCP gets a dedicated pool — MVP raises `DB_POOL_MAX` and enforces the semaphore). Background sweep tasks never hold a pooled connection across combo execution (R-267).

### 14.3 Dispatch pipeline — ONE canonical ordering, audit as a WRAPPER (R1-F5/F14; security-F)
Published canonical pipeline (referenced everywhere; reconciles §2/§3.1/§8):
```
host/origin allowlist → auth → rate-limit → tier-gate → epoch-fence(mutating only, R-305)
   → audit-BEGIN (reserve seq+correlation_id) → timeout(handler) → audit-END (finalize status/duration/error)
   → error-map → shape/redact
```
Audit is a wrapping stage, not a linear step: `seq`/`correlation_id` reserved pre-call, outcome finalized post-call as a SINGLE row, with a guaranteed finalize on exception/cancel — so a crashed/cancelled handler still yields a terminal audit row (completeness == 1.0, R-367). The single serialized audit-writer task assigns `seq`/`prev_hash`/`entry_hash`; the overflow sync-fallback enqueues through the SAME serialization point (never a direct write — R1-F17). The TOCTOU epoch-fence captures the config epoch at dispatch and re-checks it atomically immediately before any side-effecting (exchange/kline) call (R-305).

### 14.4 BacktestService changes are real, additive, and acknowledged (integration-F2/F6; arch-F15)
Driving sweeps "through BacktestService" requires real, ADDITIVE changes to that service/table (not zero-change):
- `backtest_runs` gains `source TEXT NOT NULL DEFAULT 'ui'` + `sweep_id UUID` (a SEPARATE additive migration, NOT part of v43's 5 MCP tables) + an index; list/retention queries updated to filter/exclude `source='mcp_sweep'` (R-242).
- A new `BacktestRunner` entry path `run_one(config, signals, klines, instrument_info)` bypasses `_load_klines`/`_resolve_instrument_info`/buy-hold-fetch and the UI create-rate-limiter, drawing from a SEPARATE sweep semaphore sized below `_MAX_CONCURRENT` so UI backtests keep reserved slots (R1-F6/F15). A shared global backtest-concurrency gate (owned by BacktestService) is the single source both UI and sweep acquire.
- `backtest_run` tool input schema is generated from `BacktestCreateRequest` with the R-346 build-time equivalence test; each sweep combo is validated against the same model. Money fields are `float` in `BacktestCreateRequest` but decimal-string in JSONB persistence — coerced at the persist boundary (integration-F7).

### 14.5 Table count reconciled (arch-F8)
V43 creates **6** tables: `mcp_config`, `mcp_sweep_jobs`, `mcp_sweep_results`, `mcp_audit_log`, `mcp_proposals`, `mcp_tokens` (modeled-now, populated P6). §4 intro, §7, and R-509's "four/five" are corrected to **six**. The `backtest_runs` `source`/`sweep_id` columns are a separate additive migration (14.4), version-pinned at merge time (R-512 contiguity CI gate, blocking).

### 14.6 Missing control-plane endpoints added (integration-F4/F5)
The operator UI talks only to `/api/v1/mcp/*`, so the data-plane (bearer, agent-only) sweep tools are not reachable from the browser. Add:
- `GET /api/v1/mcp/sweeps` (keyset list), `GET /api/v1/mcp/sweeps/{id}` (status+best-N), `POST /api/v1/mcp/sweeps/{id}/cancel` (R-166/169).
- `GET /api/v1/mcp/tools` — the FULL registry (`{name, group, description, safety_class, mutating, annotations, input_schema, est_tokens}`) + preset definitions, so the catalog browser + budget meter compute client-side without per-checkbox round-trips (R-50/57/467).

### 14.7 Middleware interactions on `/mcp/rpc` (integration-F1/F11/F12; arch-F9)
Four app-wide middlewares wrap the mount. Required handling:
- **ContentSizeLimitMiddleware (1 MB):** exempt `/mcp/rpc` (a large `sweep_run` param_space exceeds 1 MB); over-limit must return a JSON-RPC error, not a raw 413 (R1-F1).
- **CSPCSRFMiddleware:** exempt EXACTLY `/mcp/rpc` (`path == '/mcp/rpc' or path.startswith('/mcp/rpc/')` — never `startswith('/mcp')`, which would catch the SPA `/mcp`); keep the security-header injection on the exempted branch; a regression test asserts a non-`/mcp/rpc` POST without `X-Requested-With` still 403s (R1-F11/arch-F9).
- **ObservabilityMiddleware:** make the 3 s slow-request threshold path-aware (exempt `/mcp/rpc` streaming) (R1-F12).
- **CORSMiddleware:** never reflects arbitrary origins; the data-plane relies on the Host/Origin allowlist, not CORS.

### 14.8 Capabilities ⊆ implemented; protocol version pinned (integration-F3/F8/F10)
Advertise only implemented capabilities — MVP sets `resources.subscribe:false`, drops `logging` unless `logging/setLevel`+`notifications/message` ship (deferred per R-397). An init-contract test asserts advertised capabilities ⊆ implemented methods. Pin supported `protocolVersion` (e.g. `2025-06-18`), negotiate-down-not-error, validate the `MCP-Protocol-Version` header post-handshake. Contract version carried in `serverInfo.version` + a `tradingagents://server/info` resource, tied to the R-525 golden-snapshot diff-gate.

### 14.9 Restore-safety identity is out-of-band (devops-F5)
`installation_id` as a `mcp_config` column travels in `pg_dump` → a clone can't self-detect. Add an out-of-band identity (`MCP_INSTALLATION_ID` env or a first-boot filesystem marker); on boot, if stored `mcp_config.installation_id` ≠ the out-of-band id → force `enabled=false` + rotate token + alert (R-456/419).

### 14.10 Retention purge lives OUTSIDE the feature (devops-F6, R-521)
The audit/sweep purge must survive code removal. Implement it as a job in the EXISTING scheduler service (or pg_cron / a DB-side scheduled function), NOT inside `backend/mcp/`. Removing `backend/mcp/` must not stop the purge.

### 14.11 Out-of-band kill path + live-protection breaker (devops-F3/F7/F8/F18, CRITICAL)
- An **out-of-band watchdog** (separate thread / SIGTERM handler) can flip `enabled=false` and abort the sweep executor WITHOUT scheduling on a saturated event loop; env force-OFF + restart is the only unconditional tier (R-505).
- An in-process **RSS / cgroup-memory watchdog** sheds sweeps when RSS crosses ~80% of the container limit, before the kernel OOM-kills the shared trading process (devops-F3).
- The circuit-breaker watches LIVE SLIs (event-loop lag p95, scanner cycle time, reconciler/order latency, asyncpg pool-wait) — these must be exported to `/metrics` (prerequisite audit; some may not exist yet) plus an attribution series correlating breaker-open × active sweeps (devops-F7).
- Env force-OFF must also WRITE-BLOCK the enable/PATCH endpoints (hard-reject, no DB mutation) so removing the env var later doesn't spring MCP ON with stale intent (devops-F10).

### 14.12 Deferred-but-clarified items
- `config_epoch` retained for the kill-switch/config propagation (LISTEN/NOTIFY primary); `row_version` for optimistic concurrency — distinct purposes (R1-F20).
- Audit hash-chain: kept for MVP (R-112/367 mandate), single serialized writer; tombstoning/re-anchor stays P6 (R1-F19).
- Equity downsample reconciled to ≤1000 points in the MCP shape layer (LTTB), independent of the service's 2000 (R1-F15).
- `manage.py` command path: pin the runbook to `python -m backend.mcp.manage mcp ...` and smoke-test the exact string (devops-F16).
- Single-flight + serve-stale-while-revalidate for non-financial caches (symbols/sectors) to avoid thundering herd (perf-F11).
- Context-budget token counts computed with a real BPE reference, biased upward so the meter never under-reports (perf-F8).
- `test-connection` uses the in-process ASGI client (zero socket, zero SSRF surface), matching R-507 (arch-F18).

### 14.13 §11 performance budgets — corrected (perf-F1/F5/F13)
- Read-tool p50<50ms/p95<200ms holds **in isolation AND with a max sweep running** only via the reserved pool floor (14.2) + process-pool CPU isolation (ADR-8); a test measures read p95 WHILE a sweep fans out.
- Sweep throughput is candle-count-relative: `FakeBacktestRunner` ≥500 combos/sec (orchestration); real cached backtests benchmarked per-engine (≈1–5/sec aggregate through the bounded pool), so a 5000-combo sweep is **minutes**. The §11 "≥50/sec/core" is removed; a real-engine micro-benchmark in CI publishes the actual curve.
- Sweep snapshot RSS budgeted separately (columnar, sub-512MB), with a realistic-snapshot RSS assertion (perf-F7).

---

## 15. Round 2 Review Revisions (ProcessPool hardening + contract completions)

Round 1's ProcessPool decision (ADR-8) closed the GIL-contention critical but opened new live-process risks (RSS multiplication, CPU starvation, fork-inherited DB sockets, snapshot serialization). Round 2 also surfaced contract gaps the §14 revisions declared but didn't fully specify. Binding resolutions:

### 15.1 ProcessPool memory & isolation model (R2-F1/F3/F7/F12; devops R2-F3/F12)
- **Start method = `spawn`** (forced on Windows dev; mandated on Linux too) — NEVER `fork`, because fork inherits the live asyncio loop, open asyncpg sockets, and held locks into children → FD/connection corruption + fork-while-locked deadlock against live trading.
- **Snapshot via `multiprocessing.shared_memory` (or Arrow IPC), attached not copied** — the columnar snapshot is built ONCE in the parent and placed in a shared segment; workers ATTACH (zero-copy). `submit()` carries only the tiny combo config, never the snapshot (avoids the 5000× per-task pickle that would block the event loop and re-create the N+1). RSS budget = `N_workers × interpreter + 1 × shared-snapshot`, asserted on the deployment OS.
- **`run_one` runs in an import-light, side-effect-free module** (pure engine + snapshot only) so `spawn` re-import pulls no service/LLM/app-state/DB wiring; a Windows worker-startup test asserts this.
- **Core cap + priority:** `MCP_SWEEP_WORKERS ≤ cores−1` (reserve ≥1 core for the live loop); workers set `os.nice(+10)` and a high `oom_score_adj` so the OOM killer prefers a sweep child over the shared trading process; `maxtasksperchild` recycles workers so freed RSS returns.
- **Cancellation across the boundary:** `sweep_cancel`/kill terminates worker PIDs (SIGKILL) — a running combo is not asyncio-cancellable; killed combos are recovered via the completed-config-hash resume set. The R-274 drain ladder is restated in ProcessPool terms: stop submitting → cancel queued futures → terminate running workers → persist partial + flush audit in the main loop.

### 15.2 DB connection budget — bounded against `max_connections` (perf R2-F4/F5/F11; devops R2-F1/F2/F6)
- **Prefer a SEPARATE small MCP asyncpg pool** over enlarging the shared one; if the shared pool is reused, the MCP semaphore must bracket the ENTIRE hold (acquire-before-`pool.acquire()`, release-after) and cap MCP acquisitions at `pool_max − live_floor`.
- **`live_floor` is MEASURED, not counted** — instrument peak concurrent live-loop acquisitions (scanner fan-out, multi-order auto_trade) and set `live_floor = measured_peak + headroom` (not "4 subsystems").
- **`max_connections` preflight gate:** enable FAILS unless `(pool_max + dedicated_leader_lock_conn + listen_notify_conn + migration_conn) × instances ≤ max_connections − reserved`. Raising `DB_POOL_MAX` without this check is itself a live-down path (`FATAL: too many connections` hits live queries).
- **EVERY MCP pooled acquisition is gated or dedicated** — audit writer, control-plane REST endpoints, leader heartbeat, boot-recovery all routed through the semaphore or onto dedicated connections; a test asserts no un-gated MCP pool acquire. Ban PgBouncer transaction-mode on the leader-lock connection (advisory locks break under it).

### 15.3 Leader liveness & failover (devops R2-F5)
- The leader runs a **liveness loop** re-asserting it holds the advisory lock on its dedicated connection; on loss (PG restart, idle_session_timeout, TCP drop) it self-demotes (point `mcp_asgi` back to the 503 gate, `mcp_server=None`).
- Non-leaders run a **promotion-retry loop** that runs `mcp_boot` if they later acquire the lock. For single-worker deployments, failover == supervised process restart (documented).

### 15.4 Audit single-writer for ALL appends (arch R2-F5/F10; integration)
- BOTH data-plane (tool-call) and control-plane (proposal approve/reject/revert) audit records go through the ONE serialized `core/audit` writer on `app.state`. Direct audit INSERTs are forbidden (would fork the hash chain).
- At audit-BEGIN only `correlation_id` is reserved (for log tracing); `seq`/`prev_hash`/`entry_hash` are assigned by the serialized writer at audit-END in completion order. The overflow sync-fallback enqueues through the same writer (never a direct write). A test asserts chain continuity across an interleaved tool-call + proposal-approve.

### 15.5 Apply path: allow-list, scoped epoch-fence, safe revert (security R2-F2; arch R2-F14)
- **Sanitize is an ALLOW-LIST, not a deny-list** — the approve handler accepts ONLY the known-safe sweepable `AutoTradeConfig` fields and rejects anything outside the set, so a future live-enabling field can't slip through (R-284 "stripped OR rejected" → rejected).
- **Revert re-runs the full pipeline** — restoring `diff.before` goes through sanitize→ceiling→validate too (a human may have legitimately set `allow_real_trades=true` earlier; revert must not blindly restore raw), and warns if the live config changed since apply (don't clobber unrelated manual edits).
- **Epoch-fence uses a NARROW `kill_epoch`** (bumped only by disable/kill/tier-downgrade), not the broad `config_epoch` (which bumps on benign edits like `audit_retention_days`), so routine operator edits don't spuriously abort in-flight calls. The fence is applied by the dispatch pipeline (not left to handler authors) for any tool whose registry entry is `mutating` OR `exchange_facing` (kline fetches in `backtest_run`/`sweep_run` count, even though `readOnlyHint` — they consume the rate gate).

### 15.6 `run_one` Protocol completion (integration R2-F3/F6)
- Signature: `run_one(config, signals, snapshot, instrument_info, *, deadline) -> metrics`, where `snapshot` carries BTC klines so `run_one` replicates `_attach_buy_hold` from memory (best-effort None-on-missing) → combo metrics match the UI-backtest shape (parity for `excess_return`/`buy_hold_return_pct`, and the R-346 equivalence intent).
- Each combo **does NOT** insert a full `backtest_runs` row by default (avoids 5000 rows/sweep + the slot-reserve/rate-limit path); results live in `mcp_sweep_results` with `backtest_id` NULL. IF provenance to a re-runnable `backtest_runs` row is required for a winning config, the operator/agent re-runs that single config via `backtest_run` (which creates the tagged row). This removes the R2-F5 retention-orphan entirely (no tagged `backtest_runs` rows accumulate). The `source`/`sweep_id` columns on `backtest_runs` remain for the OPTIONAL case where a sweep is configured to persist rows, and the out-of-band purge (§14.10) deletes `source='mcp_sweep'` rows by age.

### 15.7 Money type symmetry (integration R2-F8)
- Coercion is pinned to `Decimal(str(x))` (exact, no IEEE drift) at every persist boundary. The OUTPUT/resource money representation is declared (decimal strings) and a round-trip test asserts string→`backtest_run`-number→string is lossless, extending R-346 beyond input-only.

### 15.8 Loopback interop & version negotiation (integration R2-F9/F10/F14; arch)
- **MVP is loopback-only:** both Claude Desktop (`mcp-remote` stdio↔HTTP shim) and Claude Code (`--header`) must run on the SAME host; `--header` supplies the bearer, not remote reach. True remote access is P6 (`bind_host` + TLS). §6 states this caveat.
- **Host/Origin allowlist allows an ABSENT Origin from local non-browser bridges** (mcp-remote/Node send `Host: 127.0.0.1:PORT`, no Origin); a PRESENT Origin must be loopback. A missing `MCP-Protocol-Version` header defaults to the negotiated version (reject only an explicitly-unsupported value), so older clients connect.

### 15.9 Mount lifespan & toggle teardown (arch R2-F4/F10)
- The indirection `_indirection` handles `scope["type"] in ("http","websocket")` only and no-ops/acks `lifespan` — the FastMCP session manager is driven explicitly in `mcp_boot`, never via mount lifespan propagation. On master-disable, the old session-manager lifecycle is explicitly torn down (await its shutdown) before/after the ref-swap; a repeated enable↔disable toggle test asserts no task/FD leak.

### 15.10 Operator full-results endpoint + restore env-ON override (integration R2-F11; devops R2-F8/F9)
- Add `GET /api/v1/mcp/sweeps/{id}/results` (keyset-paginated, ≤1000-pt shape) so the operator UI renders/exports the full per-combo grid, not just best-N.
- **Installation-mismatch is an ABSOLUTE force-OFF that even `MCP_ENABLED=true` cannot override** (reconciles the env>DB precedence with §14.9); first boot with no out-of-band id AND `enabled=true` is treated as untrusted → force OFF + alert (never auto-adopt the DB's `installation_id`).

### 15.11 Live-protection test watches the RIGHT victim (devops R2-F11; perf)
- The gating assertion is **live order-placement p95 and reconciler cycle time UNAFFECTED during a max sweep** (not merely MCP read p95). The breaker's input SLIs (event-loop lag, scanner cycle, reconciler/order latency, pool-wait) are a BLOCKING enable-preflight dependency — enable fails unless every breaker input is present and emitting on `/metrics` (some are NEW instrumentation work: loop-lag watchdog, pool-wait wiring).

**Round 2 status:** Round-1 Criticals confirmed resolved; Round-2 findings folded in (no remaining Critical; the Highs were ProcessPool/pool-budget hardening + doc-consistency, all addressed above).

### 15.12 Shared-memory backing-store safety (Round 3 — new High R3-F1 + shm-seam mediums)
The §15.1 shared-memory snapshot is backed by `/dev/shm` (tmpfs), whose default container size is **64 MB** — far below the sub-512 MB snapshot budget. `ftruncate` is lazy on tmpfs, so allocation succeeds but the first PARENT write past the tmpfs cap raises **SIGBUS** (uncatchable) → the live trading process (which builds the snapshot) crashes. Binding resolutions:
- **Enable-preflight + per-sweep-build gate** free backing-store space ≥ the snapshot budget; hard-fail the sweep with a CATCHABLE error (e.g. `posix_fallocate` to force early `ENOSPC`) — never a late SIGBUS. The deploy runbook mandates container `--shm-size` / tmpfs ≥ the snapshot RSS budget; enable is gated on it.
- **Build columnar arrays directly into the shm buffer OFF the event loop** (a one-off thread/executor), so the pack/copy never stalls the live loop at sweep start; the §15.11 gating test measures live order p95 across sweep STARTUP, not just steady-state; budget the transient build spike.
- **`BrokenProcessPool` is an EXPECTED outcome** of the high `oom_score_adj` design (kernel kills a worker): detect → backoff/shed (no tight recreate) → resume from the completed-config-hash set, REUSING the live shm snapshot (never rebuild on-loop). The watchdog/breaker sheds BEFORE kernel OOM; kernel-kill is the backstop.
- **The memory watchdog reads cgroup-v2 `memory.current` vs `memory.max`** (whole-cgroup footprint incl. worker interpreters + shmem), NOT parent-process RSS (which under-counts workers) — mandated, not optional.
- **`max_connections` preflight enumerates EVERY source explicitly:** `live_pool_max + mcp_pool_max(if separate) + leader_lock + listen_notify + migration`, × instances; a test asserts the gate FAILS when the separate MCP pool is omitted.
- **POSIX-only priority levers guarded:** `os.nice`/`oom_score_adj` are no-ops on Windows dev (else the worker initializer crashes); documented as Linux-deploy-only.
- **Worker count clamped `max(1, cores−1)`;** on ≤2-core hosts, refuse to enable sweeps (or force serial in-process-with-yield) — state the minimum core count for enabling MCP.
- **Deterministic shm cleanup:** `close()`+`unlink()` in `finally`/`atexit` on the parent; boot-recovery unlinks orphaned MCP shm segments; handle/disable the resource_tracker for attach-only workers (prevents `/dev/shm` leak across crashes feeding the SIGBUS risk).
- **Leader-lock reconnect:** the §15.3 liveness loop reconnects the dropped dedicated lock connection and retries acquire with backoff (TCP keepalives set) before requiring a supervised restart (resilience).

### 15.13 Editorial corrections (Round 3 Low — applied)
- `kill_epoch BIGINT NOT NULL DEFAULT 0` added to `mcp_config` (§4.1), bumped ONLY by disable/kill/tier-downgrade; `config_epoch` = config/propagation, `kill_epoch` = the TOCTOU fence signal (§15.5).
- `run_one` canonical signature is `run_one(config, signals, snapshot, instrument_info, *, deadline) -> metrics` (§15.6) — ADR-8 and §14.4's earlier `(…, klines, …)` wording defers to this.
- §14.3's "audit-BEGIN reserves correlation_id only" (not seq) and "kill_epoch fence for mutating OR exchange-facing tools" are the binding pipeline wording (§15.4/§15.5 govern).
- §6's `source=mcp_sweep` tagging applies only in the OPTIONAL persist mode (§15.6 makes per-combo `backtest_runs` rows OFF by default).

**Round 3 status:** Architecture reviewer — "converged, no remaining Critical/High". The one new High (R3-F1 /dev/shm SIGBUS) and its shm-seam mediums are folded into §15.12; editorial leftovers into §15.13.

### 15.14 Provable money-path & secret-path enforcement (Round 4 security Highs R4-F1..F4)
Round 4 confirmed every obvious path is terminated, but flagged four load-bearing controls whose strength rested on UNVERIFIED assumptions. Binding resolutions make them provable, not just asserted:
- **Worker env scrub (R4-F1, was a false isolation claim):** `spawn` copies the parent `os.environ` into every sweep worker, so `ACCOUNTS_ENCRYPTION_KEY`, `DATABASE_URL`, `MCP_TOKEN`, and `*_API_KEY` are present despite "workers receive only klines+config." The `ProcessPoolExecutor` **initializer MUST pop/scrub all secret env vars** in each worker (the pure engine needs none). A worker test asserts `os.environ` contains no secret canary; the positive leak test plants a canary in `ACCOUNTS_ENCRYPTION_KEY` and asserts it never appears in any worker output/shm.
- **Deny-list names the REAL money sinks (R4-F2):** the registration deny-list is extended beyond config/token/audit to ALL real-money/exchange sinks explicitly — `update_scheduled_scan`/`create_scheduled_scan` (writes the live auto-trade config) and every exchange-mutating `accounts_service` method (order placement / `set_leverage` / cancel). A **call-graph test** asserts NO registered tool reaches `update_scheduled_scan` or any exchange order/leverage method EXCEPT the control-plane approve handler; the `scheduled/`, `trades/`, `accounts/` tool groups are pinned read-only.
- **Metadata-vs-behavior integrity (R4-F3):** a static/behavioral CI check FAILS the build when a handler's call graph reaches `bybit_rate_gate`/`update_scheduled_scan`/exchange sinks without the correct `exchange_facing|mutating` flag + tier — so a mis-flagged tool cannot be exposed at READ_ONLY or skip the fence. The `kill_epoch` re-check is enforced AT the `bybit_rate_gate` acquire chokepoint (not only at dispatch-entry), closing the yield-between-dispatch-and-exchange-call TOCTOU window.
- **Allow-list is an explicit literal, fail-closed on new fields (R4-F4):** `SWEEPABLE_FIELDS` is a hand-maintained literal `frozenset`, NOT derived from an AutoTradeConfig flag (a derived flag would auto-admit a future live-enabling field). A CI test FAILS when `AutoTradeConfig` gains ANY field not explicitly classified allow/deny; allowed fields must be scalar or recursively allow-listed (nested sub-models like `close_rules[]`); Pydantic aliases are normalized before the membership check. (Note: `update_scheduled_scan` is a PARTIAL update that can target an already-live-enabled scan, so the sanity ceiling + server verdict robustness carry the load there.)
- **Resource/prompt leak coverage (R4-F5, Medium):** the positive leak test extends to `resources/read` and `prompts/get` outputs; the `config`/`portfolio` resources enumerate exactly what they expose and assert no `access_token_hash`/`installation_id`/secret/key-reference fields.
- **No raw-PID kill (R4-F6, Medium):** `sweep_cancel`/kill signals managed `Process`/`Future` handles owned by the executor, never `os.kill(pid)` on a raw PID (PID reuse could SIGKILL the live process); liveness verified before signaling.
- **Principal-scoped sweep reads now (R4-F7, Low):** `sweep_status`/`sweep_results` queries filter by calling `principal_token_id` (no-op under the MVP single bearer, correct for P6 multi-token — prevents a UUID-guesser reading another principal's strategy configs).

### 15.15 shm preflight implementation note (Round 4 perf)
The §15.12 shm free-space gate assumes `posix_fallocate` actually reserves tmpfs pages (closing the TOCTOU→SIGBUS window). The implementation MUST verify this on the deployment OS — `shm_open`+`ftruncate` alone is lazy; if `posix_fallocate` on the shm fd does not force allocation on the target tmpfs, fall back to writing zero-pages across the segment at build time (still off-loop) so any `ENOSPC` surfaces as a catchable error before fan-out, never as a late SIGBUS during a combo.

**Round 4 status:** Architecture/perf/devops converged across R1–R3 (live-process-disruption paths closed). Round-4 security found 4 Highs (env-scrub, money-sink deny-list, metadata-vs-behavior, literal allow-list) — all folded into §15.14 as provable/tested controls. These are enforcement guarantees on already-designed controls, introducing no new architecture.
