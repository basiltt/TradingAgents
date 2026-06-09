# Production-Ready Frontend — Progress Tracker

**Skill:** `/production-ready`
**Worktree:** `.claude/worktrees/production-ready-frontend` (branch `worktree-production-ready-frontend`)
**Target:** `frontend/` (190 source files, 70 test files — Large)
**Started:** 2026-06-09

## Recovery Instructions
After compaction: read this tracker, re-read `~/.claude/skills/production-ready/SKILL.md`, resume from last IN_PROGRESS / next PENDING row.

## Baseline (Step 0 — captured before any change)

| Metric | Value |
|---|---|
| Typecheck (`tsc -b`) | PASS (0 errors) |
| Lint (`eslint .`) | FAIL — 21 errors, 3 warnings |
| Tests (`vitest run`) | PASS — 712/712 (69 files) |
| Build (`vite build`) | PASS (chunk-size warnings: charts 399kB, analysis 224kB) |
| Dep audit | 7 vulns (1 high, 6 moderate) — ALL dev/build tooling, not shipped |
| Coverage | not yet measured |

### Lint baseline by rule
- 11 × react-refresh/only-export-components
- 6 × react-hooks/set-state-in-effect
- 2 × react-hooks/exhaustive-deps
- 2 × react-hooks/purity
- 1 × @typescript-eslint/no-unused-expressions
- 1 × react-hooks/incompatible-library
- 1 × no-constant-binary-expression

### Test hygiene note
- ECONNRESET / "socket hang up" errors logged during test run (unhandled network/MSW leaks) — investigate Phase 4/5.

### Dep audit detail (all transitive dev deps)
- fast-uri (high), hono, ws, qs, ip-address, express-rate-limit, brace-expansion (moderate)
- Fix path: `npm audit fix` — verify none are runtime deps first.

## State
- current_phase: 1 DONE → starting Phase 2
- current_round: 1
- clean_streak: 0
- total_findings: 24 (all fixed)

## Phase Status
| Phase | Status | Rounds | Findings |
|---|---|---|---|
| 0. Baseline | DONE | — | — |
| 1. Type Safety & Linting | DONE | 1 | 24 fixed (lint 24→0, tsc 0, tests 720/720) |
| 2. Clean Code & Patterns | DONE (R1) | 1 | 22 found / 11 fixed, 1 declined, ~10 deferred |
| 2.5. Documentation | DONE (R1) | 1 | 62 exports documented (220 insertions, 0 logic) |
| 2.75. Maintainability | DONE (R1) | 1 | 36 found / 11 fixed, rest deferred |
| 3. Logging | DONE (R1) | 1 | logger.ts + 4 wirings, +7 tests |
| 4. Testing | DONE (R1) | 1 | +80 tests (834 total), fixed network-leak hygiene bug |
| 5. Bug Detection | DONE (R1) | 1 | 18 found / 12 fixed (1 HIGH, 6 MED, 5 LOW) +bug tests |
| 5.5. Future-Proofing | DONE (R1) | 1 | resilience: polling in-flight guard, WS jitter, per-call timeouts |
| 5.75. Performance | DONE (R1) | 1 | perf review done; high-value deferred (backend-dep), compiler covers memoization |
| 6. Config & Security | DONE (R1) | 1 | API-key sessionStorage leak fixed, CSP added, audit 7→0 vulns |
| 7. Final Holistic | DONE (R1) | 1 | 3 reviewers, fixed actionable + 5 regression tests |
| 8. Final Validation | DONE | — | all gates green |

## FINAL RESULTS (Phase 8)
- Typecheck (`tsc -b`): PASS (0 errors)
- Lint (`eslint .`): PASS (0 errors, 0 warnings) — was 21 errors / 3 warnings at baseline
- Tests (`vitest run`): 854/854 PASS (81 files) — was 720/720 (70 files) at start; +134 tests
- Build (`vite build`): PASS
- Dep audit: 0 vulnerabilities — was 7 (1 high, 6 moderate)
- Coverage: 40.76% stmts / 31.04% branch — was 38.16% / 28.77%
- Test-network-leak (ECONNREFUSED noise): ELIMINATED (was hundreds of lines/run)
- 9 clean phase commits on branch worktree-production-ready-frontend

## Baseline on local main (re-measured)
- Lint: 21 errors / 3 warnings → **0 / 0** after Phase 1
- Typecheck: PASS
- Tests: **720/720** (70 files) — origin/main had 712/69; +8 from draft feature
- Build: PASS (chunk warnings: charts 399kB, analysis 224kB)

