# Implementation Progress — Regime Multi-Strategy

**Worktree:** `.claude/worktrees/regime-multistrategy` (branch `worktree-regime-multistrategy`, based on origin/main + cherry-picked planning commit)
**Plan:** `plans/regime-multistrategy/00-plan-summary.md` + phase files 01–06
**Started:** 2026-06-07

## Baseline (Step 10)
- Full backend suite: **443 passed, 1 failed** — `test_concurrency_cap` (sandbox network validator blocks localhost→::1; pre-existing, environment).
- Feature-relevant modules: **364 passed, 2 failed** — `test_schema_migration_no_op_current_version` (sync persistence dead at v35 vs DB v42 — the PD2 finding, documented pre-existing) + `test_debounce_allows_after_interval` (pre-existing timing flake).
- **All 3 failures are pre-existing** (`git diff HEAD` empty) and documented in `research-history.md`. None touch `_try_trade` (the golden-snapshot path). Valid baseline.

## Phase Status

| Phase | Status | Commit | Tests |
|-------|--------|--------|-------|
| 0 — Foundation | DONE | committed | reason codes, config, migrations, ScanContext, router |
| 1 — Shared Compute (pure) | DONE | committed | market_data, kill_switch (12+6) |
| 2 — Routing/Cohort (wired) | PARTIAL | — | gates wired into _try_trade, integration green |
| 3 — F1 Filter (wired) | DONE | — | session+vol gates fire through executor |
| 4 — F2 Mean-Reversion | PARTIAL | — | MR math done; placement branch pending |
| 5 — Frontend + Tests | PENDING | — | — |

## Milestone: F1 + F3 working END-TO-END (90 regime tests green)
- Golden snapshot LOCKED (captures current _try_trade; placed BTC/ETH/DOGE, skipped SOL/XRP) — stays byte-identical with features off.
- Regime gates wired into _try_trade (kill-switch master+per-feature, cohort routing, F1 session+vol) — all no-op when off (golden green), all FIRE when on (integration test green).
- Existing auto_trade tests: 12/12 still pass (no regression).

## Session Log (cont.)
| 13 | 14:10 | Golden-snapshot harness (TASK-0.1) | DONE — locks _try_trade behavior |
| 14 | 14:20 | Wire regime gates into _try_trade (kill/cohort/route/F1) | DONE — golden stays green |
| 15 | 14:25 | Integration test: gates fire when enabled | DONE — 6/6 |
| 16 | 14:28 | Regression check: existing auto_trade tests | DONE — 12/12 |
| 17 | 14:30 | build_scan_context precompute orchestration (TDD) | DONE — 7/7 |
| 18 | 14:45 | F2 placement branch + _compute_mr_params + f2_long_ack | DONE |
| 19 | 14:50 | F2 placement integration (TDD; caught fade-side + SL-default bugs) | DONE — 6/6 |
| 20 | 14:55 | f2_long_ack escalation-staleness (TDD) | DONE — 8/8 |
| 21 | 14:58 | Full regime+auto_trade suite | DONE — 134 green, 0 regressions |
| 22 | 15:00 | Persistence tagging: place_trade + create_trade + create_child_trade INSERTs | DONE — 145 green |
| 23 | 15:15 | start_scan wiring: kill-switch read + build_scan_context + set_scan_context | DONE — 132 scanner green, no-op for non-regime |
| 24 | 15:20 | BACKEND FUNCTIONALLY COMPLETE end-to-end | DONE |
| 25 | 15:22 | AI-mgr MR exclusion + f2-long-ack endpoint (TDD) | DONE — 137 green |
| 26 | 15:40 | Frontend: client.ts mirror + RegimeStrategyFields + mount | DONE — tsc 0 errors |
| 27 | 15:45 | FULL-STACK FUNCTIONALLY COMPLETE | DONE |
| 28 | 15:48 | E2E all-on + coverage (95%) | DONE |
| 29 | 16:10 | Step 12c review gate (3 agents on REAL code) | DONE — 1 CRITICAL, 2 HIGH, ~15 Med/Low |
| 30 | 16:15 | Fix review findings (IR1-IR12) | DONE — 268 tests green |
| 31 | 16:45 | Review-fix regression tests (IR1/2/3/6/7) | DONE — 6/6 |
| 32 | 16:50 | Next: re-review (2nd round) then cross-phase + final hardening | IN_PROGRESS |

