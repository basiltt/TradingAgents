# Progress Tracker: MCP Server (AI Agent Integration)

**Created:** 2026-06-07
**Last Updated:** 2026-06-07
**Current Step:** Part 2 implementation — P0–P4 built + reviewed; P1 read-tool gap closed
**Status:** IN_PROGRESS (implementation; pre-merge)
**Active Skill:** /new-feature (`~/.claude/skills/new-feature/SKILL.md`)

---

## Implementation State (authoritative — supersedes the planning-phase log below)

**Branch:** `worktree-mcp-server` · **Commits:** 13 (12 feature/fix + this tracker update)
**Backend tests:** 217 MCP green · 123 host-app regression green · import-linter 3/3 KEPT
**Frontend:** tsc 0 errors · eslint clean · vite build clean · OFF-path inert

### Phase completion vs plan
| Phase | Plan file | Status | Notes |
|-------|-----------|--------|-------|
| P0 skeleton | 01-phase-P0 | DONE | registry/auth/audit/dispatch/redact/transport + control-plane + DB v43/v44 |
| P1 read tools | 02-phase-P1 | DONE (gap closed) | All 9 tool-rows: scans, accounts, **positions, trades, portfolio, analytics, symbols**, scheduled(+get), strategies(+config_current). core/shape.py (projection/keyset/LTTB). Resources (server/info, scan/latest, config/current, **portfolio/snapshot**, **scan/{id} template**). Prompts (optimize_my_config, audit_last_scan, **explain_trade_close**). |
| P2 tool-budget UI | 03-phase-P2 | DONE | /mcp console: master toggle, context-budget manager, connection/token panel, proposal queue. Enriched /mcp/registry + preset endpoints. |
| P3 backtest+debug | 04-phase-P3 | DONE | backtest_run/get/list/compare + debug_scan_trace/symbol_decisions + rate-gate mcp lane |
| P4 optimizer+apply | 05-phase-P4 | DONE | combos/ranker/orchestrator + apply pipeline + full money path (create→approve→apply→revert, drift-guarded, ceiling-enforced) |

### Tools registered (25 total)
accounts(2), analytics(2), backtest(4), debug(2), optimizer(2), portfolio(1),
positions(2), scans(2), scheduled(2), strategies(2: strategies_list+config_current), symbols(2), trades(2).
(`advanced` group intentionally empty — reserved for live-money primitives, deferred.)

### Review passes completed (this implementation)
- P0–P4 adversarial hardening (3 reviewers) → audit delivery, redaction depth, CancelledError, SL=None ceiling, etc.
- P2 phase review (frontend + security, 2 reviewers) → 8 findings fixed; preset tier-clamp + exchange_facing exclusion.
- Final cross-phase review (3 reviewers: money-path / lifecycle / production) → A6 revert-ceiling FIXED, proposal-create wired, audit-chain resilience, lifecycle teardown, NaN ceiling, diff envelope.
- P1-completion review (redaction surface) → widened money markers (position_value/notional/funding/fee/cost/realised) + ratio-exemption so absolute exchange money is masked by default while ratios/prices survive.

### Known deferrals (documented, not gaps)
- `advanced` tool group (live-money primitives: place_order/close_position/set_leverage) — out of MVP scope.
- AI Manager tools — explicitly excluded per original feature scope.
- Audit/proposal retention purge job — modeled (retention_days columns) but no purge task yet (single-user v1).
- ProcessPool/shared-memory optimizer execution — in-process orchestrator shipped; ProcessPool is a perf layer over the same pure core.

---

## Session Log (planning phase — historical)


