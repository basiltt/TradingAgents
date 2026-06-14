# Implementation Plan — Post-Market-Scan Optimization (Summary)

## A. Metadata
- **Plan:** Post-Market-Scan Optimization
- **Date:** 2026-06-14 · **Author:** Claude (`/new-feature` LITE) · **Status:** Draft → In Review · **Version:** 1.0
- **Spec:** `specs/post-scan-optimization-spec.md` (FINAL, effective precedence **AC > AB > AA > F-Z**)
- **Requirements:** `specs/post-scan-optimization-requirements.md` (MoSCoW MUST partition, post SC-1 de-scope)

## B. Planning Summary
- **What:** Optimize the post-scan auto-trade tail — (1) live WebSocket status, (2) bounded behavior-preserving cross-account parallelization, (3) corrected Bybit rate-gate (public/private channel fix + per-`account_id`/endpoint sub-limiter + ban-breaker), (4) UX polish.
- **Approach:** Mirror the proven `BacktestProgressManager`/`ws_backtest`/`useBacktestProgressWS` pattern for live status; extract a shared `run_post_scan_tail` orchestrator and fan out across accounts under a process-wide bounded semaphore (default width **1**); fix the gate channel classification + add a per-`account_id`/endpoint sub-limiter + ban breaker FIRST (Phase 0) so concurrency is safe.
- **Phases:** **0** rate-gate correctness + ban-breaker → **1** WS transport (parallelizable, fail-open) → **2** bounded parallelism + data integrity → **3** UX + cross-cutting.
- **Key files:** `bybit_rate_gate.py`, `bybit_client.py`, `auto_trade_service.py`, `scanner_service.py`, `scanner.py`, `main.py`, new `scan_progress_manager.py` + `ws_scan_progress.py` + schema; frontend `useScanAutoTradeProgressWS.ts` + `PostScanExecutionPanel.tsx` + `ScannerPage.tsx` + `client.ts` + `ws.ts`; `admin.py`.
- **Key risks:** double-placement (mitigated: golden-equality + live re-check + default=1), Bybit ban (mitigated: Phase 0 before Phase 2, private-bound feasibility, ban-breaker), orphan-on-pool-timeout (mitigated: inline TP/SL + structured orphan log + reconciler alert).
- **Key invariant:** byte-identical orders/counts vs sequential for identical inputs (golden test).

## C. Phase Files
| Phase | File | Goal |
|---|---|---|
| 0 | `01-phase0-rate-gate.md` | Channel fix, per-`account_id`/endpoint sub-limiter, gate-bypass fix, ban-breaker, thread-safe telemetry, startup validation, runtime kill-switches |
| 1 | `02-phase1-ws-transport.md` | `ScanProgressManager`, WS endpoint, typed event, frontend hook + panel, polling-through-tail fix, predicate, single-renderer |
| 2 | `03-phase2-parallelism.md` | Shared orchestrator, process-wide account semaphore, per-account partition/merge, parallelize the 5 steps, idempotency, failure isolation, replace-by-stage persist, lock-order, shutdown drain |
| 3 | `04-phase3-ux-crosscutting.md` | UX polish, ban-cooloff state, golden+speedup benchmarks, regression detectors, DoD gate, traceability |

## D. Implementation Strategy
- **Dependency order (hard):** Phase 0 (rate-gate correct) BEFORE Phase 2 (fan-out) — fanning out before the gate is channel/UID-correct increases ban risk. Phase 1 (WS, transport-only, fail-open) is independent and can be built in parallel with Phase 0. Phase 3 polish after the core is green.
- **Patterns reused:** `BacktestProgressManager` (pub/sub + history + GC), `ws_backtest.py` (subscribe/replay/ping-pong) but with STRICTER origin (exact-match, reject-missing) + scan-existence check, `useBacktestProgressWS.ts` (reconnect/StrictMode) but close-code-aware, the `_emit_life` None-guard idiom, the existing `BybitRateGate` deque+lane design extended with a per-`account_id`/endpoint dimension in the SAME critical section.
- **Rollback-aware:** every risky change (fan-out, channel-fix, per-endpoint limiter) is behind a runtime `feature_kill_switches` toggle reverting to current behavior; ships default concurrency=1 (sequential path exercised, byte-identical).
- **TDD:** each task writes the test first (RED), minimal code (GREEN), refactor. The golden-equality test is the central net for Phase 2.

## E. Effective spec decisions the plan is built on (from Section AC/AB)
1. Rate model is **PRIVATE-channel-bound** (~2 placements/s aggregate; speedup = RTT latency-hiding up to the private cap, ~4-5× at N=10, then plateau).
2. **No durable crash-resume system** (de-scoped, SC-1): resume stays no-worse-than-today; incremental persist = **replace-by-stage**; orphan → structured log → existing reconciler **alert** (manual intervention; position protected by inline TP/SL).
3. Lock order: trade-row write **under** the per-`(account,symbol)` position-lock; invariant "no subsystem acquires a position-lock while holding a pool conn" (verified true today — no pre-fix).
4. Combined-IP: per-channel pin `public=400 + private=100 ≤ 500 < 600`; drop the inert 540 counter; ≤480 is observability-only.
5. Per-UID limiter keys on internal **`account_id`** (1:1 with BybitClient); FR-049 startup-warns on shared-credential configs.
6. Ban breaker: half-open admission counter (K=1→2→4 per 5s window), both async+sync acquire honor it.
7. Account identity over WS = per-scan **salted handle**; free-text `detail`/`label` omitted from payload (FE renders from enums).
8. `set_trading_stop` + fill-polls use `lane="order"`.

## F. Definition of Done (release gate, R196)
Ship-the-fan-out gate (flip width>1) requires ALL green:
1. Golden-equality test (per-account ordered placements + full payload tuple + close-rule create/delete sets + counts) parallel==sequential.
2. Speedup benchmark: parallel < sequential at each N (RTT-overlap), zero `10006`, at width 2.
3. `=1` fallback byte-identical (AC-008).
4. Orphan-on-pool-timeout: structured log + reconciler alert, no silent drop.
5. Both call sites route through the single orchestrator.
6. All phase reviews converged; no unresolved Critical/High.

See per-phase files for full Task Breakdown, File-Level Changes, Tests, ACs, Verification, and Rollback.
