# MCP Server — Implementation Plan: Summary & Navigation

## A. Title and Metadata
- **Plan:** MCP Server (AI Agent Integration) — phased implementation
- **Date:** 2026-06-07
- **Author:** Claude (`/new-feature`)
- **Status:** Final — passed plan validation (parity + codebase-alignment 36/37) and plan review (2 rounds: R1 heavy findings fixed, R2 all 4 lenses CONVERGED: backend/QA/frontend/security+arch). Ready for implementation.
- **Spec:** `specs/mcp-server-spec.md` (Final, AC-001..026, FR-001..040, NFR-001..014)
- **Architecture:** `specs/mcp-server-architecture.md` (12 ADRs + §14/§15, converged)
- **Requirements:** `specs/mcp-server-requirements.md` (586 reqs)
- **Version:** 0.1 (MVP = Phases P0–P4)

## B. Planning Summary
- **What:** an embedded MCP server (`backend/mcp/`) on the existing FastAPI app exposing read tools / backtest tools / debug tools / a parameter-sweep optimizer to an external AI agent over streamable-HTTP, plus a React `/mcp` operator page; default OFF; granular tool-budget; human-only config-apply.
- **Approach:** strict TDD, phase-by-phase, each phase shippable behind the OFF master toggle. P0 is a walking skeleton proving the whole spine end-to-end before breadth.
- **Key files:** `backend/mcp/**` (new), `backend/main.py` (2-line seam), `backend/async_persistence.py` (migrations v43+v44 + `update_scheduled_scan` apply-owner), `backend/services/backtest_service.py` (additive `run_one` + `source/sweep_id`), `backend/services/bybit_rate_gate.py` (additive lane), `frontend/src/components/mcp/**` (new), `route-tree.tsx`, `navigation.ts`, `client.ts`.
- **Key risks:** RK-1 sweep degrades live trading (mitigated: ProcessPool/spawn/shm + reserved DB floor + breaker + live-order-p95 gate); RK-2 prompt-injected agent reaches money (mitigated: human-only apply + allow-list + ceiling + deny-list call-graph test).
- **Key assumptions:** A-001 FastMCP embeds as ASGI sub-app; A-003 single-worker-when-enabled; A-005 live-SLI metrics exportable (prereq work).

## C. Global Constants
- **Project root:** `c:\Users\ttbasil\Desktop\Projects\PublicProjects\TradingAgents`
- **Backend pkg:** `backend/mcp/` (core/ tools/ resources/ prompts/ repositories/ schemas.py router.py mount.py manage.py)
- **Frontend pkg:** `frontend/src/components/mcp/`
- **Data-plane mount:** `/mcp/rpc` (bearer, not-in-OpenAPI, CSRF-exempt). **Control-plane:** `/api/v1/mcp/*`. **SPA:** `/mcp` + `/mcp/proposals/$proposalId`.
- **DB:** PostgreSQL via asyncpg; migrations append to `_MIGRATIONS` in `async_persistence.py`; current max = 42; MCP tables = **v43**; `backtest_runs.source/sweep_id` = **v44**.
- **Tests:** `tests/backend/mcp/` (+ `conftest.py`), pytest markers `unit`/`integration`/`slow`; frontend `frontend/src/components/mcp/__tests__/` (vitest). Coverage: 100% branch on apply/auth/deny-list/dispatch-error-map, 90% elsewhere; multiprocessing-aware.
- **Commands:** backend `python -m pytest tests/backend/mcp -x -q`; types `cd frontend && npx tsc --noEmit`; frontend tests `cd frontend && npm run test`.

## D. Implementation Strategy
- **Dependency order:** core plumbing (registry/dispatch/auth/audit/transport) BEFORE any tool; read repositories before read tools; SweepOrchestrator only after backtest tools are green; the apply path last (highest risk).
- **Risk-based sequencing:** the live-trading-protection mechanisms (reserved DB floor, ProcessPool isolation, breaker, kill-switch) are built in P0/P4 and gated by tests before any sweep can run.
- **Rollback-aware:** every phase ships behind `enabled=false` (zero overhead); the feature is removable (delete `backend/mcp/` + the 2-line seam; migrations left in place; retention purge lives outside the package).
- **Reuse:** mirror the debug feature (availability gate, degrade-to-None, repo style); reuse `BacktestService`, `kline_cache_service`, `bybit_rate_gate`, `mask_secrets`, `Decimal(str(x))`, the migration runner, TanStack Router/Query + neumorphism UI.

## E. Phase List