| # | Timestamp | Activity | Status | Details |
|---|-----------|----------|--------|---------|
| 1 | — | Step 1: Codebase Discovery | DONE | Mapped API surface, toggle pattern, backtest schema, migrations, frontend routing |
| 2 | — | Step 2: Requirements Brainstorm | IN_PROGRESS | Launching Round 1 (5 agents) |
| 3 | — | Step 2: Brainstorm R1 | DONE | 5 agents (product/arch/security/QA/frontend), 221 reqs compiled |
| 4 | — | Step 2: Brainstorm R2 | DONE | 5 agents (integration/backend/security/product/QA), +150 reqs → 371 total |
| 5 | — | Step 2: Brainstorm R3 | DONE | 5 agents (arch/devops/db/perf/maintainability), +120 reqs + 17 contradictions → 491 total. MULTIWORKER correctness gap found. |
| 6 | — | Step 2: Brainstorm R4 | DONE | 5 agents (agent-UX/migration/security-deep/QA-convergence/SDK-docs), +90 reqs +3 contradictions → 581. QA verdict: "over-complete, stop." |
| 7 | — | Step 2: Brainstorm R5 | DONE | Convergence: 3/5 reviewers converged; backend+frontend found ONE cluster (apply-proposal loop) → +5 reqs (R-582..586) → 586 total |
| 8 | — | Step 2: Brainstorm R6 | DONE | FINAL convergence: 3/3 reviewers CONVERGED/spec-ready. 2 consecutive clean rounds. Brainstorm COMPLETE: 586 reqs, 20 contradictions resolved. |
| 9 | — | Step 3: Architecture Document | DONE | Drafted specs/mcp-server-architecture.md (13 sections, 12 ADRs resolving C1-C20). |
| 10 | — | Step 3: Arch Review R1 | DONE | 5 agents (1 partial). Critical: perf/live-protection cluster + leader-lock split-brain + pool starvation + OOM. High: mount mechanics, apply-path service gap, BacktestService real changes, capabilities mismatch, missing control-plane endpoints. ~60 findings. |
| 11 | — | Step 3: Arch Review R1 fixes | DONE | Revised ADR-7/8/9/12; added §14 Round-1 Revisions (14.1-14.13) folding in all Critical/High. |
| 12 | — | Step 3: Arch Review R2 | DONE | Round-1 Criticals resolved (arch: "no Critical remains"). R2 found: doc-consistency drift (stale ADR-12 dup, 5→6 tables, stale §11 nums) + ProcessPool hardening (spawn/shared-mem/core-cap/oom_score/no-fork-asyncpg) + max_connections gate + run_one cancel/parity + audit single-writer + allow-list apply. |
| 13 | — | Step 3: Arch Review R2 fixes | DONE | Deleted stale ADR-12 dup, fixed §2/§6/§4/§7/§11 consistency, env var rename; added §15 (15.1-15.11) ProcessPool hardening + pool budget + audit single-writer + allow-list apply + run_one completion. |
| 14 | — | Step 3: Arch Review R3 | DONE | Arch reviewer: "converged, no Critical/High". Perf/devops found 1 new High: /dev/shm SIGBUS (shm fix backing-store) + shm-seam mediums. Security reviewer incomplete. |
| 15 | — | Step 3: Arch Review R3 fixes | DONE | §15.12 shm SIGBUS hardening (preflight shm-size gate, off-loop build, cgroup watchdog, BrokenProcessPool handling, Windows guards) + §15.13 editorial + kill_epoch col. |
| 16 | — | Step 3: Arch Review R4 | DONE | Perf/devops shm verify (1 impl-note). Security found 4 Highs: worker env-scrub (spawn inherits secrets), deny-list must name real money sinks, metadata-vs-behavior CI check, literal allow-list fail-on-new-field. Folded into §15.14/15.15. |
| 17 | — | Step 3: Arch Review R5 | DONE | Both reviewers CONVERGED: security "money/secret provably closed", holistic "SPEC-READY". 2 consecutive clean rounds (R3 arch + R5). Architecture COMPLETE (5 review rounds). |
| 18 | — | Step 4: Create Specification | DONE | specs/mcp-server-spec.md — all sections A-Z; 37 FR + 14 NFR + 15 AC + 10 risks; MVP-scoped P0-P4. |
| 19 | — | Step 5: Spec Review R1 | DONE | 5 agents. Highs: debug no FR/AC, backtest no AC, "robustly beats" unquantified, NFR-002 not operationalized, golden-sweep/clock fixtures undefined, mcp_proposals NO target-scan col (breaks apply), rate-gate/concurrency-gate changes unacknowledged, merged-config validation, optimizer/deep-link/nav-badge UI gaps. ~55 findings. |
| 20 | — | Step 5: Spec Review R1 fixes | DONE | +FR-038/039/040, quantified FR-018/020 robustness bar, proposal target_schedule_id+merged validation, +AC-016..023, §AA revisions (NFR-002 harness, fixtures, rate-gate/concurrency acks, UI gaps). |
| 21 | — | Step 5: Spec Review R2 | DONE | 5 agents. R1 Highs confirmed resolved. New: robustness-verdict precision (X%/hard-soft), apply drift-guard, §AA two-sources-of-truth, FR-040 no API, NFR-002 tolerance contradiction. ~40 findings. |
| 22 | — | Step 5: Spec Review R2 fixes | DONE | Promoted INLINE: FR-018/020 hard/soft+40%, FR-023 drift-guard, NFR-002 p99/1.15x, NFR-005 gate, §L dock/optimizer/route, AC-007/024/025/026, §K annotations+pending_proposals, v44, audit gap-recovery, §Y/§Z refresh. §AB recap. |
| 23 | — | Step 5: Spec Review R3 | DONE | backend/QA CONVERGED, product/integration CONVERGED, maintainability found 1 contradiction (AC-011 vs NFR-002 tolerance) → fixed inline. 2 consecutive clean rounds. Spec FINAL. |
| 24 | — | Step 6: Create Implementation Plan | DONE | 6 files: 00-summary + 01-P0..05-P4. TDD tasks w/ exact signatures, migration DDL, test specs. |
| 25 | — | Step 6: Plan validation | DONE | Parity: 12 issues (1 High: missing control-plane sweep/proposal endpoints; mediums: Protocol placement, run_one kw-only, ctx.services, leader cols, /audit, tier map). Codebase: 36/37 aligned, 1 Medium (update_scheduled_scan is last-write-wins, no row_version). |
| 26 | — | Step 6: Plan validation fixes | DONE | Fixed P-F1 (TASK-P4-13 control-plane endpoints), Protocol→core/runner.py, run_one kw call, ctx.services, leader cols, /audit+pending_proposals, tier map, C-F24 atomic apply method, BTCUSDT-in-snapshot, summary §F. |
| 27 | — | Step 7: Plan Review R1 | DONE | 5 agents, source-verified. Critical: ProcessPool worker conflates async run_one w/ sync entrypoint. High: apply JSONB codec, worker can't write DB, gate TOCTOU, live-p95 fixture/baseline untasked, AC-019 no test, request/mutate private, Optimizer/Proposals no host, deny-list missing new apply method. ~55 findings. |
| 28 | — | Step 7: Plan Review R1 fixes | DONE | Fixed: sync _run_combo worker entrypoint, parent-side persist, apply JSONB codec+canonical drift compare, gate TOCTOU-safe, live-protection fixture+baseline task, AC-019/db-floor/concurrent-apply tests, concrete P4 test files, coverage gate, import-linter task, preflight phase-gating, deny-list+apply method, mcpApi namespace, Optimizer/Proposals tabs, axe tooling, flat routes. |
| 29 | — | Step 7: Plan Review R2 | DONE | All 4 lenses CONVERGED: BACKEND (worker/apply/gate sound), QA (26/26 ACs tasked, live-gate runnable), FRONTEND (wiring/hosting/routing correct), SECURITY+ARCH (money/secret provably closed+tested, import-linter enforces). Plan FINAL. |
| 30 | — | Step 8: Planning Phase Summary | DONE | Part 1 complete. No unresolved Critical/High. Proceeding to Part 2 (worktree + per-phase TDD). |
| 31 | — | Step 9: Create worktree | IN_PROGRESS | EnterWorktree for isolated implementation |