## Step 12c review fixes APPLIED (268 tests green, golden + tsc clean)
- IR1 CRITICAL: lazy MR mean (per-scan cached, kline-cache fetcher) — F2 now reachable.
- IR2 HIGH: place_trade gets strategy_cohort + f1_active (cohort no longer always 'trend').
- IR3 HIGH: check_geometry takes capture_pct, validates ACTUAL placed TP (not full-capture).
- IR4 MED: position_directions records the MR fade side (not LLM dir+reverse).
- IR6 MED: mr_max_trades enforced as MR position cap.
- IR7 MED: SL-vs-liquidation guard implemented (MR_SL_LIQUIDATION now emitted).
- IR9 LOW: scanner kill read fail-CLOSED when _db falsy.
- IR10 LOW: kline window sized from interval*depth (not hardcoded 30d).
- IR11 LOW: long-fade TP oracle now asserts independent hand-computed value.
- IR12 LOW: MR_SHORT_DISABLED enum (no magic string); float-None guard via `is not None`.
- IR5 documented as known v1 limitation (ack ceiling; SD28 follow-up) in endpoint comment.
- IR8 deferred-low: resolve_final_side kept (tested); unused `direction` param left (stable signature).

## Step 12c Implementation Review Findings (real code audit)
**CRITICAL:**
- IR1 [backend F1]: build_scan_context called with EMPTY scan_results (scanner_service.py:363) → MR means/prices NEVER computed → every MR trade skips mr_mean_unavailable → F2 DEAD in production. FIX: build/refresh ScanContext AFTER scan results exist (or compute mean lazily in _compute_mr_params from kline cache).
**HIGH:**
- IR2 [backend F2]: executor passes only strategy_kind to place_trade, NOT strategy_cohort/f1_active → cohort always "trend", f1_active always False (contradictory pair for MR). FIX: pass strategy_cohort=cohort + f1_active.
- IR3 [maint F1/sec F7]: check_geometry validates FULL-capture TP but placed TP is capture-scaled (0.6×) → SL in band (actual_TP, full_TP] passes guard with reward<risk. FIX: pass capture_pct into check_geometry; compare against actual placed TP.
**MEDIUM:**
- IR4 [backend F3]: position_directions recorded from LLM direction+reverse, NOT the MR fade side → max_same_direction enforced against wrong value for MR. FIX: record place_signal_direction for MR.
- IR5 [sec F2]: ack at ceiling {125,100,999} permanently defeats escalation-staleness. FIX: re-ack on any change OR validate ack against live config not schema maxima.
- IR6 [sec F3]: mr_max_trades in consent tuple but NEVER enforced as a position cap → 999 MR longs despite consenting to 2. FIX: enforce MR-long cap = mr_max_trades.
- IR7 [maint F2]: SL-vs-liquidation guard (FR-025/MR_SL_LIQUIDATION) NOT implemented (reason code defined, never emitted). FIX: implement liquidation-distance check or descope+delete code.
- IR8 [maint F3]: resolve_final_side is DEAD (never called; impl uses price-vs-mean per FR-021). FR-005/FR-021 conflict. FIX: reconcile — delete resolve_final_side + truth-table OR document; drop unused `direction` param.
**LOW:**
- IR9 [sec F5]: scanner kill read fail-OPEN when _db falsy (`if self._db else {}`). FIX: else {"__all__": True}.
- IR10 [backend F5/sec F6]: _fetch hardcodes 30d window regardless of interval/depth; DB configs not re-validated. FIX: size window from interval*depth; re-validate.
- IR11 [maint F4/F5]: long-fade TP oracle circular + long-fade TP value asserted nowhere. FIX: add hand-computed long oracle value + assert long-fade TP.
- IR12 [maint F6/F8/F9/F10/F11]: magic "mr_short_disabled" string; float(None) crash on explicit None; dead `side` param in mr_target_price; `or 8.0` rewrites 0.0; dead manifest local; dead enum members. FIX: cleanup.

