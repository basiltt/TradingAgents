# Specification: MCP Server (AI Agent Integration)

## A. Title and Metadata

- **Feature:** MCP (Model Context Protocol) Server for AI-Agent control of the TradingAgents app
- **Date:** 2026-06-07
- **Author:** Claude (via `/new-feature`)
- **Status:** Final — passed spec review (3 rounds; backend/QA + product/integration + consistency all converged). Ready for implementation planning.
- **Related user request:** "Create an MCP server to connect to the trading agents app and perform activities by an AI agent — basic features + extensive backtesting + debugging; the agent runs backtests with varying parameter combinations to find the optimal config; toggleable on/off via the UI (default off); and (because too many tools saturate the model's context) enable/disable groups or individual tools."
- **Related modules:** `backend/mcp/` (new), `backend/main.py`, `backend/async_persistence.py`, `backend/services/backtest_service.py`, `backend/services/kline_cache_service.py`, `backend/routers/`, `frontend/src/routes/route-tree.tsx`, `frontend/src/components/layout/navigation.ts`, `frontend/src/api/client.ts`, `frontend/src/components/mcp/` (new)
- **Related files:** `specs/mcp-server-requirements.md` (586 reqs), `specs/mcp-server-architecture.md` (5 review rounds)
- **Version:** 0.1 (MVP = Phases P0–P4)

## B. Discovery Summary

- **Stack:** FastAPI (Python 3.12, asyncio, asyncpg) backend; React 18 + TypeScript + Vite + TanStack Router/Query + zod v4 frontend; PostgreSQL; LangGraph multi-agent engine.
- **App factory & lifespan:** `backend/main.py:create_app()` registers routers in the function body and wires services onto `app.state.*` inside `lifespan` (DB pool created there, not at body time).
- **Toggle precedent (debug feature):** `debug_config` singleton table (`id INT PK CHECK(id=1)`, `tracing_enabled BOOLEAN`), availability gate `getattr(app.state, "debug_trace_recorder", None) → HTTPException(503)`, `GET/PUT /debug/config`, lifespan degrades to `None` on init failure (never aborts startup).
- **Security middleware (app-wide):** `CSPCSRFMiddleware` (POST/PATCH/PUT/DELETE require `X-Requested-With: XMLHttpRequest` else 403), `ContentSizeLimitMiddleware` (1 MB body cap), CORS allow-list, `ObservabilityMiddleware` (3 s slow-request log).
- **Backtest subsystem:** `app.state.backtest_service` (BacktestService) runs backtests as background asyncio tasks (`_running_tasks` strong-ref set + done-callback), `_MAX_CONCURRENT=3`, `ThreadPoolExecutor(3)`, `_TIMEOUT=120s`, raises `BacktestBusy/RateLimit/Validation/NotFound/Conflict`; engine is pure-Python candle iteration; `BacktestCreateRequest` (~40 tunable fields) is the optimizer's parameter surface. `kline_cache_service.get_klines` is a DB round-trip (no in-memory cache).
- **Migrations:** versioned `_MIGRATIONS: list[tuple[int, sql|callable]]` in `async_persistence.py`, advisory-locked `_apply_migrations`, per-version transaction, current max version = 42 → MCP lands at 43.
- **Frontend:** routes in `route-tree.tsx` (lazy + createRoute + addChildren); nav in `navigation.ts` (System section); API client `client.ts` (`request`/`mutate`, `DEFAULT_HEADERS` already sets the CSRF header); neumorphism `@/components/ui` primitives.
- **Money discipline:** the codebase coerces money via `Decimal(str(x))` (NUMERIC columns) — floats capture IEEE error on money paths.
- **Constraints:** real-money Bybit trading shares the process/event-loop/DB-pool/`bybit_rate_gate` with this feature → the live-trading loop must never be degraded; default OFF; localhost only (MVP).

## C. Feature Overview

- **What:** An embedded MCP server (official `mcp` Python SDK / FastMCP, streamable-HTTP) mounted on the existing FastAPI app, exposing the app's capabilities as MCP **tools / resources / prompts** for an external AI agent (Claude Desktop, Claude Code, or any MCP client), plus a server-side **parameter-sweep optimizer** that runs many backtests to find the optimal `AutoTradeConfig`. A React `/mcp` operator page controls it.
- **Why:** Let an AI agent drive scans/accounts/positions/trades/portfolio/analytics reads, the backtesting subsystem, and the debugging routes — and autonomously search the config space for a better trading configuration than the one currently running.
- **Who:** (1) the **operator** (human) — enables the feature, configures the tool budget, connects a client, approves config proposals; (2) the **agent** (machine) — calls tools over `/mcp/rpc` with a bearer token.
- **Problem solved:** manual config tuning is slow; the agent can systematically sweep parameters and surface a robust, baseline-beating config — while the human retains the sole authority to apply it to real money.
- **Expected outcome:** a default-OFF, context-budget-aware, security-hardened MCP integration whose headline capability is "find me the optimal AutoTradeConfig for our current setup," delivered as a human-reviewable proposal.

## D. Business Goal

- **Objective:** turn config optimization from a manual chore into an agent-driven workflow, and give the app a standard machine interface.
- **User value:** discover better-performing, robustness-checked trading configs; drive the app from an AI assistant.
- **Operational value:** off-by-default with zero overhead when disabled; never destabilizes live trading; full audit trail.
- **Success definition:** with MCP enabled and the Minimal/Backtest presets active, an agent connects, runs a parameter sweep, and returns a baseline-beating `AutoTradeConfig` proposal that the operator reviews and (optionally) applies — with the live-trading loop measurably unaffected (order-placement p95 within baseline during a max sweep) and zero secret leakage.

## E. Current System Behavior

- **No machine interface:** the app is driven only by its React UI + REST API; there is no MCP server, no programmatic agent control surface.
- **Backtesting** exists (UI + `/api/v1/backtest*`) but is human-initiated one config at a time; there is **no parameter sweep / optimizer**.
- **Debugging** routes exist (`/api/v1/debug/*`) for auto-trade trace forensics, gated by `debug_config.tracing_enabled` + the recorder availability gate.
- **Config** (`AutoTradeConfig`) for the Scheduled Scanner is edited via the UI and persisted via `AsyncAnalysisDB.update_scheduled_scan(schedule_id, fields)`; there is no propose/approve/diff/revert workflow and no server-side config-sanity ceiling beyond the Pydantic model validators.
- **Limitations / pain points:** config tuning is manual and unsystematic; no audit of programmatic actions; no standard way to connect an AI agent.
- **Codebase references:** `routers/backtest.py`, `services/backtest_service.py`, `routers/debug.py`, `services/debug_trace_repository.py`, `async_persistence.py` (migrations + `update_scheduled_scan`), `main.py` (lifespan/middleware).

## F. Expected New Behavior

- **New workflow (operator):** open `/mcp` → read the explainer → enable (security-warning confirm + preflight gate) → pick a tool preset (default Minimal/read-only) → copy the generated client-config snippet → connect an MCP client → watch the activity feed → review/approve/revert config proposals.
- **New workflow (agent):** connect over streamable-HTTP with `Authorization: Bearer <token>` → `initialize` (reads `instructions` steering it to the optimizer) → `tools/list` (only the enabled subset) → call read tools / `sweep_estimate` → `optimize_config(objective, constraints)` or `sweep_run` → poll `sweep_status`/`sweep_results` → receive a best-config **proposal** + deep link → hand off to the human (the agent CANNOT apply).
- **API behavior:** a JSON-RPC data-plane at `/mcp/rpc` (bearer, not in OpenAPI, CSRF-exempt); a same-origin control-plane at `/api/v1/mcp/*` (existing app auth, 503 when feature absent).
- **Frontend behavior:** a new `/mcp` route + System nav entry with a status badge; sections Overview/Tools/Connection/Safety/Optimizer/Activity/Proposals.
- **Backend behavior:** `backend/mcp/` package; the transport + control-plane mounted via a two-phase `register_mcp`/`mcp_boot`; a `SweepOrchestrator` (ProcessPool, shared-memory snapshot) driving `BacktestService.run_one`; repositories for `mcp_config`/audit/sweep/proposal.
- **Data behavior:** six new `mcp_*` tables (v43) + additive `backtest_runs.source/sweep_id`; singleton config seeded `enabled=false`; hash-chained audit; sweep results streamed per-combo.
- **Validation behavior:** every tool input validated by a Pydantic model (`extra=forbid`); `backtest_run` schema generated from `BacktestCreateRequest`; the apply path runs allow-list sanitize → sanity ceiling → existing validators.
- **Error behavior:** tool execution failures → JSON-RPC `isError:true` + agent-readable remediation; protocol errors → standard `-327xx` codes; feature OFF → 503; auth failure → 401 fail-closed.

## G. Scope

### In Scope (MVP — Phases P0–P4)
- Embedded FastMCP streamable-HTTP transport at `/mcp/rpc`; control-plane REST at `/api/v1/mcp/*`; SPA page at `/mcp`.
- Master ON/OFF toggle (default OFF, DB singleton + env override), 503 gate, kill-switch, preflight + dry-connect self-test on enable.
- Tool registry (decorator self-registration), tool-group + individual enable/disable, presets (Minimal/Standard/Full/Read-only/Backtest-only as predicates), context-budget meter.
- **Read tools** (P1): scans, accounts (redacted), positions, trades, portfolio, analytics, scheduled, strategies/config, symbols. **Resources** (`tradingagents://scan/latest`, config, portfolio, server/info) + **prompts** (static).
- **Backtest tools** (P3): `backtest_run/get/list/compare`, kline cache warmup/status.
- **Debug tools**: trace forensics reads (gated by `allow_debug`).
- **Optimizer** (P4): `sweep_estimate`, `sweep_run`, `sweep_status`, `sweep_results`, `sweep_cancel`, composite `optimize_config`; grid + random search; baseline backtest of the live config; uplift ranking; null-result honesty; robustness verdict (basic); proposal generation.
- **Apply workflow**: agent proposes → `mcp_proposals` → operator approves on `/mcp` (allow-list sanitize → sanity ceiling → validators → `update_scheduled_scan`) → diff/revert.
- Bearer auth (single hashed token), localhost bind, Host/Origin allowlist, capability-tier ceiling, per-call audit (hash-chained), rate limiting, output caps, redaction-by-default, secret leak test.
- Multi-worker safety (single-worker-when-enabled + advisory-lock corruption guard), live-trading resource protection (separate ProcessPool, reserved DB floor, RSS/loop breaker).
- Observability (Prometheus metrics into existing `/metrics`, health sub-status), runbooks (enable/connect/rotate/disable/decommission).