## Review Summary (updated)

| Step | Rounds | Outcome |
|------|--------|---------|
| Step 2 (Requirements) | 6 | 586 reqs, C1-C20 resolved, 2 clean rounds |
| Step 3 (Architecture) | 5 | 12 ADRs + §14/§15, money/secret provably closed, 2 clean rounds |
| Step 5 (Spec) | 3 | A-Z spec, 40 FR/14 NFR/26 AC, 2 clean rounds |
| Step 6 (Plan validation) | 1 | parity (12 issues fixed) + codebase 36/37 aligned |
| Step 7 (Plan) | 2 | 6-file phased plan, R1 heavy fixes, R2 4/4 lenses converged |

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/mcp-server/progress-tracker.md | 1 | This tracker |
| specs/mcp-server-requirements.md | 2 | 586 requirements |
| specs/mcp-server-architecture.md | 3 | Architecture (12 ADRs + §14/§15) |
| specs/mcp-server-spec.md | 4 | Formal spec (A-Z, 40 FR/14 NFR/26 AC) |
| plans/mcp-server/00-plan-summary.md | 6 | Plan TOC + phases + cross-phase deps |
| plans/mcp-server/01-phase-P0-skeleton.md | 6 | P0 walking skeleton (full detail) |
| plans/mcp-server/02-phase-P1-read-tools.md | 6 | P1 read tools/resources/prompts |
| plans/mcp-server/03-phase-P2-toolbudget-ui.md | 6 | P2 tool budget + UI |
| plans/mcp-server/04-phase-P3-backtest-debug.md | 6 | P3 backtest+debug tools |
| plans/mcp-server/05-phase-P4-optimizer-apply.md | 6 | P4 optimizer + apply |