## FULL STACK FUNCTIONALLY COMPLETE (137 backend tests + tsc clean)
Backend: scan -> ScanContext -> gates/route/F2 placement -> strategy-tagged trade.
Frontend: 3 feature toggles on the shared AutoTradeSection (both forms), 28-field
client.ts mirror, F2-long danger ack. All default-off; golden snapshot byte-identical.

## Remaining (verification + review + merge)
- Phase 5: E2E all-on integration test, perf-bound test, coverage gate
- Per-phase review gates (12c security/arch/backend/qa/perf), cross-phase (13)
- Final hardening (14, 20-25 rounds), traceability (16), merge (18)
- Deferred-but-noted: reconciler pending-intent writes, admin kill-switch endpoint,
  StrategyChip/PnL-view UI, fleet bulk-assign (v1-optional polish; backend core done)

## BACKEND END-TO-END COMPLETE
scan -> _set_executor_scan_context (kill read + build_scan_context BTC regime/means)
-> executor gates (kill, cohort route, F1 session/vol) -> F2 placement (fade side,
TP convert, ack) -> place_trade(strategy_kind) -> create_trade writes the tag.
- place_trade: +strategy_kind/strategy_cohort/f1_active params; long/short side map
- create_trade: 25-col INSERT (was 22); create_child_trade inherits parent (28 cols)
- start_scan: _set_executor_scan_context (kline-cache fetcher + fail-safe degrade)
- Existing scanner(132)+auto_trade+trade_repo+accounts tests all green (no regression)

## Remaining (non-trade-path + UI + tests)
- reconciler strategy-awareness + pending_intents writes; AI-mgr MR exclusion
- f2-long-ack POST endpoint + admin kill-switch endpoint (routers)
- frontend: AutoTradeSection sub-components, StrategyChip, PnL view, client.ts
- Phase 5: E2E all-on, fixtures, perf, coverage; review gates; final hardening; merge

## Milestone: ALL 3 FEATURES functionally working end-to-end (134 tests green)
- F1 session+vol filter: fires through executor, fail-open. ✓
- F3 cohort routing: trend-all-regimes, MR-only-ranging. ✓
- F2 mean-reversion PLACEMENT: short/long fade (side from price-vs-mean per FR-021),
  margin-% TP conversion, fail-closed on stale/missing data, geometry guards,
  server-authoritative long-ack with escalation-staleness, strategy_kind tagging. ✓
- build_scan_context: precompute predicate, BTC memoization, MR-symbol scoping,
  PR1-6 (MR-cohort vol-off still classifies), degrade-on-failure. ✓
- Golden snapshot: regenerated (trend trades now tagged strategy_kind="trend" —
  intended FR-050 change; decision logic byte-identical). ✓
- TDD caught 3 real bugs: flat-market→ranging, MR fade-side model, MR SL-default.

## Remaining (backend wiring + frontend + tests + review gates)
- start_scan: call build_scan_context + read kill-switch, set_scan_context on executor
- trade_repository: strategy_kind/strategy_cohort/f1_active in both INSERT paths
- reconciler + pending_intents; AI-mgr MR exclusion; f2-long-ack + admin endpoints
- frontend sub-components + StrategyChip + PnL view + client.ts
- Phase 5 E2E/fixtures/perf/coverage; per-phase review gates; final hardening; merge

## Phase 0 Task Status