### Out of Scope (MVP)
- **LIVE-MONEY trade tools** (placing/closing real orders via MCP) — forbidden by default; not built in MVP.
- Advanced optimizer: coarse-to-fine/smart search, Pareto, walk-forward/IS-OOS, sensitivity analysis, Monte Carlo CIs, multi-regime validation (R-19/23/24/25/323/324 — P5).
- Shadow/paper probation, staged capital rollout, cross-session refine, adopted-config predict-vs-actual tracking, optimization-memory champion, generated md/PDF report (P5).
- Multiple per-client tokens, enforced token TTL, remote (non-localhost) binding + TLS, retention encryption-at-rest, GDPR tombstoning, adaptive circuit-breaker (P6).
- `resources/subscribe` + live `notifications/resources/updated`, `completion/complete` (P5).
- i18n/localization (English-only).

### Future Scope (P5/P6 — seamed, not built)
- The `mcp_tokens` table is created empty; `bind_host`/`MCP_ALLOW_REMOTE_BIND` retained; `principal_token_id` columns present; the `Transport`/`TokenAuthenticator` interfaces and a basic breaker hook exist so P5/P6 drop in without re-architecting.

## H. Functional Requirements

Mapped from the 586-requirement catalogue (R-###). Grouped by area; each is testable.

### Toggle & Lifecycle
- **FR-001:** The MCP integration MUST default to OFF on a fresh DB (singleton `mcp_config.enabled=false`, absent row reads as disabled). [R-35/41/42]
- **FR-002:** When OFF, the JSON-RPC transport MUST NOT be mounted (no sessions/handlers); a tiny always-mounted gate route at `/mcp/rpc` returns 503 "feature disabled". [R-36/37, C1]
- **FR-003:** Enabling MUST pass a preflight gate (token set+strong, loopback bind, `read_only=true`, zero mutating/live tools, migrations at expected version, single-worker-or-leader, DB-pool/`max_connections` budget, shm free-space) and a dry-connect self-test; any failure keeps it OFF. [R-506/507, §15.2/15.12]
- **FR-004:** A kill-switch (UI + headless + `MCP_ENABLED=false` env) MUST disable the server, drop sessions, cancel in-flight sweeps, reachable even under a saturated event loop (out-of-band path). [R-39/426, §14.11]
- **FR-005:** MCP init failure MUST degrade `app.state.mcp_server=None` and NEVER abort trading startup. [R-84/207]
- **FR-006:** Enable/disable is hot (no process restart) via the indirection-Mount ref-swap; tool-group/individual changes use registry filtering (no rebuild). [R-44, ADR-7]

### Tool Budget
- **FR-007:** The server MUST advertise ONLY the enabled tool subset; disabled tools are absent from `tools/list` AND rejected at dispatch (`-32601`). [R-45/53/100/187]
- **FR-008:** Tool groups AND individual tools MUST be independently enable/disable-able; most-restrictive resolution wins. [R-45/46/52]
- **FR-009:** Presets (Minimal/Standard/Full/Read-only/Backtest-only) MUST be predicates over registry metadata, auto-classifying new tools; Minimal/first-enable contains ZERO mutating tools. [R-47/381/382/307]
- **FR-010:** The UI MUST show a live "N tools enabled" count and an estimated context-cost (token) meter within ±10% of the actual advertised-schema token count, with a warning threshold. [R-48/49/56/467]

### Core Tools / Resources / Prompts
- **FR-011:** Read tools MUST exist for scans, accounts (redacted), positions, trades, portfolio, analytics, scheduled-scans, strategies/current-config, symbols — each calling existing side-effect-free service methods (or new thin read-only repository methods), never re-running a scan. [R-1..9/269]
- **FR-012:** MCP resources MUST expose stable low-cost reads (`tradingagents://scan/latest`, config, portfolio, server/info) and static prompts for guided journeys. [R-14/15]
- **FR-013:** Every read tool MUST default to a compact `summary` projection with `detail` opt-in, top-N + drill-down (default ≤20), keyset pagination, and bounded output. [R-16/461/500/129]

### Backtest Tools
- **FR-014:** `backtest_run` MUST create a backtest via `BacktestService`, its input schema generated from `BacktestCreateRequest` (build-time equivalence test); `backtest_get/list/compare` and kline `cache_status/warmup` MUST exist. [R-10/11/12/70]

### Optimizer
- **FR-015:** `sweep_estimate(space)` MUST return combo count, ETA, and cache gaps BEFORE running; oversized grids (> `max_sweep_backtests`=5000) are refused pre-flight. [R-18/31/493]
- **FR-016:** `sweep_run`/`optimize_config` MUST run grid or random search across config combinations, deduped by canonical config-hash, ranked by a chosen objective metric, returning top-N. [R-17/19(grid+random only)/21/32/254/255]
- **FR-017:** The optimizer MUST baseline the CURRENT live `AutoTradeConfig` through the same harness and report each candidate's uplift (Δreturn/ΔmaxDD/ΔSharpe/Δexpectancy) vs baseline. [R-313/314/316]
- **FR-018:** When no candidate **robustly beats** the baseline, the optimizer MUST return "keep current config" and crown NO winner. **"Robustly beats" (MVP bar):** `Δobjective ≥ min_uplift_pct` (default 5% relative) **AND** `candidate.min_trades ≥ guardrail.min_trades` (default 30) **AND** `candidate.max_drawdown ≤ baseline.max_drawdown` **AND** robustness verdict (FR-020) ≠ `fragile`. A candidate MUST satisfy BOTH the agent-supplied constraints (FR-039, applied first to exclude) AND this bar. All thresholds config-driven with the stated defaults. [R-312]
- **FR-019:** Every reported metric MUST trace to a stored result with provenance (config-hash, date range, seed); the agent MUST NOT surface an untraceable number. [R-320]
- **FR-020:** The optimizer MUST surface the backtest-fidelity caveat (~1% deviation, in-sample-only for MVP) and a **robustness verdict** computed from a named check set, each classified **hard-fail** or **soft-fail**:
  - `trade_count_sufficient` (candidate.min_trades ≥ guardrail.min_trades, default 30) — **HARD**
  - `drawdown_not_worse` (candidate.max_drawdown ≤ baseline.max_drawdown) — **HARD**
  - `not_single_trade_dominated` (the single best trade contributes < 40% of gross PnL) — **SOFT**
  - `uplift_above_noise` (Δobjective ≥ min_uplift_pct, default 5% relative) — **SOFT**
  Grade: `robust` = all pass; `moderate` = only soft-fail(s); `fragile` = any HARD fail. Results are deterministic for identical inputs. [R-321/318/34]
- **FR-021:** A `sweep_id`-based fire-and-poll handle MUST let an agent disconnect and a later session reattach to an in-flight/finished sweep; `sweep_cancel` cancels and persists partial results. [R-494/26/81]

### Apply / Proposal
- **FR-022:** The optimizer MUST emit a winning config as a `mcp_proposals` row (status `pending`) with a `proposal_id` + deep link; the agent can ONLY propose. The proposal MUST carry a **target `schedule_id`** and the **auto-trade-config selector/index** identifying WHICH scheduled scan (and which entry in its `scan_config.auto_trade_configs[]` list) the config would apply to. [R-27/498/582, R1-F1]
- **FR-023:** Applying a proposal MUST require human approval in the `/mcp` UI (no tool argument can satisfy the gate) and run **allow-list sanitize → absolute sanity ceiling → construct the FULL prospective `AutoTradeConfig` (current ⊕ patch) and run the model's cross-field validators on THAT → read-merge-write** the targeted entry back into `scheduled_scans.scan_config` via `update_scheduled_scan`. The apply MUST be atomic and drift-guarded: reject if `target_schedule_id IS NULL`; bounds-check `0 ≤ target_config_index < len(auto_trade_configs)`; compare the current `auto_trade_configs[index]` against `mcp_proposals.diff.before` and **coerce-or-reject on mismatch** (the list was reordered/edited since propose); guard the whole read-merge-write under optimistic concurrency on the `scheduled_scans` row (read-back compare or row-version) to prevent a lost update of a concurrent scan edit. Validating only the patch (not the merged config) is forbidden. [R-282/284/538/539, §15.5/15.14, R1-F1/F6, R2-F2]
- **FR-024:** The approval screen MUST render a server-computed risk verdict (independent of the agent), a segregated "agent-generated, unverified" rationale panel, a field-level live→proposed diff with high-risk flags, per-high-risk-field acknowledgment + typed-confirm, and applied-config version history with one-click revert. [R-535/536/537/326/329/585]
- **FR-025:** A pending proposal MUST expire after a bounded TTL; expired/stale-schema proposals cannot be applied (coerce-or-reject). [R-586/573]

### Security / Auth
- **FR-026:** Every `/mcp/rpc` request MUST present a valid bearer token (constant-time hash compare) else 401 fail-closed; no anonymous path. [R-87/89/92]
- **FR-027:** The transport MUST validate Host against a loopback allowlist (`127.0.0.1`/`localhost`/`::1`) and reject a non-loopback Origin (absent Origin allowed for local bridges) — DNS-rebinding defense. [R-277/278, §15.8]
- **FR-028:** The capability tier (READ_ONLY→BACKTEST→MUTATING_DEMO→LIVE_MONEY) MUST be the single authoritative ceiling, re-read per call; LIVE_MONEY is forbidden without a separate explicit opt-in (not built in MVP). [R-96/97/98/101, ADR-5]
- **FR-029:** A registration-time deny-list MUST bar wrapping sensitive methods as tools (config/token/kill-switch/audit writers, `update_scheduled_scan`/`create_scheduled_scan`, exchange order/leverage methods); a call-graph test enforces no tool reaches a money sink except the approve handler. [R-288, §15.14]
- **FR-030:** Tool outputs, errors, logs, audit, resource reads, and ProcessPool worker outputs MUST never contain Bybit keys, `ACCOUNTS_ENCRYPTION_KEY`, the MCP token, or DB credentials — enforced by a canonical deny-list + positive leak test; sweep workers MUST have secrets scrubbed from `os.environ`. [R-553/554, §15.14]
- **FR-031:** Account balances and absolute P&L MUST be aggregated/redacted by default; raw figures require a separate financial-detail opt-in. [R-296]
- **FR-032:** Every tool invocation MUST be audited (hash-chained, single serialized writer, redacted args, correlation id, outcome, duration); both data-plane and control-plane appends go through the one writer. [R-112/113, §15.4]
- **FR-033:** Enabling MUST record a one-time data-egress consent (tool results leave to the connected model provider); a persistent `/mcp` notice reminds the user. [R-551]

### Multi-worker / Resource Protection
- **FR-034:** When enabled, the supported topology MUST be single-worker; multi-worker uses an advisory-lock leader (on a dedicated never-pooled connection) as a corruption guard, with non-leaders degraded. [R-400/401/402, ADR-9, §15.3]
- **FR-035:** MCP/sweep DB acquisitions MUST be capped below the pool max with a measured live-floor reserved for the trading loop; raising `DB_POOL_MAX` is gated by a `max_connections` budget check. [R-292/293, §15.2]
- **FR-036:** Sweep CPU work MUST run in a separate `ProcessPoolExecutor` (spawn, shared-memory columnar snapshot, ≤cores−1 workers, `os.nice`/`oom_score_adj`) so the live event loop is never CPU-starved; a watchdog sheds sweeps before kernel OOM. [R-292/294(basic), §15.1/15.12]
- **FR-037:** Exchange-facing MCP calls (kline fetches) MUST acquire the shared `bybit_rate_gate` in a subordinate lane with a reserved live floor; a 429/ban breaker halts MCP fetches first. [R-235/548/549]
- **FR-038 (Debug — spec-review R1-F1):** Debug/forensics READ tools (trace-by-scan / by-account / by-symbol, read `debug_config`) MUST exist, gated behind an `allow_debug` flag (default OFF), redacted (credential-shaped keys stripped, per the debug-repo precedent), depth/size-capped, returning the same trace data the debug UI exposes. [R-13/211/133]
- **FR-039 (Optimizer constraints — R1-F4):** `optimize_config`/`sweep_run` MUST accept agent-supplied constraints (max drawdown, min trades, min win-rate) that EXCLUDE violating configs BEFORE ranking; the supported objective-metric set is enumerated: total_return, sharpe, sortino, max_drawdown (minimize), win_rate, profit_factor, expectancy, calmar — with documented tie-breakers (secondary metric → config hash). [R-21/22/32]
- **FR-040 (Sweep history — R1-F9):** Stored sweep results MUST be re-rankable by an alternate stored objective metric without re-running the sweep (revisit/compare later). [R-28]

## I. Non-Functional Requirements

- **NFR-001 (Perf — read tools):** Read-tool latency p50 < 50 ms, p95 < 200 ms in-process — and the p95 MUST hold WHILE a max sweep fans out (backed by the reserved DB floor + ProcessPool isolation). [R-353, §15.11]
- **NFR-002 (Perf — live protection):** During a max sweep, live order-placement/reconciler latency MUST stay within the gate: **p95 ≤ 1.15× the stored pre-enable baseline AND p99 ≤ 1.3× baseline AND max single-cycle < a hard bound**, over **N ≥ 500 samples**, measured via a **synthetic order/reconciler-latency fixture** in CI (live-money isn't built, so the fixture exercises the shared reconciler/order-prep loop path); the baseline is captured just before enable; the breaker-input live-SLIs are a hard enable-preflight prerequisite (FR-003). This is the gating assertion for RK-1 (missed-stop = real money), so the tail (p99/max) is bounded, not just p95. [§15.11, R2-F4]
- **NFR-003 (Perf — audit):** Audit write MUST add < 5 ms p95 to a tool call (non-blocking queued writer). [R-357]
- **NFR-004 (Perf — context budget):** Advertised-schema token budgets: Minimal ≤ 2,000, Standard ≤ 8,000, Full ≤ 20,000; per-tool schema ≤ ~500 tokens; estimate within ±10% (BPE-referenced, biased upward). [R-358/458]
- **NFR-005 (Perf — sweep):** A 5000-combo sweep streams results to DB incrementally; sweep snapshot held columnar in shared memory under a budgeted RSS; throughput is candle-count-relative — **the gate is 5000 combos < 60 s with the FakeRunner (≈85/sec orchestration)**; ~500 combos/sec is a non-asserted aspirational ceiling; a real sweep is minutes–~1 hr (benchmarked in CI, no hardcoded "/sec/core" claim). [R-354/355, §14.13, R2-F5]
- **NFR-006 (Security):** Default OFF = zero attack surface (unmounted); default tier READ_ONLY; no live-money path without separate opt-in; fail-closed everywhere; secrets never logged/returned. [R-37/97/123/553]
- **NFR-007 (Reliability):** MCP MUST never crash the live-trading process (separate process pool, env force-OFF, RSS watchdog, out-of-band kill, degrade-to-None). [R-84, §15.1/15.11/15.12]
- **NFR-008 (Reliability — recovery):** A backend restart mid-sweep MUST recover (`running`→`interrupted`, resume by completed-config-hash set), never leave a sweep perpetually `running`. [R-86/209/276]
- **NFR-009 (Maintainability):** All MCP code in `backend/mcp/`; one-way dependency (nothing outside imports it except the single mount call), import-linter enforced; decorator self-registration so adding a tool edits ONE module; removal = delete the package + one mount line. [R-372/373/376/483]
- **NFR-010 (Observability):** MCP metrics emit into the existing `/metrics`; `/api/v1/health` carries an `mcp` sub-status (degraded ≠ 503); audit completeness == 1.0. [R-415/420/367]
- **NFR-011 (Compatibility):** Adding MCP (even OFF) MUST add zero behavior change and < 50 ms startup overhead to the existing app; the existing test suite passes unchanged; tool contracts are additive-only once published. [R-362/363/247]
- **NFR-012 (Data integrity):** Money values use `Decimal(str(x))` at every persist boundary; NaN/Inf → NULL; per-combo result writes are individually committed. [R-434/435/263, §15.7]
- **NFR-013 (Accessibility):** The `/mcp` page passes an axe/jsx-a11y gate + keyboard-nav + contrast checks in both themes. [R-578/174/177]
- **NFR-014 (Portability):** Prod-OS (Linux) CI runs the MCP suite incl. e2e, coexistence soak, SIGTERM drain, uvloop/signal/lock-release parity; loopback allowlist includes `::1`; no hardcoded Windows paths. [R-529/530/531]

## J. User Flows

### J.1 Primary — Operator enables MCP and connects a client
1. Operator opens `/mcp` (OFF state): explainer panel ("what is MCP / what can the agent do / why tool budget matters") + a single Enable CTA.
2. Clicks Enable → security-warning dialog (lists exposed capabilities + data-egress consent) → confirm.
3. Backend runs the preflight gate + dry-connect self-test → on success transitions to ON; on failure stays OFF and shows the failed invariant.
4. Page reveals the control surface: Tools (preset = Minimal/read-only), Connection (endpoint URL + masked token + copy + "Copy client config" snippet), Status, Safety, Optimizer, Activity, Proposals.
5. Operator copies the client-config snippet, pastes into Claude Desktop (`mcp-remote` bridge) / Claude Code (`--header`), runs on the same host.
6. Agent connects → activity feed shows `initialize` + `tools/list`.

### J.2 Primary — Agent finds the optimal config
1. Agent `initialize` (reads `instructions`) → reads current config + scan-data ranges + cache coverage (resources/read tools).
2. Agent calls `sweep_estimate(space)` → reviews combo count/ETA/cache gaps → narrows the space.
3. Agent calls `optimize_config(objective="sharpe", constraints={max_dd<15, min_trades>=30})` → receives a `sweep_id`.
4. Agent polls `sweep_status` (progress) then `sweep_results` (top-N, baseline uplift, robustness verdict, fidelity caveat).
5. Agent receives a best-config **proposal** (`proposal_id` + deep link) → tells the operator "review at <link>"; the agent CANNOT apply.

### J.3 Primary — Operator reviews & applies a proposal
1. Operator opens the proposal (pending-proposal nav badge → inbox → proposal screen).
2. Screen shows: server-computed risk verdict; segregated unverified-agent-rationale; field-level live→proposed diff with high-risk flags; baseline vs winner equity/DD curves.
3. Operator acknowledges each high-risk field, types ENABLE if the server flagged it "unusually risky", clicks Approve.
4. Backend runs allow-list sanitize → sanity ceiling → existing validators → `update_scheduled_scan`; snapshots the prior config (version history).
5. Toast "config applied"; the live Scheduled Scanner now uses the new config. One-click Revert restores the prior config (re-run through the pipeline).

### J.4 Tool-budget management
1. Operator opens Tools section → expandable group cards (master toggle + "X of Y enabled") → per-tool checkboxes with safety-class badges + tooltips.
2. Picks a preset or customizes; the live token-budget meter updates client-side; over-threshold shows a non-blocking warning.
3. Clicks Save (unsaved-changes guard) → `tools/list_changed` fires; connected agents re-pull the (smaller/larger) toolset.

### J.5 Failure / edge flows
- **Enable preflight fails** → stays OFF, shows which invariant failed (e.g. "shm free space < snapshot budget; set --shm-size").
- **Feature OFF, agent connects** → 503 "feature disabled".
- **Invalid/expired token** → 401, generic error.
- **Sweep oversized** → `sweep_estimate`/`sweep_run` rejects pre-flight with "reduce ranges or use random search".
- **No candidate beats baseline** → "keep current config", no winner.
- **Live-trading health degrades mid-sweep** → breaker sheds the sweep; activity feed notes it; live loop unaffected.
- **Restored DB clone** → installation-mismatch forces OFF + token rotation regardless of env.

## K. API Requirements

### K.1 Data-plane (JSON-RPC over streamable-HTTP)
- **Path:** `POST/GET /mcp/rpc` (+ `Mcp-Session-Id`). **Auth:** `Authorization: Bearer <token>` (FR-026). **Not in OpenAPI**, CSRF-exempt (exact `/mcp/rpc` subtree), ContentSizeLimit-exempt (own bounded read, JSON-RPC error on over-cap), Origin/Host allowlisted.
- **Methods:** `initialize` (serverInfo+capabilities⊆implemented+instructions, protocolVersion `2025-06-18` negotiate-down), `tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources/templates/list`, `prompts/list`, `prompts/get`, `ping`, `notifications/{tools/list_changed,progress,cancelled,initialized}`.
- **Tool naming:** `group_action` (`scans_list`, `scans_get`, `backtest_run`, `sweep_run`, `optimize_config`), immutable once published.
- **Annotations & capabilities:** `tools/list` emits MCP tool annotations (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`/`title`) derived from registry `safety_class`/`mutating`; `initialize` advertises `capabilities.tools.listChanged=true`, `resources.subscribe=false` (P5 deferral); supported `protocolVersion` set has an explicit floor+ceiling (e.g. `2025-03-26`..`2025-06-18`), negotiate-down-not-error; a missing/older `MCP-Protocol-Version` header from a local bridge is handled leniently (not hard-rejected). [R-228/223/224, R2-F4/F6]
- **Errors:** execution → `isError:true`+content; protocol → `-32700/-32600/-32601/-32602/-32603`+server range; disabled tool → `-32601`.

### K.2 Control-plane (REST, same-origin, existing app auth + CSRF, 503 when feature absent)
| Method | Path | Purpose | Codes |
|--------|------|---------|-------|
| GET | `/api/v1/mcp/config` | enabled subset, tier, budget estimate | 200/503 |
| PATCH | `/api/v1/mcp/config` | optimistic-concurrency update (toggle groups/tools/tier/safe-mode) | 200/409/403(env-managed)/503 |
| GET | `/api/v1/mcp/tools` | FULL registry (name/group/desc/safety_class/mutating/annotations/input_schema/est_tokens) + presets | 200/503 |
| POST | `/api/v1/mcp/enable` | preflight-gated OFF→ON | 200/422(preflight)/409 |
| POST | `/api/v1/mcp/disable` | + `?kill=true` | 200 |
| POST | `/api/v1/mcp/token/regenerate` | rotate bearer (drops sessions) | 200 |
| GET | `/api/v1/mcp/status` | running/leader/sessions/last-error + **pending_proposals count** | 200/503(module absent) |
| GET | `/api/v1/mcp/health` | ops probe (200 when OFF) + `pending_proposals` | 200 |
| GET | `/api/v1/mcp/audit` | keyset activity feed | 200 |
| GET | `/api/v1/mcp/sweeps` / `/{id}` / `/{id}/results?objective=<metric>` | sweep list/detail/full results (keyset); `objective` re-ranks stored rows server-side (FR-040) | 200/404 |
| POST | `/api/v1/mcp/sweeps/{id}/cancel` | cancel a running sweep | 200/404/409 |
| GET | `/api/v1/mcp/proposals` / `/{id}` | proposal list / detail+diff+verdict | 200/404 |
| POST | `/api/v1/mcp/proposals/{id}/{approve,reject,revert}` | human apply/reject/revert | 200/409/422 |
| POST | `/api/v1/mcp/test-connection` | in-process ASGI self-test (no socket) | 200 |

- **Backward compatibility:** all paths are NEW; the `/mcp/rpc` mount + middleware exemptions MUST NOT alter existing endpoints (regression test: a non-`/mcp/rpc` POST without `X-Requested-With` still 403s; OpenAPI unchanged).

## L. UI/UX Requirements

- **Route/nav:** new `/mcp` route + `/mcp/proposals/$proposalId` child route (mirrors `/backtest/$runId`, makes the FR-022 deep link implementable); System-section nav entry "AI Agent (MCP)" with a status dot (green/gray/red) + pending-proposal badge — shown in the mobile **System section header** (the dock is a fixed 4-item allowlist, NOT mirrored there); the nav status query is NOT mounted/polled until enabled (seeded from the one-shot `/api/v1/health` `mcp` field, backs off on 503) to keep the OFF path zero-overhead. [R-134/135/136, R2-F1/F3/F5]
- **Page:** per-section components (`frontend/src/components/mcp/`): Overview/Status, Tools, Connection, Safety, Optimizer, Activity, Proposals — `ui/tabs` desktop, accordion mobile; neumorphism `@/components/ui` primitives; dark/ivory parity. [R-137/177/491]
- **States:** loading skeletons, OFF/empty hero, error, saving spinners, 503 "module unavailable" panel, success toasts (`sonner`). [R-170/171]
- **Tool budget:** group cards (tri-state master toggle + count), per-tool checkboxes + safety badges + tooltips, preset selector, select-all/none, sticky "N enabled" + token meter, search/filter, explicit Save + unsaved-changes guard. [R-143..151/172]
- **Connection:** endpoint URL + copy; masked token (reveal only in the one-time post-generation window) + copy + Regenerate(confirm); ready-to-paste client-config snippet (`ui/tabs` per client) + "Test connection". [R-154..158, C6]
- **Safety:** access-mode segmented control; red "Allow live-money" toggle (default OFF, typed-confirm) — but live-money tools not built in MVP, so the toggle is present-but-inert with a "P6" note; persistent data-egress notice. [R-163/164/551]
- **Proposals:** the Apply-Proposal review screen (FR-024) + pending-proposal inbox/badge, reached via `/mcp/proposals/$proposalId`. [R-585]
- **Optimizer:** sweep-monitoring screen — sweep list (status/progress via polling `GET /api/v1/mcp/sweeps`), per-sweep detail (top-N results + uplift vs baseline + robustness verdict + fidelity caveat), a **re-rank-by-metric control** (`?objective=` on `/sweeps/{id}/results`, FR-040), cancel-with-confirm; states `running/interrupted/failed/empty`. [R-166..169/585]
- **Activity:** the audit/activity feed — filterable by tool/group/outcome, keyset-paginated from `GET /api/v1/mcp/audit`, with empty/loading/error states; rows expand to redacted args/result summary. [R-160/161]
- **Disable / Kill-switch:** controls in the Overview/Status section — Disable (confirm + result toast) and Kill-switch (`POST /disable?kill=true`, warns of dropped sessions + cancelled sweeps). [R-39/FR-004]
- **Validation messages:** inline on the sweep form / config edits; copy-to-clipboard confirmations; confirm dialogs for all destructive/elevated actions. [R-178]
- **A11y:** keyboard nav of the tool matrix, `role=switch`/`aria-checked`, `aria-expanded`, live-region for the budget counter, focus management on dialogs. [R-174/175]
- **Type safety:** `/mcp` API responses validated with zod v4 schemas mirroring backend Pydantic; no `any`. [R-478]

## M. Backend Requirements

- **Package:** `backend/mcp/` with `core/` (transport, registry, dispatch, auth, audit, shape, errors, context_budget, ping), `tools/<group>/`, `resources/`, `prompts/`, `repositories/`, `schemas.py`, `router.py`, `mount.py` (`register_mcp`+`mcp_boot`), `manage.py`. [§3.1]
- **Integration seam:** `register_mcp(app)` in `create_app` body (permanent indirection Mount + control-plane router, reads nothing); `mcp_boot(app)` in lifespan AFTER migrations/scanner-resume (leader lock, read config, boot-recovery, build transport). [§14.1]
- **Services reused (in-process):** `BacktestService` (new `run_one(config,signals,snapshot,instrument_info,*,deadline)` + additive `source/sweep_id`), `kline_cache_service` (shared store), `bybit_rate_gate`, `AsyncAnalysisDB.update_scheduled_scan` (apply-owner). [§14.4/15.6, ADR-12]
- **Dispatch pipeline (canonical, applied to every handler):** host/origin → auth → rate-limit → tier-gate → kill_epoch-fence (mutating|exchange_facing, at the `bybit_rate_gate` chokepoint) → audit-begin(correlation_id) → timeout(handler) → audit-end → error-map → shape/redact. [§14.3/15.5/15.14]
- **Sweep:** `tools/optimizer/` with `ComboGenerator` (pure), `SweepRanker` (pure), `SweepRunner` (ProcessPool fan-out + shm snapshot), thin `SweepOrchestrator` (lifecycle). [ADR-8, §15.1]
- **Repositories:** `MCPConfigRepository`, `AuditRepository` (single serialized writer), `SweepRepository`, `ProposalRepository` — all SQL here, typed domain objects out. [R-250/253]
- **Error handling:** central exception→JSON-RPC table with retryable flags; dispatcher catch-all → generic internal-error envelope (logged), never crash the session. [R-264/265]
- **Patterns followed:** mirror the debug feature (availability gate, degrade-to-None, repo style); migrations append to `_MIGRATIONS`; schemas re-exported into `backend/schemas`; `from __future__ import annotations` + full type hints, mypy --strict. [R-387/477]

## N. Database/Data Requirements

**Migration v43** (callable, advisory-locked, one transaction): creates SIX tables + indexes + singleton seed (full column definitions in architecture §4). A SEPARATE additive migration adds `backtest_runs.source TEXT NOT NULL DEFAULT 'ui'` + `sweep_id UUID` + index.

- **`mcp_config`** (singleton `id=1`): `enabled` (default false), `bind_host`, `access_token_hash`, `capability_tier`, `enabled_groups/enabled_tools/safe_mode_flags` (JSONB, fail-safe defaults), `config_schema_version`, `row_version` (optimistic concurrency), `config_epoch` + `kill_epoch`, `installation_id`, `audit/sweep_retention_days`, `updated_at`. Seed `INSERT … VALUES (1) ON CONFLICT DO NOTHING`; boot repairs an incomplete row to fail-safe + forces OFF. [R-444/445/447, §4.1]
- **`mcp_sweep_jobs`**: `id UUID`, `status` CHECK enum (incl. `interrupted`), `param_space JSONB`, `objective_metric`, `total/completed_combos` (CHECK), `best_result_id` (deferrable FK), `idempotency_key` (partial-unique by principal+session), `principal_token_id`, timestamps. [R-432/436/448]
- **`mcp_sweep_results`**: `sweep_id` FK CASCADE, `config JSONB` (decimal-string money), `config_hash CHAR(64)` UNIQUE(sweep_id,config_hash), `backtest_id UUID` FK SET NULL (NULL by default — §15.6), `metrics JSONB` — **MUST store the full FR-039 objective-metric superset** (all 8: total_return/sharpe/sortino/max_drawdown/win_rate/profit_factor/expectancy/calmar, decimal-string, NaN/Inf→null) so FR-040 re-rank works for any metric; `objective_value NUMERIC(20,8)` (the primary objective, NaN/Inf→NULL), `result_rank` (relative to the original objective), `created_at`. [R-433/434/435/437/439, R2-F2]
- **`mcp_audit_log`**: `seq BIGINT UNIQUE`, `prev_hash/entry_hash`, `tool_name/tool_group/safety_class/mutating`, `principal_token_id/session_id/correlation_id`, `args_redacted JSONB`, `sensitive_payload BYTEA` (Fernet via `ACCOUNTS_ENCRYPTION_KEY`), `status` CHECK, `error`, `started_at`, `duration_ms`. Hash over canonical plaintext. Indexes: `(started_at DESC)`, `(session_id, started_at DESC)`, `(tool_name,tool_group,status)`, BRIN `(started_at)`. [R-430/453/454/452]
- **`mcp_proposals`**: `id UUID`, `sweep_id` FK SET NULL, **`target_schedule_id TEXT` FK → `scheduled_scans(id)` ON DELETE SET NULL** (which scan to apply to), **`target_config_index INT`** (which entry in `scan_config.auto_trade_configs[]`), `config JSONB` (the allow-listed patch, decimal-string money), `diff JSONB` (carries the FULL prior `AutoTradeConfig` for revert), `status` CHECK enum, `approver`, `applied_config_version`, `risk_verdict JSONB`, `created_at`, `expires_at`. The apply path does **read-merge-write**: read current `scan_config`, splice the allow-listed fields into `auto_trade_configs[target_config_index]`, validate the merged config, write the whole `scan_config` back. [R-582/586, §4.5, R1-F1]
- **`mcp_tokens`** (modeled, empty in MVP): id/name/token_hash/scope/principal/expires_at/revoked_at/created_at. [C5]
- **Migration safety:** `IF NOT EXISTS` everywhere; additive-only (zero-downtime); forward-only (rollback = manual drop + decrement, documented); version-collision CI gate (43 contiguity, blocking — just-merged features make this a real race). Retention purge runs OUTSIDE `backend/mcp/` (scheduler/pg_cron) so code removal doesn't stop it. [R-440/442/512/521, §14.10]
- **Integrity:** money `Decimal(str(x))`; JSONB shapes validated by versioned Pydantic models on write+read + cheap `jsonb_typeof` CHECKs.

## O. Integration Requirements

- **MCP SDK (FastMCP, official `mcp` ≥1.12):** streamable-HTTP; override its defaults (bind/auth/CORS/session caps); disable verbose/debug; enumerate+lock down auto-registered routes (legacy `/sse`, message, inspector, `.well-known`) behind auth+allowlist; CSPRNG session ids. Hash-pinned in the lockfile; pip-audit CVE + SBOM + license gate in CI. [R-289/290/291/555/556/575/581]
- **BacktestService:** the ONLY backtest engine; sweeps drive `run_one` (bypasses `_load_klines`/instrument-resolve/buy-hold-fetch, accepts the shm snapshot incl. BTC for buy-hold parity); sweep-spawned backtests optionally tagged `source=mcp_sweep`. [§14.4/15.6]
- **Kline cache:** MCP warmup writes the SAME store/keys as BacktestService, with a coexistence quota protecting the live path. [R-243/516]
- **Bybit:** klines only (no live orders from MCP in MVP) via the shared rate gate, subordinate lane, reserved live floor, 429/ban breaker. [R-548/549]
- **External clients:** Claude Desktop (`mcp-remote` stdio↔HTTP bridge, same host), Claude Code (`--header`, same host); `Authorization: Bearer` only; loopback-only MVP. [R-244/245/281, §15.8]
- **Idempotency:** mutating/sweep submissions deduped by client-supplied key (TTL+session-scoped). [R-124/304]

## P. Security Requirements

(Consolidated from FR-026..033, §8, §15.5/15.14 — the money-path and secret-path are "provably closed" per the final security review.)
- **Auth:** bearer (CSPRNG ≥256-bit, hashed, constant-time compare, never logged/returned); 401 fail-closed; first-enable force-generates a strong token; localhost bind + Host/Origin allowlist + DNS-rebind guard. [R-87..94/277/278/306]
- **Authz:** capability-tier ceiling re-read per call; default READ_ONLY, zero mutating/live tools; live-money forbidden (not built MVP); registration deny-list (config/token/kill/audit writers + money sinks) with a call-graph test; metadata-vs-behavior CI check; `kill_epoch` TOCTOU fence at the rate-gate chokepoint. [R-96..101/288/305, §15.14]
- **Apply path:** human-only out-of-band approval; allow-list (literal frozenset, fail-closed on a new AutoTradeConfig field, recursion/alias-safe) sanitize → absolute sanity ceiling → existing validators → `update_scheduled_scan`; server-computed risk verdict; revert re-runs the pipeline. [R-282/284/535/538/539, §15.5/15.14]
- **Secrets:** canonical deny-list + positive leak test over results/errors/logs/audit/resources/prompts/worker-output/shm; worker `os.environ` scrubbed of secrets; audit `sensitive_payload` encrypted; outputs use opaque internal ids. [R-553/554, §15.14]
- **Input validation:** Pydantic `extra=forbid`; symbols allow-listed; ids UUID-validated (tools AND resource URIs); parameterized SQL only; untrusted free-text fenced + injection-neutralized. [R-102..107/532..534/544]
- **Audit:** hash-chained, single serialized writer, append-only, redacted, both planes; completeness == 1.0. [R-112/113, §15.4]
- **Abuse/DoS:** per-token rate limit; stricter exchange-facing throttle; sweep caps (combos, concurrency, uncached-fetch volume); output size caps; data-egress consent + per-session volume budget. [R-116/117/118/120/297/550/551]
- **CSRF/CORS:** the `/mcp/rpc` exemption is exact-prefix with headers preserved; control-plane keeps CSRF; CORS never reflects arbitrary origins. [§14.7]

## Q. Performance Requirements

- **Load:** ≤ 8 concurrent sessions, ≤ 2 concurrent sweeps (MVP caps); read tools dominate volume.
- **Response times:** NFR-001/002/003 (read p50<50/p95<200 ms incl. under sweep; live order p95 within baseline; audit <5 ms).
- **Caching:** symbols/sectors/config cached short-TTL with single-flight + invalidate-on-config-change; financial/position data not cached stale. [R-464, perf-F11]
- **Pagination:** keyset everywhere; equity ≤1000 pts (LTTB), trade page ≤500, summary payload ≤256 KB. [R-356]
- **Background:** sweeps as ProcessPool + background asyncio tasks; cold-start pays a one-time kline pre-warm (UI surfaces "warming"). [R-466]
- **Large datasets:** 50k-trade backtest paginated/truncated; huge debug trees depth/size-capped. [R-211/133]

## R. Logging, Monitoring, Observability

- **Log:** structured, `MCP_LOG_LEVEL` (default INFO), per-call correlation_id linking request→service→backtest→audit; token scrubbed. NEVER log secrets/token/args-with-secrets. [R-126/421]
- **Metrics (into existing `/metrics`):** `mcp_tool_calls_total{tool,group,status}`, `mcp_tool_latency_seconds`, `mcp_sweeps_active`, `mcp_sweep_throughput`, `mcp_active_sessions`, `mcp_audit_queue_depth`, `mcp_audit_completeness`, `mcp_rate_limited_total`, `mcp_circuit_breaker_state`, `mcp_enabled`(always 0/1), `mcp_leader`. Plus the live-SLI inputs the breaker needs (event-loop lag, scanner cycle, reconciler/order latency, pool-wait) — a blocking enable-preflight dependency. [R-420, §15.11]
- **Health:** `/api/v1/health` gains `mcp:{enabled,state,leader,active_sessions,last_error_at}` (degraded≠503, read from cache); `/api/v1/mcp/health` ops probe (200 when OFF); `/healthz` stays MCP-agnostic. [R-415/416]
- **Alerts:** tool_error_rate, audit_queue near cap, breaker open, audit_completeness<1.0, auth-failure spike, stuck sweep, leader-lock lost, enable-window live-SLI regression (auto-disable). [R-422, §14.11]
- **Audit UI:** activity feed (filterable by tool/group/outcome), reproduce-from-audit procedure. [R-160/368]

## S. Edge Cases

(From the requirements' edge-case catalogue R-180..216 + review findings.)
- **Toggle:** enable mid-sweep; disable mid-tool-call (clean error); rapid on/off (no zombie/port churn); OFF persists across restart; fresh DB reads OFF; toggle OFF cancels in-flight calls + persists running sweeps to `interrupted`; kill-switch hard-cancels everything. [R-182..185, C13]
- **Tool budget:** disable a group while its tool executes; `tools/list` changes mid-session (one `list_changed`); direct call to a disabled tool (`-32601`); enable zero tools (valid empty list); enable all tools (max budget computed). [R-186/187/53]
- **Optimizer:** empty search space (reject); single-point (one backtest); combinatorial explosion (cap/refuse pre-flight); all backtests fail (`failed` + diagnostics); metric ties (deterministic tie-break: secondary metric → config hash); NaN/Inf (quarantine, sort last); cancel midway (retain partial); invalid combos skipped + reported; rate-limit backpressure; date range with no scan data (explicit empty, not a fake zero-trade success); missing kline cache (precise "cache miss"). [R-188..200]
- **Concurrency:** two clients; concurrent sweeps; concurrent config writes (row_version optimistic); sweep vs UI backtest sharing the rate limiter (fair); audit appends serialized. [R-201..204, §15.4]
- **Failure:** DB lost mid-call (prompt service-unavailable); BacktestService None (defined error); MCP init fails (isolated, app starts); client network drop (session cleanup); restart mid-sweep (recover); long tool timeout (partial-result ref); Bybit 429/ban (breaker); bind port in use (clear error, app survives); `/dev/shm` too small (catchable ENOSPC at preflight, never SIGBUS); BrokenProcessPool from oom-kill (shed/resume). [R-205..213, §15.12]
- **Auth:** missing/expired/malformed token (401); token rotated mid-session (re-challenge); installation-mismatch clone (force OFF). [R-212/456]
- **State:** illegal sweep transitions rejected; proposal expiry; stale-schema proposal (coerce-or-reject). [R-215/586/573]
- **Multi-worker:** WEB_CONCURRENCY>1 + enabled (refuse-mount or leader; non-leaders degrade); kill-switch reaches all workers; leader-lock survives >300s idle (dedicated conn); leader death → standby. [R-400..404, §15.3]
- **Money/data integrity:** decimal-string round-trip lossless; applied-config == backtested-config; combo hashes deterministic. [§15.7]

## T. Testing Requirements

- **Unit (no transport/DB):** every tool handler with fake services + ctx; `FakeBacktestRunner` (<1 ms/call); `ComboGenerator`/`SweepRanker` pure; registry/preset resolution; allow-list/sanitize; config-budget token counting. [R-339/340/222/223]
- **Property (Hypothesis ≥1000):** combo generator (count==product, zero dupes, in-bounds, cap at exactly 5000); random search (N distinct, seed-reproducible); toggle/registry state machine (most-restrictive, never a disabled tool, round-trips). [R-349/350/351]
- **Contract:** per-tool advertised schema == `Pydantic.model_json_schema()`; registry-completeness (schema/handler/safety_class/error-map/audit/mutating per tool + group + preset membership); error-mapping golden snapshot; capabilities ⊆ implemented; tool-contract golden-snapshot CI diff-gate (additive vs breaking). [R-346/347/348/525, §14.8]
- **Integration (in-memory ASGI, no port):** `initialize→tools/list→tools/call`; session lifecycle/isolation/teardown; resources/prompts surface; control-plane CRUD; CSRF-exemption regression (non-`/mcp/rpc` POST still 403s; OpenAPI unchanged). [R-344/345/562, §14.7]
- **Security:** DNS-rebind (forged Host / bad Origin rejected); registration deny-list (build fails if a money-sink/sensitive method is wrapped); call-graph (no tool reaches `update_scheduled_scan`/exchange except approve handler); metadata-vs-behavior build-fail; apply-sanitization (allow_real_trades/live-binding stripped or rejected); allow-list fail-on-new-field; TOCTOU epoch-fence; redaction-by-default; positive secret leak test (incl. worker env/output/shm + resources/prompts); restore-safety (clone forces OFF). [R-566..572, §15.14]
- **Perf/load:** read p50/p95 (isolation AND under a max sweep); **live order-placement p95 / reconciler cycle within baseline during a max sweep (the gating assertion)**; audit <5 ms non-blocking; preset token budgets (2k/8k/20k ±10%); 5000-combo FakeRunner <60 s + no leaked task; 50 calls+5 sweeps no PoolTimeout; soak 10k calls+1k toggles RSS<50 MB; real-engine micro-benchmark publishes the throughput curve; shm RSS assertion on the deploy OS. [R-353..361, §15.11]
- **Regression:** OFF-path zero-overhead (<50 ms startup delta, no MCP task, single config read); behavioral-equivalence (existing suite unchanged with MCP present-but-OFF); core-trading isolation (force MCP init to raise → app starts, `mcp_server is None`). [R-362/363/364]
- **E2E (slow, Linux CI, ephemeral port):** real streamable-HTTP client initialize→list→read-tool→tiny sweep→completed; whole-feature scenario (enable→connect→sweep→best config→propose→human approve→diff persisted→revert); generated client-config snippet actually connects. [R-365/366/559/561]
- **Acceptance:** headline-outcome (golden sweep → known winner with uplift/rationale/verdict/provenance/proposal); null-result honesty. [R-559/560]
- **Migration:** v43 applies under the real `split(";")`/callable runner; reserved-word columns OK; reapply idempotent; partial-failure full-rollback; 43 contiguity gate; backtest_runs additive migration. [R-574/509/512]
- **Manual verify (per release):** real Claude Desktop + Claude Code interop; live-money-opt-in copy renders (inert in MVP); a11y in both themes. [R-564/565]
- **Coverage target:** 90%+ on `backend/mcp/` and `frontend/src/components/mcp/`.

## U. Acceptance Criteria

- **AC-001 (FR-001/002):** Given a fresh DB, when the app starts, then `mcp_config.enabled=false`, `/mcp/rpc` returns 503, and no MCP background task exists.
- **AC-002 (FR-003):** Given an enable request that fails any preflight invariant (e.g. shm < budget), when submitted, then the feature stays OFF and the response names the failed invariant.
- **AC-003 (FR-007/009):** Given the Minimal preset, when `tools/list` is called, then only read-only tools appear, zero mutating tools, and a disabled tool called by name returns `-32601`.
- **AC-004 (FR-010):** Given the operator toggles tools, when the enabled set changes, then the "N enabled" count and token meter update client-side and stay within ±10% of the actual advertised-schema token count.
- **AC-005 (FR-015/016/017):** Given a valid search space over the live config, when `optimize_config` runs, then it baselines the current config, runs grid/random combos, and returns top-N ranked by uplift vs baseline.
- **AC-006 (FR-018):** Given a space where nothing beats the baseline, when the sweep completes, then it returns "keep current config" and no winner.
- **AC-007 (FR-018/019/020):** Given the committed golden sweep (fixed seed, fixed `max_workers=1`, pinned objective), when it runs, then the crowned winner == the expected config-hash and satisfies the full FR-018 bar (Δobjective ≥ 5% AND min_trades ≥ 30 AND no DD regression AND verdict ≠ fragile); every reported metric carries provenance + a robustness verdict + the fidelity caveat; identical inputs reproduce identical rankings (deterministic tie-break exercised).
- **AC-008 (FR-022/023):** Given a winning config, when the agent finishes, then a `pending` `mcp_proposals` row + deep link is produced and the agent cannot apply it; applying requires human approval running sanitize→ceiling→validate.
- **AC-009 (FR-024):** Given a proposal with a high-risk field change (leverage 5×→50×), when the operator opens it, then the screen shows a server-computed risk verdict, a segregated agent-rationale panel, the diff with the field flagged, and requires per-field ack + typed-confirm; revert restores the prior config.
- **AC-010 (FR-029/030):** Given the build, when CI runs, then it FAILS if any tool wraps a money sink/sensitive method or a worker exposes a secret canary in env/output/shm.
- **AC-011 (NFR-002):** Given a max sweep running, when measured over N≥500 samples via the synthetic order/reconciler fixture, then live order-placement/reconciler latency stays within the gate — p95 ≤ 1.15× the stored pre-enable baseline AND p99 ≤ 1.3× baseline AND max single-cycle < the hard bound.
- **AC-012 (NFR-007):** Given MCP init forced to raise, when the app starts, then trading startup succeeds with `app.state.mcp_server is None`.
- **AC-013 (FR-026/027):** Given a request with a missing/invalid token or a forged Host/non-loopback Origin, when received at `/mcp/rpc`, then it is rejected (401 / blocked) fail-closed.
- **AC-014 (FR-034/035/036):** Given WEB_CONCURRENCY>1 + enabled, when the app boots, then exactly one leader serves (others degraded), the leader lock survives >300 s idle, and MCP DB acquisitions never breach the reserved live floor.
- **AC-015 (NFR-011):** Given MCP present-but-OFF, when the existing test suite runs, then it passes unchanged and startup overhead is < 50 ms.
- **AC-016 (FR-014, backtest — R1-F2):** Given a valid `BacktestCreateRequest`, when `backtest_run` is called, then a run is created via `BacktestService`, `backtest_get` returns status→result, `backtest_compare` returns the standard metric set, and the advertised input schema equals `BacktestCreateRequest.model_json_schema()`.
- **AC-017 (FR-011, read tools — R1-F3):** Given a completed scan, when `scans_get` is called, then it returns the stored ranked signals WITHOUT invoking the scanner, and account-listing tools return redacted balances (ratios, not raw) by default.
- **AC-018 (FR-038, debug — R1-F1):** Given `allow_debug=false` (default), when a debug tool is called, then it is unavailable/denied; given `allow_debug=true`, it returns redacted trace data depth/size-capped.
- **AC-019 (FR-004, kill-switch):** Given an enabled server under a saturated event loop, when the operator triggers the kill-switch (or `MCP_ENABLED=false`), then the server disables, sessions drop, and in-flight sweeps cancel via the out-of-band path.
- **AC-020 (FR-025, proposal expiry):** Given a `pending` proposal past its TTL (virtual clock), when apply is attempted, then it is rejected as expired; a proposal computed under an older config schema is coerced-or-rejected, never silently applied.
- **AC-021 (FR-032, audit integrity):** Given a tampered audit row, when chain verification runs, then the tamper is detected; given interleaved tool-call + proposal-approve, the single writer keeps the chain continuous (no fork).
- **AC-022 (FR-033, egress consent):** Given a first enable, when completed, then a data-egress consent is recorded exactly once and a persistent `/mcp` notice is shown.
- **AC-023 (NFR-008, recovery):** Given a backend killed mid-sweep, when it restarts, then the sweep is `interrupted` then resumed by the completed-config-hash set, never left perpetually `running`.
- **AC-024 (FR-039, optimizer constraints):** Given a constraint `max_drawdown ≤ 15%`, when a config breaching it is evaluated, then it is EXCLUDED from ranking and never crowned winner; given an unsupported objective metric, the sweep is rejected with a clear error.
- **AC-025 (FR-040, re-rank):** Given a completed sweep with the full metric superset stored, when `GET /sweeps/{id}/results?objective=sortino` is called, then the rows are re-sorted by sortino server-side (stable order) without re-running the sweep.
- **AC-026 (FR-023, apply drift guard):** Given a proposal whose `target_config_index` no longer matches the stored `diff.before` (list reordered/edited since propose), when approve is attempted, then it is rejected (coerce-or-reject); a concurrent scan edit during read-merge-write does not cause a lost update.

## V. Risks

| ID | Risk | Sev | Likelihood | Mitigation |
|----|------|-----|-----------|------------|
| RK-1 | A sweep degrades the live-trading loop (CPU/DB/memory) → missed stops = real money | Critical | Medium | Separate ProcessPool (spawn, ≤cores−1, nice/oom_score_adj), reserved DB floor + max_connections gate, shm-size preflight, RSS/loop breaker, live-order-p95 gating test (NFR-002) |
| RK-2 | A prompt-injected agent reaches real money via the apply path | Critical | Low | Human-only out-of-band approval, allow-list (fail-closed on new field), absolute sanity ceiling, server risk verdict, money-sink deny-list + call-graph test |
| RK-3 | Secret leakage (Bybit keys / token / encryption key) to the agent | High | Low | Worker env scrub + canary test, deny-list + positive leak test over all surfaces, audit encryption, token never returned |
| RK-4 | Split-brain under multi-worker (double sweeps/audit fork) | High | Low | Single-worker-when-enabled + advisory-lock leader on a dedicated never-pooled connection + liveness loop |
| RK-5 | Real backtest throughput far below expectation → sweeps take >1 hr, poor UX | Medium | High | Honest candle-relative SLOs, `sweep_estimate` ETA up-front, random search + caps, CI micro-benchmark; UX surfaces ETA + completion push |
| RK-6 | MCP SDK behavior/version drift breaks interop or opens a default route | Medium | Medium | Pin SDK version (hash-locked), enumerate+lock down auto-routes, capabilities⊆implemented test, real-client interop sign-off |
| RK-7 | Migration v43 version collision with concurrently-merged features | Medium | Medium | Blocking contiguity CI gate; renumber on collision; idempotent DDL |
| RK-8 | Orphan `mcp_*` table growth after feature removal | Medium | Low | Retention purge lives OUTSIDE `backend/mcp/` (scheduler/pg_cron); documented decommission runbook |
| RK-9 | Context-budget meter under-reports → agent context saturates anyway | Low | Medium | BPE-referenced count biased upward, ±10% test against real `tools/list` |
| RK-10 | Operator approval fatigue rubber-stamps a risky config | Medium | Medium | Per-field ack + typed-confirm for risky configs, standout non-dismissible warning, cool-down between applies |

## W. Assumptions

- **A-001:** *Assumption:* The official `mcp` Python SDK's FastMCP supports embedding as an ASGI sub-app on an existing FastAPI app with streamable-HTTP and a manually-driven session manager. *Risk:* Medium. *Reason:* This is the SDK's documented embedding pattern. *Impact if wrong:* fall back to a standalone localhost process (ADR-1 alternative) — more wiring, same tools.
- **A-002:** *Assumption:* `posix_fallocate` (or zero-page write) forces tmpfs allocation so shm over-budget surfaces as a catchable `ENOSPC`. *Risk:* Medium. *Reason:* standard tmpfs behavior. *Impact if wrong:* use a file-backed snapshot store sized by preflight (§15.15).
- **A-003:** *Assumption:* The deployment runs a SINGLE uvicorn worker when MCP is enabled (or the operator accepts the leader-only serving model). *Risk:* Low. *Reason:* stated topology. *Impact if wrong:* non-leader workers 503 nondeterministically — preflight refuses enable.
- **A-004:** *Assumption:* `AutoTradeConfig`'s sweepable fields are a stable, enumerable set that rarely gains live-enabling fields. *Risk:* Low. *Reason:* the model is mature. *Impact if wrong:* the fail-on-new-field CI test forces an explicit allow/deny classification before merge (by design).
- **A-005:** *Assumption:* The live-trading SLI metrics the breaker needs (event-loop lag, scanner cycle, reconciler/order latency, pool-wait) can be exported to `/metrics`. *Risk:* Medium. *Reason:* some may not exist yet. *Impact if wrong:* that instrumentation is in-scope prerequisite work gating enable (§15.11).
- **A-006:** *Assumption:* Money fields in `BacktestCreateRequest` (typed `float`) can be coerced losslessly via `Decimal(str(x))` at the persist boundary. *Risk:* Low. *Reason:* established codebase pattern. *Impact if wrong:* widen the model to accept string money.

## X. Open Questions

- **Q-001:** *Question:* Single uvicorn worker in the target deployment, or must MCP serve under multi-worker in MVP? *Why:* determines whether the advisory-lock leader is only a guard (MVP) or must include sticky sessions + shared session store (P6 pulled forward). *Recommended default:* single-worker-when-enabled; preflight refuses multi-worker. *Impact if unanswered:* proceed with the default.
- **Q-002:** *Question:* Is in-sample-only optimization acceptable for MVP, with walk-forward/OOS deferred to P5? *Why:* affects how strongly the "robustness verdict" can be trusted. *Recommended default:* yes — MVP ships with a loud "in-sample only, not validated" caveat (FR-020) and defers walk-forward. *Impact if unanswered:* proceed with the default.
- **Q-003:** *Question:* Should the MVP expose the live config-apply path at all, or ship optimize-and-propose only (no apply) first? *Why:* the apply path is the sole money bridge and the highest-risk surface. *Recommended default:* ship propose+human-apply (the apply path is heavily gated and is the feature's payoff), but it can be feature-flagged off to ship optimize-only first. *Impact if unanswered:* proceed with propose+human-apply behind its own sub-flag.

## Y. Traceability Matrix (summary — full map maintained in Step 16)

| Requirement area | Spec FR/NFR | Arch home | Plan phase | Key tests | AC |
|------------------|-------------|-----------|-----------|-----------|-----|
| Toggle/lifecycle | FR-001..006, NFR-007 | ADR-4, §14.1 | P0 | OFF-path, isolation, preflight | AC-001/002/012 |
| Tool budget | FR-007..010, NFR-004 | ADR-7, registry | P2 | registry-completeness, budget ±10%, property | AC-003/004 |
| Core read tools | FR-011..013, FR-031 | tools/<group>, §3.1 | P1 | per-tool contract, redaction | AC-003/017 |
| Debug tools | FR-038 | tools/debug, allow_debug | P3 | allow_debug gate, redaction | AC-018 |
| Backtest tools | FR-014 | §14.4 | P3 | schema-equivalence | AC-016 |
| Optimizer | FR-015..021, FR-039/040, NFR-005 | ADR-6/8, §15.1 | P4 | golden sweep, property, constraint-exclude, re-rank | AC-005/006/007/024/025 |
| Apply/proposal | FR-022..025 | ADR-12, §15.5, mcp_proposals | P4 | apply-sanitization, allow-list, drift-guard | AC-008/009/020/026 |
| Security | FR-026..033, P | §8, §15.14 | P0-P4 | deny-list, leak, DNS-rebind, TOCTOU, audit-integrity, consent | AC-010/013/021/022 |
| Multi-worker/resource | FR-034..037, NFR-002 | ADR-9, §15.1/15.2 | P0/P4 | leader, pool floor, live-order p95/p99 | AC-011/014/023 |
| Data | N, NFR-012 | §4 | P0 | migration, decimal round-trip | — |
| Observability | R, NFR-010 | §9, §14.11 | P0-P4 | metrics, health, audit completeness | — |
| Compatibility | NFR-011 | §14 | all | regression, behavioral-equivalence | AC-015 |

## Z. Definition of Ready

- ✅ Scope clear (MVP P0–P4; P5/P6 explicitly deferred + seamed).
- ✅ Requirements testable (every FR/NFR maps to a §T test; a representative high-risk subset has explicit ACs, AC-001..026).
- ✅ Edge cases documented (§S, from R-180..216 + review findings).
- ✅ Codebase impact understood (§B/§M/§N reference real files; additive-only [non-breaking] to shared code, with acknowledged additive changes to BacktestService + bybit_rate_gate per §AA.2).
- ✅ Dependencies identified (FastMCP SDK, BacktestService changes, live-SLI instrumentation, shm sizing).
- ✅ Risks documented (§V, with mitigations).
- ✅ Acceptance criteria measurable (§U, AC-001..026).
- ✅ No unresolved Critical/High (architecture converged over 5 review rounds; money/secret paths provably closed). Open questions have recommended defaults.

**Status: READY for spec review (Step 5).**

---

## AA. Spec Review Round 1 Revisions (High/Medium findings folded in)

Binding refinements from spec-review Round 1 (5 reviewers). These ADD to / sharpen the sections above.

### AA.1 Apply-path target & merged validation (backend R1-F1/F6 — CRITICAL)
`AutoTradeConfig` lives inside `scheduled_scans.scan_config->'auto_trade_configs'` (a LIST), written via `update_scheduled_scan(schedule_id, {scan_config: <whole blob>})`. The apply path therefore: (1) `mcp_proposals` carries `target_schedule_id` + `target_config_index` (FR-022/§N); (2) approve does read-merge-write — read `scan_config`, splice allow-listed fields into `auto_trade_configs[index]`, construct the FULL prospective `AutoTradeConfig` and run its cross-field validators on the MERGED result (not the patch), then write the whole `scan_config` back (FR-023). Test: a patch valid alone but invalid when merged → rejected.

### AA.2 Acknowledged additive changes to shared live components (backend R1-F4/F5)
Beyond `BacktestService` (already flagged), §M/§O acknowledge two MORE additive changes to shared real-money components — NFR-011's "additive-only" is scoped to "no BREAKING change," these are additive-with-tests:
- **`bybit_rate_gate`** gains a subordinate lane + reserved live floor + 429/ban breaker (`BybitRateGate.acquire_async` currently takes only `channel`); a test asserts the live lane is never starved by MCP. [FR-037]
- **`BacktestService` concurrency** refactors the bare `_active_slots` counter into a shared async gate both UI and sweep acquire (sweep bounded below `_MAX_CONCURRENT`); a test asserts UI-path behavioral-equivalence (reserved UI slots). [§14.4]

### AA.3 Data-integrity hardening (backend R1-F2/F3/F8/F9)
- NaN/Inf normalize to JSON `null` (or omitted) INSIDE `metrics`/`config` JSONB too (not only `objective_value`), enforced by the versioned Pydantic-on-write validator (`Decimal(str(float('nan')))`→`"NaN"` would otherwise slip through). [NFR-012]
- The circular sweep FK is created by `CREATE both tables → ALTER ADD the deferrable FK` (Postgres has no `ADD CONSTRAINT IF NOT EXISTS` for FKs); the one ALTER is guarded (`DROP CONSTRAINT IF EXISTS` first / catch duplicate_object), and the "reapply-idempotent" claim is scoped to the version-ledger preventing re-run. [§N]
- The `backtest_runs` `source`/`sweep_id` migration is its OWN contiguous version (e.g. 44), ordering-independent of v43; `source` (TEXT tag) is distinct from the existing `scan_source` (JSONB). [§N]
- `mcp_sweep_jobs` idempotency tuple is `(principal_token_id, session_id, idempotency_key) WHERE idempotency_key IS NOT NULL` (align the §N bullet). 

### AA.4 NFR-002 operationalized (QA R1-F1 — the gating assertion)
NFR-002/AC-011 get a concrete harness: **tolerance = live order-placement p95 ≤ 1.15× the stored pre-enable baseline over N≥500 samples**, measured via a **synthetic order/reconciler-latency fixture** in CI (since live-money isn't built, the fixture exercises the reconciler/order-prep path that shares the loop); the baseline-capture procedure runs just before enable; the live-SLI instrumentation (A-005) is a hard, separately-tested enable-preflight prerequisite (enable fails if any breaker-input SLI is absent).

### AA.5 Test fixtures & coverage seams (QA R1-F3/F4/F7/F20)
Added to §T's fixture list: **golden sweep** pinned as a committed artifact (seed, kline ranges, scan rows, objective, expected winner config-hash, expected uplift sign+tolerance); **seeded klines/scan factories**; an **injectable Clock** seam (drives TTL/idle/rate-window/timeout assertions via virtual time — no real waits, fixes AC-014's >300 s and FR-025 TTL); **multiprocessing-aware coverage** (`concurrency=multiprocessing`, `COVERAGE_PROCESS_START`) + an in-worker canary assertion so the secret-scrub path is actually measured; **branch coverage with a 100% floor on apply/auth/deny-list/dispatch-error-map**, 90% elsewhere.

### AA.6 New tests for previously-uncovered requirements (QA R1-F5/F9/F10/F12/F15/F19)
- Restart-mid-sweep recovery (NFR-008/AC-023); sweep reattach-by-id after session drop (FR-021); proposal expiry via virtual clock (FR-025/AC-020); egress consent recorded once (FR-033/AC-022); audit chain tamper-detect + writer-restart gap-recovery (FR-032/AC-021); malicious agent-rationale renders inert (no XSS) — frontend + backend neutralization (FR-024); concurrency: double-approve (row_version-guarded/idempotent), revert-conflict (detect intervening change), duplicate idempotency_key dedup.

### AA.7 Perf measurement rigor (QA R1-F6/F11/F13)
NFR-005's "≥500 combos/sec (FakeRunner)" reconciled with its gating test — the asserted figure is **5000 combos < 60 s (≈85/sec)**; the 500/sec is an aspirational ceiling, not the gate. NFR-001 thresholds specify N samples + warmup + percentile method + a relative-to-baseline assertion. `sweep_estimate` ETA is bounded within 2× on the FakeRunner (or explicitly marked non-asserted, testing only combo-count + the >5000 refusal).

### AA.8 Frontend gaps (frontend R1-F1/F2/F3/F5/F6/F7)
- **Optimizer/sweep-monitoring screen** specified in §L: sweep list (status/progress polling `GET /sweeps`), per-sweep detail (top-N + uplift/robustness/fidelity caveat), cancel-with-confirm, `running/interrupted/failed/empty` states; **Activity** + **Disable/Kill-switch** controls get §L bullets too.
- **Proposal deep-link route:** child route `/mcp/proposals/$proposalId` (mirrors the existing `/backtest/$runId` pattern) — opens the Proposals tab focused on that proposal (makes FR-022's deep link implementable).
- **Nav status-dot + pending-proposal badge:** extend `NavItem` with `status?`/`badgeCount?`, fed by `GET /api/v1/mcp/status` + pending-proposal count; the query is **NOT mounted/polled until enabled** (seed from the one-shot `/api/v1/health` `mcp` field, back off on 503) so the OFF path stays zero-overhead (NFR-011) — a regression test asserts no MCP control-plane calls when disabled. Mobile: drop the dock-mirroring claim (dock is a fixed 4-item allowlist); show the dot in the section header instead.
- **zod drift test** added to §T (frontend): `/mcp` zod schemas validated against recorded control-plane MSW fixtures so mirroring is enforced, not just asserted.
- **a11y tooling** (`@axe-core/react`/`jest-axe` + `eslint-plugin-jsx-a11y`) added to devDependencies + an automated axe test of the `/mcp` panels in both themes (NFR-013).
- **New `@/components/ui` primitives to build** (not reuse): `Switch`, `Accordion`, `SegmentedControl` (on `@base-ui/react`).

### AA.9 Missing flows & ACs (product R1-F6/F7/F8, QA R1-F8/F14)
- §J adds operator Disable/Kill-switch and Token-rotation flows.
- AC-007 folds in winner-correctness: "winner == golden expected config-hash with uplift > 0" (not just determinism).
- `backtest_get` exposes background-task status for fire-and-poll (FR-014).
- Constant-time compare tested structurally (assert `hmac.compare_digest` is the code path), not by wall-clock timing.

### AA.10 Quantified vague terms (QA R1-F18)
Token-budget warning threshold = 16,000 tokens (80% of the Full ceiling); resource read ≤ 50 ms / ≤ 64 KB; the reserved DB live-floor is a concrete connection count derived from measured peak (AA.2) — stated numerically in the plan.

**Spec Review R1 status:** all High/Critical findings folded in (debug FR+AC, backtest AC, quantified robustness bar, proposal target-scan + merged validation, rate-gate/concurrency-gate acknowledgment, NFR-002 harness, fixtures, UI gaps). Ready for R2 verification.

## AB. Spec Review Round 2 Revisions (folded into the main sections above)

R2 confirmed the R1 Highs resolved but flagged a "two sources of truth" risk and two new precision gaps. These R2 fixes were **promoted INLINE into the main sections** (not left as a changelog):
- **Robustness verdict fully specified (R2-F1):** FR-020 now classifies each check HARD/SOFT and fills the `not_single_trade_dominated` threshold (40% of gross PnL); FR-018 states constraints (FR-039) AND the bar both apply. The "X%" placeholder is gone.
- **Apply drift/lost-update guard (R2-F2):** FR-023 now requires target-NULL check, index bounds-check, `diff.before` mismatch coerce-or-reject, and optimistic concurrency on the `scheduled_scans` row. New AC-026.
- **NFR-002 promoted inline (R2-F1 maint.):** the 1.15× p95 / 1.3× p99 / max-bound, N≥500, synthetic-fixture wording now lives in NFR-002 itself (no longer only in §AA.4); AC-011 references it.
- **NFR-005 figure reconciled (R2-F5/F7):** NFR-002…NFR-005 bodies now state the real gate (5000 combos < 60 s ≈85/sec); 500/sec is labeled aspirational.
- **§L dock contradiction removed (R2-F3):** the status dot is in the mobile System-section header, not the dock; the optimizer/activity/disable-kill bullets + the `/mcp/proposals/$proposalId` route + the OFF-gated nav query are now in §L.
- **AC-007 winner-correctness (R2-F2 prod/F8 maint.):** AC-007 now asserts winner == golden config-hash + the full FR-018 bar.
- **FR-039/040 AC + API (R2-F3 prod, R2-F1 integ):** new AC-024 (constraint-exclude) + AC-025 (re-rank); `GET /sweeps/{id}/results?objective=` added; `mcp_sweep_results.metrics` MUST store the 8-metric superset; objective enum is app-validated TEXT (no DB CHECK) so additive metrics need no migration.
- **Data-plane conformance (R2-F4/F6 integ):** `tools/list` annotations, `tools.listChanged=true`, protocolVersion floor+ceiling + lenient header — added to §K.1.
- **status/health pending_proposals + 503 (R2-F5 prod/F8 integ):** `GET /status`/`/health` now expose `pending_proposals`; `/status` returns 503 when the module is absent, 200 `{state:"off"}` when merely disabled.
- **Migration v44 (R2-F11 maint.):** the additive `backtest_runs.source/sweep_id` migration is **version 44** (its own contiguous version, no FK ⇒ order-independent); the contiguity CI gate covers **v43 AND v44**.
- **Audit gap-recovery contract (R2-F3 backend):** on writer boot, a begin-without-end is stamped `status=interrupted, duration=NULL`; `audit_completeness==1.0` means "every begin has a TERMINAL status (incl. interrupted)", chain continues from the last verified seq. Added to §M/AC-021.
- **Rate-gate default-lane equivalence (R2-F5/F9 integ/backend):** AA.2's `bybit_rate_gate` change defaults the new lane to the LIVE lane — a signature-compat test asserts every existing caller (scanner/reconciler/order-placement) is behavior-unchanged; the BacktestService UI reserved-slot count equals today's effective UI concurrency when idle.
- **Coverage split (R2-F10 maint.):** §T's "90%+" is the AA.5 split — 100% branch floor on apply/auth/deny-list/dispatch-error-map, 90% elsewhere, multiprocessing-aware.
- **Golden-sweep determinism (R2-F6 backend):** the golden sweep pins `max_workers=1` + states engine-vs-FakeRunner + exercises the deterministic tie-break (AC-007); worker-side deadline tests run `run_one` in-process (the injectable Clock is in-process only).
- **Tail-latency in the gate (R2-F4 backend):** NFR-002 bounds p99 + max single-cycle, not just p95 (missed stops live in the tail).
- **Finding-ID hygiene (R2-F9 maint.):** review findings are lane-prefixed (backend-/qa-/prod-/integ-/maint-) to avoid the R1-F# collisions; low-value wording items (scans_get naming, warning-threshold-per-preset, AA cross-ref to §15.2) are resolved as noted.

**Spec Review R2 status:** R1 Highs resolved; R2 Highs (robustness verdict precision, apply drift-guard) + the contradiction/two-sources-of-truth items folded in inline. Ready for R3 verification.