| Phase | File | Scope | Entry | Exit |
|-------|------|-------|-------|------|
| **P0 — Walking Skeleton** | `01-phase-P0-skeleton.md` | DB v43+v44, two-phase mount (register_mcp/mcp_boot), 503 gate, core registry+dispatch+auth+audit, ONE read tool (`scans_list`), control-plane config/enable/disable/status/health, OFF-path zero-overhead, multi-worker leader guard, in-memory ASGI test | merged main, clean tree | `initialize→tools/list→tools/call(scans_list)` green in-memory; OFF-path regression green; app starts with MCP present-but-OFF unchanged |
| **P1 — Read Tools + Resources/Prompts** | `02-phase-P1-read-tools.md` | read tools (accounts/positions/trades/portfolio/analytics/scheduled/strategies/symbols), resources (`tradingagents://scan/latest`, config, portfolio, server/info), static prompts, redaction-by-default, shape/pagination | P0 exit | all read tools contract-tested; redaction leak-test green; resources/prompts e2e green |
| **P2 — Tool Budget + Operator UI** | `03-phase-P2-toolbudget-ui.md` | registry presets (predicates), enable/disable groups+tools, context-budget meter, `/mcp` page (Overview/Tools/Connection/Status/Activity), nav entry+badge, connection snippet, token regen, zod schemas, a11y | P1 exit | tool toggle property-test green; budget ±10% test; `/mcp` page renders all sections; axe green |
| **P3 — Backtest + Debug Tools** | `04-phase-P3-backtest-debug.md` | `backtest_run/get/list/compare`, kline cache tools, debug forensics tools (allow_debug), BacktestService `run_one` + `source/sweep_id` (v44), shared concurrency gate, bybit_rate_gate lane | P2 exit | backtest schema-equivalence test; debug allow_debug gate test; rate-gate default-lane equivalence test |
| **P4 — Optimizer + Apply** | `05-phase-P4-optimizer-apply.md` | ComboGenerator/SweepRanker/SweepRunner/Orchestrator (ProcessPool/spawn/shm), `sweep_estimate/run/status/results/cancel`, `optimize_config`, baseline+uplift+robustness verdict, `mcp_proposals`, apply pipeline (allow-list→ceiling→merged-validate→update_scheduled_scan→revert), Proposals UI + Optimizer UI, live-order-p95 gate, breaker | P3 exit | golden-sweep acceptance (AC-007); apply-sanitization + drift-guard + deny-list call-graph tests; live-order p95/p99 gate green |

## F. Cross-Phase Dependencies & Shared Interfaces
- **`@tool` decorator + ToolRegistry** (P0 `core/registry.py`) — keyword-only: `@tool(*, name, group, input_schema, output_schema, safety_class, mutating=False, exchange_facing=False)`; `description` captured from the handler docstring. Every later phase's tools register through it.
- **Dispatch pipeline** (P0 `core/dispatch.py`) — `host/origin→auth→rate-limit→tier-gate→kill_epoch-fence→audit-begin→timeout(handler)→audit-end→error-map→shape`. Tools added in P1–P4 inherit all cross-cutting behavior. Tier-gate uses `_TIER_RANK` ordering (READ_ONLY<BACKTEST<MUTATING_DEMO<LIVE_MONEY).
- **`ctx` (CallContext)** (P0) — injected into every handler: `{principal, session_id, tier, correlation_id, services (lazy app.state accessors via ctx.services — handlers NEVER touch app.state directly), clock}`.
- **`BacktestRunner` Protocol** (declared P0 in `backend/mcp/core/runner.py`; `BacktestService` satisfies it in P3; `FakeBacktestRunner` in `conftest.py`) — `run_one(config, signals, snapshot, instrument_info, *, deadline) -> dict[str, Any]` (deadline keyword-only).
- **Repositories** (P0 base: config/audit; P4: `SweepRepository` TASK-P4-12b, `ProposalRepository` TASK-P4-08) — `MCPConfigRepository`, `AuditRepository`, `SweepRepository`, `ProposalRepository`. ALL `mcp_*` SQL lives here (no asyncpg in handlers/orchestrator/runner).
- **Control-plane router** (P0 base: config/enable/disable/status/health/tools-stub/audit/token/test-connection; P2: enriched `/tools`; P4 TASK-P4-13: sweeps + proposals endpoints) — `backend/mcp/router.py` at `/api/v1/mcp/*`.
- **Apply persistence** (P4) — a NEW `AsyncAnalysisDB.apply_auto_trade_config_atomic(...)` (`SELECT … FOR UPDATE` + drift re-verify + splice + write in ONE txn); the existing `update_scheduled_scan` is last-write-wins and MUST NOT be used for apply (codebase C-F24).
- **Frontend API client + zod** (P2; extended P4) — `frontend/src/api/mcpClient.ts`.

## G. Section-Index Mapping (where to find X)
- Migrations / table DDL → `01-phase-P0-skeleton.md §I`.
- The mount seam + lifespan ordering → `01-phase-P0-skeleton.md §K` (TASK-P0-02/03).
- The dispatch pipeline + audit writer → `01-phase-P0-skeleton.md §K` (TASK-P0-06/07/08).
- Read-tool pattern (template) → `02-phase-P1-read-tools.md §K` (TASK-P1-01).
- Preset predicates + budget meter → `03-phase-P2-toolbudget-ui.md`.
- `run_one` + BacktestService changes → `04-phase-P3-backtest-debug.md §K`.
- Sweep engine + apply pipeline → `05-phase-P4-optimizer-apply.md §K`.
- Security tests (deny-list, leak, DNS-rebind, TOCTOU) → each phase's §L; consolidated in P4.

## H. Definition of Done (whole plan)
- All 5 phases' exit criteria met; FR-001..040 implemented; AC-001..026 satisfied; NFR gates green (incl. live-order p95/p99 under sweep).
- Coverage targets met (100% branch on critical paths); existing suite unchanged with MCP OFF; Linux CI e2e green.
- The headline acceptance test (golden sweep → known winner with uplift/verdict/provenance/proposal) passes.
- Both review loops (per-phase + final) complete with no unresolved Critical/High.