| Task | Status | Notes |
|------|--------|-------|
| 0.2 ReasonCode enum | DONE | strategy_reason_codes.py — 4/4 tests green |
| 0.3 Config schema (28 fields) | DONE | AutoTradeConfig + 3 validators — 9/9 tests green |
| 0.4 ScanContext dataclass | DONE | scan_context.py — 8/8 tests green |
| 0.1 Golden snapshot harness | PENDING | test_regime_golden_snapshot.py |
| 0.5 Migrations 43–48 (async) | PENDING | async_persistence.py |
| 0.6 Migration 45 out-of-band + healthcheck | PENDING | — |
| 0.7 Gate-chain extraction | PENDING | strategy_router.py |
| client.ts TS mirror | PENDING | frontend AutoTradeConfig interface |

## Session Log
| # | Time | Activity | Status |
|---|------|----------|--------|
| 1 | 13:05 | Worktree + baseline established | DONE |
| 2 | 13:07 | Phase 0 TASK-0.2 ReasonCode enum (TDD) | DONE — 4/4 |
| 3 | 13:12 | Phase 0 TASK-0.4 ScanContext (TDD) | DONE — 8/8 |
| 4 | 13:18 | Phase 0 TASK-0.3 config schema 28 fields (TDD) | DONE — 9/9 |
| 5 | 13:25 | Phase 0 TASK-0.5 migrations 43-48 async (TDD) | DONE — 9/9 (incl CHECK==Literal) |
| 6 | 13:30 | Phase 2 TASK-2.1/2.2 strategy_router (route+resolve, pure) | DONE — 13/13 truth table |
| 7 | 13:32 | Phase 0 unit foundation: 41 tests green | DONE |
| 8 | 13:35 | Phase 1 market_data classifier + EMA (TDD; caught flat-market bug) | DONE — 12/12 |
| 9 | 13:42 | Phase 1 kill_switch reader (TDD) | DONE — 6/6 |
| 10 | 13:48 | Phase 4 mean_reversion_math TP oracle + guards (TDD; caught test-arith) | DONE — 13/13 |
| 11 | 13:55 | Phase 3 regime_filter session+vol gates (TDD) | DONE — 12/12 |
| 12 | 13:58 | Full new-module suite | DONE — 84/84 green |

## Pure-logic core of ALL 3 features complete (isolated-tested, default-off)
- `market_data.py` (classify_regime, atr_ratio w/ depth guard, ema_mean) — 12 tests
- `kill_switch.py` (read_kill_switches, is_killed; fail-closed) — 6 tests
- `mean_reversion_math.py` (margin_tp_pct oracle, check_geometry 4 guards) — 13 tests
- `regime_filter.py` (gate_session placement-UTC, gate_btc_vol fail-open) — 12 tests
- (+ Phase 0: reason codes, scan_context, strategy_router, config, migrations)
- TOTAL new tests: 84 green. TDD caught 1 real bug (flat-market→ranging) + 1 test-arith error.

## Remaining: WIRING into live services (the executor integration)
- build_scan_context orchestration (market_data) + start_scan wiring
- _try_trade: kill gate, cohort resolve, route_strategy, F1 gates, F2 placement branch
- trade_repository strategy_kind tagging (both INSERT paths)
- reconciler + pending_intents; f2_long_ack endpoint; AI-mgr exclusion
- golden-snapshot harness (capture current _try_trade) BEFORE the executor refactor
- Phase 5 frontend + E2E/perf/coverage

## Modules built so far (all TDD, default-off)
- `backend/services/strategy_reason_codes.py` (ReasonCode enum) — 4 tests
- `backend/services/scan_context.py` (ScanContext frozen dataclass) — 8 tests
- `backend/services/strategy_router.py` (route_strategy, resolve_final_side, feature_for) — 13 tests
- `backend/schemas/__init__.py` (28 AutoTradeConfig fields + 3 validators) — 9 tests
- `backend/async_persistence.py` (migrations 43-48, async-only) — 9 tests
- TOTAL: 41 new tests green; zero changes to runtime behavior paths yet (pure additions).

## Remaining Phase 0 (live-code, higher risk — needs golden snapshot first)
- TASK-0.1 golden-snapshot harness (must capture current _try_trade behavior)
- TASK-0.7 gate-chain extraction (refactor _try_trade under the snapshot)
- TASK-0.6 index healthcheck
- client.ts TS mirror