---

## Review Summary

| Step | Rounds | Outcome |
|------|--------|---------|
| Step 2 (Requirements) | 6 | 586 reqs, C1-C20 resolved, 2 clean convergence rounds |
| Step 3 (Architecture) | 5 | 12 ADRs + §14/§15, money/secret provably closed, 2 clean rounds |
| Step 5 (Spec) | 3 | A-Z spec, 40 FR + 14 NFR + 26 AC, 2 clean rounds |

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/mcp-server/progress-tracker.md | Step 1 | This tracker |
| specs/mcp-server-requirements.md | Step 2 | 586 requirements (6 rounds) + C1-C20 |
| specs/mcp-server-architecture.md | Step 3 | Architecture (12 ADRs + §14/§15 revisions, 5 review rounds) |
| specs/mcp-server-spec.md | Step 4 | Formal specification (A-Z) |

---

## Discovery Summary (Step 1)

**Stack:** FastAPI (Python 3.12, asyncio, asyncpg) + React/TS/Vite (TanStack Router/Query, zod v4) + LangGraph engine. PostgreSQL.

**API surface (all `/api/v1`):** routers in `backend/routers/` — accounts, ai_manager, analysis,
analytics, backtest, checkpoints, close_positions, config, debug, memory, models, portfolio,
scanner, scheduled_scans, signal_analytics, strategies, symbols, trades, trading_cycles, ws, ws_accounts.

**Toggle pattern to mirror (debug feature):**
- DB singleton table `debug_config (id INT PRIMARY KEY CHECK(id=1), tracing_enabled BOOLEAN ...)` — `async_persistence.py:765`
- Availability gate: `getattr(request.app.state, "debug_trace_recorder", None)` → `HTTPException(503)` — `routers/debug.py:13`
- Config endpoints `GET/PUT /debug/config` — `routers/debug.py:73`
- Lifespan wiring degrades to `None` on failure (never aborts startup) — `main.py:204-218`

**Security constraints (MCP must satisfy):**
- `CSPCSRFMiddleware` (`main.py:72`): all POST/PATCH/PUT/DELETE require header `X-Requested-With: XMLHttpRequest` else 403.
- `ContentSizeLimitMiddleware`: 1 MB body cap.
- CORS allow-list (`WEB_CORS_ORIGIN`), `allow_headers=["Content-Type","X-Requested-With"]`.
- Global exception handler returns sanitized 500.