## Decided Log
- DECIDED-1 (Phase 2): Extract `clampNumber`/`clampNumberOrNull` to `lib/number.ts`; replaced 16 inline `Math.min/max` clamp sites across AutoTradeSection/RegimeStrategyFields/ScannerPage/ScheduledScansPage. Tested. (Also fixed latent NaN bug in ScannerPage maxParallel.)
- DECIDED-2 (Phase 2): Add `buildQuery(path, params)` helper to client.ts; converted all 24 hand-rolled URLSearchParams blocks. Preserves exact param names; arrays as repeated keys EXCEPT trades account_id/status which stay comma-joined (pre-joined before buildQuery). 41 api tests pass.
- DECIDED-3 (Phase 2): Extract `purgeTradesFromState(state, ids)` in trades-slice; 3 remove reducers delegate. 29 tests pass.
- DECIDED-4 (Phase 2): Add `lib/storage.ts` readJson/writeJson; watchlists/endpoints/AnalyticsDashboard delegate. NOTE: throw-path tests removed — happy-dom localStorage methods are non-writable/non-prototype and not stubbable (3-Fix Rule hit); kept behavioral tests.
- DECIDED-5 (Phase 2): Add `refetch` useCallback in AnalyticsDashboard; 4 abort/refetch sites delegate.
- DECIDED-6 (Phase 2): Add `formatDateTimeLabel` to lib/format; 2 scanner formatDate dups delegate (year via opts override).
- DECIDED-7 (Phase 2): Hoist heatmap RGB triples to named consts in BacktestAnalysisTab.
- DECLINED (Phase 2 / A2-F7): Do NOT unify useTradeFilters.filtersToSearchParams (comma-string) with useTradeHistory.filtersToParams (string[]) — they serve different consumers (router URL vs API array param) and look similar but differ semantically. Unifying adds risk for no gain (YAGNI).
- DEFERRED (Phase 2): God-component splits — ScannerPage (1614L), AIMonitorPanel (931L), AutoTradeCard (833L), useAccountWebSocket message-router. High-churn/high-regression-risk; better as dedicated PRs. Re-evaluate in Phase 2.75 (Maintainability) with targeted extractions.
- DEFERRED→Phase 5 (bug): TradeDetailPanel ModifyTPSL Save discards sl/tp (no persistence path) — A2-F9. Real bug, handle in Phase 5.
- DEFERRED (lower value): CollapsibleSection unification (3 variants), ConfigPanel FIELD_SCHEMA, AccountsDashboard sort extraction, SignalAnalyticsPage→client.ts namespace, AI-manager thunk factory. Revisit Phase 7.

## Activity Log
- R1 (Phase 1): Fixed all 24 lint findings. Discovered worktree was based on stale origin/main; LOCAL main (d09a352) is 19 commits ahead with frontend changes (backtest draft feature). User chose REBUILD ON LOCAL MAIN.
- REBASE: Saved Phase 1 as patch (29/30 files; excluded BacktestConfigForm.tsx which differs on local main due to draft watch() subscription). Removed old worktree, set worktree.baseRef=head, recreated worktree from local main HEAD. Re-applied patch cleanly. BacktestConfigForm.tsx Phase-1 changes redone by hand on the draft-feature version.
- NOTE: baseline lint re-measured on local main below. Patch files (phase1-frontend.patch, phase1-tracker-backup.md) live in repo root; delete before final commit.
- R1 (Phase 2): 3 review agents (maintainability/architecture/frontend) → 22 findings. Fixed 11 (DECIDED 1-7 + watchlists/endpoints), declined 1, deferred ~10. Added lib/number.ts, lib/storage.ts, +27 tests. Verify: lint 0/0, tsc clean, 747/747 tests. COMMIT next.
- R1 (Phase 2.5): 2 doc agents → 62 exported functions/components/consts documented across 13 util/logic files. 220 insertions, 0 logic changes. Verify: tsc clean, lint 0/0, 747/747. Committed 989e42e.
- R1 (Phase 2.75): 3 maintainability agents → 36 findings. Fixed 11 named-constant/key-factory wins: useAccountWebSocket timing consts (DASHBOARD_DEBOUNCE/MIN_REFETCH/PING_WATCHDOG/JITTER), useAnalysisWebSocket NON_RETRIABLE_CLOSE_CODES, trades-slice UNREALIZED_PNL_EPSILON, ai-manager MAX_LLM_CALLS, trades/queryKeys.ts factory (centralizes ["trades",...] across 5 files), useTradeEvents stale const, documented ScannerPage intentional scan-ID no-restore. Deferred large extractions (WS router maps, AIMonitorPanel tables, ConfigPanel FIELD_BOUNDS, scanner field component). Routed ConfigPanel silent-discard bug → Phase 5. Verify: lint 0/0, tsc clean, 747/747. COMMIT next.
- DEFERRED→Phase 5 (bug): ConfigPanel handleSave silently discards out-of-range field values (no user feedback) — agent2 F3. Real UX bug.
- DEFERRED (Phase 2.75 large extractions, revisit Phase 7): useAccountWebSocket/useAnalysisWebSocket onmessage → handler map; AIMonitorPanel LivePositionsTable/DecisionsTable; ConfigPanel FIELD_BOUNDS schema; AutoTradeSection ClampedNumberField; ScheduledScansPage ScheduleActionButton.