**Backtest subsystem:**
- `POST /backtest` (201, returns run_id) — background task; `BacktestCreateRequest` (`schemas/backtest_schemas.py:35`) is the full tunable surface.
- `GET /backtest`, `GET /backtest/{id}`, `GET /backtest/{id}/trades`, `GET /backtest/compare`, `POST /backtest/{id}/cancel`, `DELETE /backtest/{id}`, `GET/POST /backtest-cache/{status,warmup}`.
- Service: `app.state.backtest_service` (BacktestService) — raises `BacktestRateLimitError`/`BacktestBusyError`/`BacktestValidationError`/`BacktestNotFoundError`/`BacktestConflictError`.
- Tunable params (sweep targets): direction, leverage(1-125), capital_pct, take_profit_pct, stop_loss_pct, min_score, confidence_filter, signal_sides, max_trades, execution_mode, fill_to_max_trades, skip_if_positions_open, max_same_direction, max_same_sector, blacklist/whitelist, max_signal_age_minutes, max_price_drift_pct, max_drawdown_pct, smart_drawdown_close, breakeven_timeout_hours, max_trade_duration_hours, trailing_profit_pct, close_on_profit_pct, target_goal_*, adaptive_blacklist_*, plus sim knobs (interval, fee_rate_pct, slippage_bps, funding_*).

**Debug subsystem:** `GET /debug/scan/{scan_id}`, `/debug/scan/{scan_id}/account/{account_id}`, `/debug/runs`, `/debug/account/{id}/timeline`, `/debug/symbol/{symbol}`, `GET/PUT /debug/config`.

**Migrations:** versioned `_MIGRATIONS: list[tuple[int, sql]]` in `async_persistence.py:776`, advisory-locked `_apply_migrations` (`:1279`). Add new `mcp_config` table as next migration version.

**Frontend integration points:**
- Routes: `frontend/src/routes/route-tree.tsx` (lazy import + createRoute + addChildren).
- Nav: `frontend/src/components/layout/navigation.ts` (System section).
- API client: `frontend/src/api/client.ts` (`request`/`mutate`, `DEFAULT_HEADERS` already includes CSRF header).
- Settings precedent: `frontend/src/components/config/ConfigPage.tsx` (read-only) — MCP page needs a real toggle (mutation).

**Key architecture decisions (to resolve in Step 3):**
- MCP transport: embedded FastMCP mounted on FastAPI (streamable-HTTP) vs standalone process.
- Tool→backend call path: in-process ASGI loopback (httpx ASGITransport, inject CSRF header) vs direct service calls vs real HTTP.
- Optimizer: agent-driven (primitive tools only) vs server-side sweep tool vs hybrid.
- Security: access token, safe-mode (gate destructive/live-trade tools), audit log, off-by-default.

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/mcp-server/progress-tracker.md | Step 1 | This tracker |

---

## Review Summary

| Step | Rounds | Findings (C/H/M/L) | Fixed | Deferred |
|------|--------|---------------------|-------|----------|
| Step 5 (Spec) | — | — | — | — |
| Step 7 (Plan) | — | — | — | — |

---

## Decided Log

| ID | Round | Decision | Reason |
|----|-------|----------|--------|

---

## User-Stated Requirements (verbatim constraints)

1. MCP integration toggleable on/off from the UI, **default OFF**.
2. Agent can use **basic app features** (scans, accounts, positions, trades, portfolio).
3. Agent can use **extensive backtesting** features + **debugging routes** (recently merged).
4. Agent can **run backtests with varying parameter combinations to find the optimal
   AutoTradeConfig** for the current app setup (optimizer/sweep).
5. Backtesting may optionally be exposed **through** the debugging feature scope if useful.
6. **Tool-budget management (NEW):** if the tool surface is large, the user must be able to
   **enable/disable groups of tools or individual tools** so the model's context window is not
   saturated. The server must only register/advertise the **enabled** subset (disabled tools
   cost zero context). Default selection must be conservative. Persist selection in DB
   (mirror `debug_config` singleton pattern).

## Blockers & Notes

| # | Timestamp | Issue | Resolution |
|---|-----------|-------|------------|
| 1 | — | Explore subagents returned API 400 during discovery | Did discovery inline via Read/Grep instead — complete |
