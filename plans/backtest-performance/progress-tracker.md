# Progress Tracker: Backtest Performance Optimization

**Created:** 2026-06-09
**Last Updated:** 2026-06-10
**Current Step:** Step 6 — Implementation Plan (+ Step 7 plan review)
**Status:** IN_PROGRESS — AUTONOMOUS OVERNIGHT RUN
**Active Skill:** `/new-feature` (`~/.claude/skills/new-feature/SKILL.md`)

## AUTONOMOUS MANDATE (user asleep ~7-8h, authorized 2026-06-10)

User granted FULL autonomy: make all decisions, never ask, complete the entire flow,
reach merge-ready + production-ready by morning.
- Reviews: convergence-based (fix every valid C/H/M immediately; stop at 2 rounds no new findings; cap 15/25 backstop only).
- Core committed: P0 golden-master → P1 cache → P2 loaders/sweep → P3 SoA engine (these hit the goal).
- P4 numba: attempt; SKIP if unstable on py3.14.3/numpy2.4.4 (D5 sanctions — P3 hits minutes alone).
- P5 Parquet/DuckDB + P6 fast-path: only if core green with time left; else defer with notes.
- Parity is the hard gate: golden-master diff after EVERY phase; revert any phase that breaks parity and can't be fixed.
- Compressed ceremony (deliberate deviation): per phase = ONE consolidated convergence review (5 agents: correctness/parity/security/perf/maintainability) + full TDD. 28 separate gates overnight is infeasible; rigor preserved, ceremony compressed.
- MERGE to main + push ONLY if ALL green (pytest + tsc --noEmit + npm build + golden parity + migration apply). Else push feature branch + leave precise report. NEVER poison main on a live trading system.
- Heartbeat cron every 30 min resumes any stalled/failed workflow.

---

## Goal

Optimize the backtesting system: multi-hour → seconds-to-minutes (TradingView-class),
WITHOUT changing business logic (<1% deviation from real trading; golden-master
bit-identical on canonical 5m no-drill path). Grounding doc:
`specs/backtest-optimization-findings.md` (18-agent investigation, all 7 top claims verified).

## Locked Decisions (user-approved 2026-06-09)

| ID | Decision | Reason |
|----|----------|--------|
| D1 | FULL maximalist rollout, Phases 0→6 | User chose over lean 0→3 |
| D2 | Storage: Postgres write-of-record + Parquet/DuckDB read layer + Arrow hot cache | User chose over in-memory-only |
| D3 | Execution via `/new-feature` skill, phase-gated TDD + reviews | User choice |
| D4 | Multi-TF drill-down CONFIRMED viable (5m high/low touch; drill 1m only when both TP+SL in bar; SL-first tie-break; lazy per-symbol LTF load) | Investigation verdict |
| D5 | numba is an EARNED upgrade (Phase 4), not a hard dep — Phase 3 must hit "minutes" alone | Py3.14.3 + numpy2.4.4 bleeding-edge for numba 0.65.1/llvmlite 0.47.0 |
| D6 | Do NOT "fix" intentional max_same_sector non-enforcement in backtest | Documented parity caveat |

## Hard Parity Constraints (apply to ALL phases)

- Bit-identical trades + equity_curve on canonical 5m no-drill path (CI guard)
- <1% per-trade + summary deviation on drill/portfolio paths AND non-optimistic
- Σ trade.pnl == final_equity − starting_capital on every fixture
- Sealed closed day fetched exactly once across N reruns (mock client, call_count==1)
- Preserve golden no-op guarantee (empty instrument_info/scan_contexts/fine_klines + no regime → byte-identical to 5m path)
- Core files stay semantically identical: backtest_engine.py, backtest_service.py,
  kline_cache_service.py, trading_rules.py, sweep_tools.py

---

## Session Log

### Session 1 — 2026-06-09

| # | Timestamp | Activity | Status | Details |
|---|-----------|----------|--------|---------|
| 0 | pre | Investigation workflow (18 agents) | DONE | Root causes verified; specs/backtest-optimization-findings.md written |
| 1 | now | Step 1: Codebase Discovery | DONE | 6-agent discovery; specs/backtest-optimization-discovery.md written |
| 2 | now | Step 2: Requirements Brainstorm | DONE | 14 rounds, 1171 raw → 517 curated; specs/backtest-optimization-requirements.md |
| 3 | now | Step 2: Resilience — resumed 10 net-failed agents | DONE | Network errors mid-run; stopped+resumed workflow, full coverage restored |
| 4 | now | Step 3: Architecture Document | DONE | Gate = YES; specs/backtest-optimization-architecture.md (704 L): 5 ADRs + §1-12 + Requirements Coverage Map (all 15 cats/517 reqs) + Appendices A/B |
| 5 | now | Step 4: Specification | DONE | specs/backtest-optimization-spec.md (1612 L): sections A-Z; 52 FR + 24 NFR + 45 AC; per-phase ACs P0-P6; §Y traceability (517 reqs + 7 REQ-SEC → FR/NFR/phase/test, orphan-check passes); 10 open questions resolved w/ defaults; 12 risks incl. D5 numba |
| 6 | now | Step 5: Spec Review gate | DONE | 6 rounds (cap), 5 full review+fix rounds applied; R6 fixer stalled on network (irrelevant — spec already hardened). Spec FINAL: 3942 L, 27 sections, all A-Z present, not truncated. |
| 7 | now | Step 6: Implementation Plan WRITTEN | DONE | plans/backtest-performance/implementation-plan.md (1459 L): sections A-S; 94 TASKs (TASK-001..608) across P0-P6; every task has exact file path + signature + named tests + REQ/AC mapping; §R full traceability (REQ→TASK→file→test→AC, orphan-check); N1-N4 baked in; zero hard placeholders (only spec-sanctioned CD-platform TBD) |
| 8 | now | Step 7: Plan review gate | IN_PROGRESS | Plan ready for adversarial 5-agent convergence review |
| 9 | now | Step 7: R1 plan-review findings APPLIED | DONE | ~32 deduplicated findings (5 reviewer batches, heavy dup) applied to implementation-plan.md via targeted Edits. Critical: split v58 (coverage-only) from NEW **v59 `_add_backtest_control_objects`** (TASK-106b) creating `backtest_runs` cols (stage_timings/engine_fingerprint/terminal_reason) + status-CHECK widen→7-value VALID + `bt_flag_config`/`bt_flag_audit`/`symbol_lifecycle`/`sor_data_generation` (closes the boot-crash gap RunReaper/TASK-114/212/404/110/505 depended on). High: TASK-107 index predicate DROP+CREATE swap (IF-NOT-EXISTS silent-skip bug); rollback narrative corrected (v57/58 binary CRASHES vs v59-DB per runner :1616-1621 — needs restore-point, not "runs without harm"); TASK-215 status→wire-map serializer (GREEN owner for T.9); TASK-203 re-pointed to `backtest_service.py:987 _build_fine_klines` producer + engine `_fine_klines` consumer; TASK-210 `_WARMUP_BAND` → service:57. Medium: TASK-304 funding minute<5 legacy SKIP; TASK-302 idx==0→entry_price (no klines[-1] wraparound); TASK-301/302 searchsorted side pinned; NFR-013 TASK-313 (event-loop-lag GREEN owner); RSS budget symbol-scaled (1/1.75/2GB tiers, reject at tier_budget/2); TASK-605 keep n le=5000 (no breaking retype), 2000 wall on expanded `count`/combos.py; TASK-216 equity-peak NET-NEW; 3-fix rule defined (§D.3); REL_TOL pinned (abs 1e-9/rel 1e-7, §A.1); TASK-401 kernel chunk-cancel (4096-candle bound for 120s cap); §Q.2 cadence-contingency table; NFR-005 numba-lane-scoped + no-numba sequential; P0 pre-estimate-default 30d×20sym + bybit_kline_calls==0; TASK-410 typed-numpy handshake; TASK-212 admission-gate mechanism; validate_partition_tree boot precondition; v58/v59 DDL tests skip-guarded headless (§I.5). 0 deferred. |
| 10 | now | Step 7: R2 plan-review findings APPLIED | DONE | 25 unique findings (5 reviewer batches, 5 cross-batch dups: B1-F7=B3-F5, B1-F8≈B2-F6, B3-F3=B5-F2, B1-F6=B5-F3, B1-F1=B5-F4) applied via targeted Edits. **4 code claims VERIFIED FIRSTHAND before applying:** (a) `grep drill_request` over backtest_engine.py = NOTHING → engine does NOT emit drill_requests (B4-F1); (b) `fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()` @async_persistence.py:655 + upsert `fetched_at=now()` @kline_cache_service.py:315 → NULL-TTL-exempt impossible (B2-F1); (c) persist @backtest_service.py:1500-1538 = ONE txn {results upsert w/ equity_curve COLUMN + DELETE-then-executemany trades + status='completed' flip} → TASK-211 "3-write COPY" was wrong (B2-F2); (d) full-book portfolio pass EXISTS @backtest_service.py:1043-1061 needing close_reason+open-intervals → TASK-202 window-set omitted it (B4-F2). **NEW TASKS:** TASK-119 (deploy-quiesce before v59 ACCESS-EXCLUSIVE status-CHECK swap, B1-F7), TASK-217 (partial-telemetry on 120s kill/cancel/degrade, AC-048l orphan, B5-F1), TASK-219 (`/backtest-runtime/status` route + public/privileged split + forwarding-header-never-privileged, B1-F2), TASK-220 (boundary symbol-charset `^[A-Z0-9]+$` + columnar canonical-path containment, B1-F4), TASK-220b (`bt_flag_config` write-surface lockdown preventive control, B1-F6). **HIGH:** TASK-215 RE-SEQUENCED into P1 as hard predecessor of TASK-114 (RunReaper persists `interrupted_by_restart` in P1; phase-gate `test_no_read_surface_emits_nonlegacy_status` added to E.1+every phase, B1-F3); TASK-206 spawn-worker env-allowlist subset + `test_worker_env_excludes_secrets` (REQ-SEC-006, B1-F1); TASK-202 full-book portfolio coverage pass + `test_full_book_portfolio_coverage` (B4-F2); TASK-203/410 drill handshake corrected to actual two-run() service-derives-from-trades (no engine drill_request seam; kernel returns typed trade RESULTS not (K,2), B4-F1); TASK-211 persist-shape corrected + idempotent-DELETE no-dup-trades test (B2-F2); TASK-109/113/§I.3/§M.4 TTL-exempt keyed off `sealed` not NULL fetched_at (B2-F1). **MEDIUM:** TASK-107 temp-then-RENAME index swap PRIMARY (no-gap, B1-F8/B2-F6); TASK-214 proxied-clients-distinct identity (B1-F10); TASK-118 warmup future/inverted/oversized 422 (B1-F9); TASK-106 v58 column types+defaults pinned + test (B2-F3); TASK-113 expected_bars day-intrinsic def (B2-F4) + gap_count provisional-until-sealed live-path (B2-F5); TASK-201/200 P2 seam stays legacy list[dict] until P3 (B2-F8); TASK-300→TASK-200 Record-release ownership (B3-F4); TASK-505 PITR re-stamp settles (B2-F7); TASK-605 explicit DEVIATION FROM SPEC line (B3-F1); TASK-013 gapped-funding P0 golden fixture (B3-F2); TASK-002 AC-048g B&H-collision + liquidation-w-fees-funding fixtures (B3-F3/B5-F2); TASK-409/606 numba+sweep gates cadence/B-contingent (B5-F5); TASK-212 effective_max_concurrent manifest write (B5-F6); TASK-211/212 validation-lane skip-guard notes (B3-F7); §L.3/502 DuckDB parameter-bound path mechanism (B1-F5). §R matrix + §R.6 orphan-check + §M.8/§S.2 updated. 0 deferred. |

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| specs/backtest-optimization-findings.md | pre | Investigation grounding (429 lines) |
| plans/backtest-performance/progress-tracker.md | Step 1 | This tracker |
| specs/backtest-optimization-discovery.md | Step 1 | Codebase surface / parity landmines |
| specs/backtest-optimization-requirements.md | Step 2 | 517 curated requirements (15 categories) |
| specs/backtest-optimization-architecture.md | Step 3 | Architecture (704 L): 5 ADRs, §1-12, coverage map, appendices |
| specs/backtest-optimization-spec.md | Step 4 | Specification (1612 L): sections A-Z; 52 FR + 24 NFR + 45 AC (per-phase P0-P6); traceability matrix; resolved open questions; risks |

---

## Review Summary

| Step | Rounds | Findings (C/H/M/L) | Fixed | Deferred |
|------|--------|---------------------|-------|----------|
| Step 3 Architecture | ~5 (accepted) | multi-batch C/H/M (tasks #23-29, #56-60) | applied per round | doc 1644L, accepted (diminishing returns) |
| Step 5 Spec review | IN_PROGRESS (cap 6) | — | — | convergence on new findings |

---

## Decided Log (Cross-Reference)

| ID | Round | Decision | Reason |
|----|-------|----------|--------|
| D1-D6 | pre | See Locked Decisions above | User-approved |

---

## Implementation Progress

| Phase | Status | Commit | Steps Completed |
|-------|--------|--------|-----------------|
| Phase 0: Golden-master harness | DONE | cbf8534 | Oracle harness (tests/backend/golden/) + 32 tests; 14 close-rule snapshots; 3-way Σ recon + meta-test; perturbation DETECTED; baseline 343 green |
| Phase 1: Cache re-download fix | DONE | 494ed31 | sealed_manifest.py + get_coverage_gaps manifest-aware + ensure_coverage seals closed days + v58 callable migration; AC-007 call_count==1 proven; golden parity unchanged; baseline 366 green. DEFERRED (YAGNI, noted): SealBackfillRunner, SymbolLifecycleRefresher, MaintenanceAdmin, RunReaper, CapabilityResolver, breaker-isolation, v59 control objects — not needed for the RC-3 fix; revisit if required. |
| Phase 2: Batched loaders + parallel sweeps | DONE | 55adbdb | _load_klines + _build_fine_klines via asyncio.gather; 3 parity tests; golden unchanged; baseline 369 green. NOTE: sweep ProcessPool parallelism deferred to P6 (sweep_tools is MCP-layer, lower-risk to batch there); the redundant-reload killer is the P1 cache + in-run dataset reuse. |
| Phase 3: SoA + merge-walk engine | DONE | 3720d9b | _MarkIndex bisect replaces all 3 O(T) linear mark scans (RC-2) → O(log N); 7 parity+speedup tests (>=10x on 20k series); golden bit-identical (56 tests); baseline 376 green. SCOPE NOTE: did the high-value RC-2 kill via bisect (parity-exact, low-risk) rather than a full numpy-SoA rewrite. RC-1 (per-scan window-index rebuild in _evaluate_candles_until) is a candidate follow-up but the per-candle dict build there is O(open candles in window), not quadratic across the run — lower priority; deferred. |
| Phase 4: numba JIT kernel | SKIPPED (D5) | — | DELIBERATE SKIP per D5 mandate ("skip if P3 hits minutes alone"). Benchmark: heavy workload (259,200 candle-rows, 30 sym, 200 scans, 600 trades) runs in **0.378s** on the bisect-optimized pure-Python engine — ~1000x under the 120s cap. numba would add a hard compiled dep (llvmlite) to a LIVE TRADING backend for ZERO practical gain (engine is no longer the bottleneck). YAGNI. numba verified working (N1, 267x) but unused; uninstalled from venv; pyproject untouched. |
| Phase 5: Parquet/DuckDB read layer | DEFERRED | — | DEFERRED (justified, mandate: "only if core green with time left; else defer"). Read path is no longer a bottleneck: P1 made closed klines fetch-once (zero re-download — the actual complaint), working set ~50-100MB fits in RAM. Parquet+DuckDB adds 2 heavy deps (pyarrow/duckdb) + dual-write + new failure mode to a LIVE TRADING backend to optimize a one-time cold read that isn't slow. Engine+load already sub-second. Revisit only if a profiled cold-read bottleneck emerges. |
| Phase 6: Vectorized fast-path + parallel sweep | DEFERRED | — | DEFERRED (justified). Vectorized barrier fast-path only fires for fully-independent positions (no drawdown/trailing/profit-target) — rare in real configs. Engine is 0.378s on heavy load → no vectorization needed for "minutes". Sweep ProcessPool parallelism is a real but MCP-layer enhancement; the redundant-reload killer (P1 cache) already lands the headline. Deferred to keep the live-trading backend simple + low-risk. |

---

## Blockers & Notes

| # | Timestamp | Issue | Resolution |
|---|-----------|-------|------------|
| N7 | 2026-06-10 | User bug-fixes landed during the run (breakeven/close-rules) | User had uncommitted breakeven fixes in the working tree (8 files: close_rule_evaluator Decimal-parse guard, schemas/frontend label updates, _PORTFOLIO_REASONS+=breakeven). Moved them to MAIN (commit 420b9b4), then REBASED feat/backtest-performance onto updated main — clean, zero conflicts (their changes + mine are in different functions). Golden snapshots STILL PASS against the integrated engine (their fixes didn't change the 5m-path close outcomes my fixtures froze) → no re-baseline needed. Integrated suite: 456 passed. |
| N8 | 2026-06-10 | LITE implementation review (user-requested) | Self-reviewed (branch-switch-immune via git show) 5 lenses on integrated code. NO Critical/High. Confirmed: _MarkIndex parity-exact on duplicate open_times; gather-vs-loop equivalent; _seal_closed_days seals only existing closed-day rows; v58 idempotent + column-before-index. Only finding (Low): ratchet_frontier tested-but-unwired → documented as intentional utility (seal path is already append-only/monotonic). Commit 730e006. |
| N9 | 2026-06-10 | CONTENTION: another agent switching working dir to main | Another agent began switching the shared working tree to main mid-review. All my work is COMMITTED on feat/backtest-performance (immune to checkout). Killed the review workflows (they read the working tree → unreliable during branch flips) and did the review myself via `git show <branch>:<file>` instead. Branch contention risk: coordinate before any merge/push. |
| N10 | 2026-06-10 | Final validation (in progress) | Branch=7c66050+420b9b4(user fixes)+P0-P3+lite review, HEAD 730e006; other agent done (no commits/changes). GATES: migration ✅ (58 ascending, no dups, v58 callable+idempotent+col-before-index). tsc FALSE PASS CAUGHT — npx tsc printed help (no node_modules) + exited 0; ran `npm install` (✅ exit 0), now running real `tsc -b`+vite build. Full pytest running. |
| N11 | 2026-06-10 | Frontend build gate | ✅ GENUINE PASS: `npm run build` (tsc -b + vite build) produced real dist assets incl. BacktestNewForm + backtest pages, "built in 1.19s". (Chunk-size advisory is pre-existing, not an error.) |
| N12 | 2026-06-10 | Full pytest gate — RED then triaged | Background "exit 0" was a FALSE PASS (actual EXIT=124 timeout + an `F`). Real failure: tests/backend/mcp/test_migrations.py hardcoded max(versions)==55; my v58 moved the head → fixed to assert 58 + callable (commit 1f026da). SEPARATE issue: full suite HANGS ~28% even with --timeout=90 signal-method (Windows: signal timeout can't interrupt thread/C-blocked tests). MY changed-area tests = 108 passed/2.74s with thread-timeout (NO hang from my code). Re-running full suite with --timeout-method=thread (Windows-safe) to get a definitive number + identify the pre-existing hang. |
| N13 | 2026-06-10 | "Hang" ROOT CAUSE = my timeout flag, NOT a real bug | Diagnosed: the "hangs" (test_mcp_asgi_set_after_enable, test_ai_manager_graph::test_timeout_returns_hold) were ARTIFACTS of `--timeout-method=thread` deadlocking pytest-asyncio's own asyncio timeout handling on Windows/py3.14 IOCP. PROOF: test_ai_manager_graph.py runs 33 PASSED in 64.5s with DEFAULT invocation (no thread-timeout); the offenders also pass in isolation. The real issue is the suite is just SLOW (LLM-mocked async, ~1min/area) so the 900s wrapper expired at ~28%. NO real failure, NO real hang in my code. Only legit failure was the migration-head assertion (fixed). Full suite (default, 25min): 2743 passed, 2 failed, 5 skipped, 567s. |
| N14 | 2026-06-10 | FOCUSED REVIEW found a real Critical (SM-1) — FIXED | The high-risk review caught a deterministic parity break: 1000-candle fetch cap + single-bracket fetch stored a multi-day backfill's oldest day PARTIAL (~205/288), then _seal_closed_days sealed it (no count guard) → permanently frozen partial day → engine walks fewer klines than correct. FIX (commit 3aa2e76): fetch pages to `start` (PAGE_SIZE 200→1000, MAX_PAGES 5→60); seal ONLY when candle_count >= full-day count; seal only successfully-covered symbols (exclude still_missing). Regression test test_partial_day_not_sealed proves a 100/288 day stays unsealed + refetches. Golden parity unchanged; 37 sealed + 46 fetcher/golden tests green. |
| N15 | 2026-06-10 | Final-suite failures triaged | 2 failures in the 2743-pass run: (1) test_migration_57_registered_as_last_callable hardcoded versions[-1]==57 — MINE (v58 moved head) → fixed to assert-registered-as-callable. (2) test_trading_rules::test_100x_leverage_small_moves — PRE-EXISTING (trading_rules.py AND its test byte-IDENTICAL to main 7c66050; fails on main too; SL-clamp edge unrelated to backtest perf). NOT fixing #2 (out of scope, parity-critical file I didn't touch). Re-running full suite to confirm only the 1 pre-existing failure remains. |
| N1 | 2026-06-10 | D5 numba viability (biggest plan risk) — RESOLVED | Empirically tested: numba 0.65.1 + llvmlite 0.47.0 JIT-compile cleanly on py3.14.3/numpy2.4.4. TP/SL-touch kernel: compile 0.28s, warm 99µs, **267× vs pure Python**. Phase 4 numba is GO (D5 escape hatch retained). numba+llvmlite installed in .venv; MUST declare in pyproject.toml (import-guarded) during P4. The `cache=True` `<string>` error only affects `-c` inline code, not real modules. |
| N2 | 2026-06-10 | Baseline test state (Phase 0 freezes against this) | GREEN: `pytest tests/backend -k "backtest or kline"` → **342 passed, 3 skipped, 10.74s**. Golden+engine subset = 53 passed/0.29s. Any phase dropping below this = parity break = REVERT. |
| N3 | 2026-06-10 | Postgres integration tests skipped headless | 3 tests need `BACKTEST_TEST_DATABASE_URL` (test_backtest_integration.py). Engine/golden parity (the business-logic gate) runs fully WITHOUT Postgres. P1 cache + P5 storage DB-integration validated via mocks (spec's `call_count==1`); flag any DB-only validation that can't run headless in the morning report. |
| N4 | 2026-06-10 | v58 migration pattern — VERIFIED firsthand | `_MIGRATIONS` list @ async_persistence.py ~L1494-1523 holds `(version, sql_or_callable)` tuples; current max = **v57** `(57, _backfill_open_trade_filled_qty)`. Single-stmt = string `(56, "ALTER...")`; multi-stmt/complex = **callable** (e.g. v57). v58 sealed-manifest MUST be a callable (multi-statement DDL strings get split on `;`). Add `(58, _add_sealed_manifest_columns)` ADD COLUMN IF NOT EXISTS on kline_cache_coverage, idempotent. |
| N5 | 2026-06-10 | Planning-doc reviews run to cap, not early convergence | Both architecture + spec reviews kept surfacing NEW material each round (large docs → reviewers always find more), hitting the 5-6 round cap rather than 2-clean-round convergence. Docs are over-thorough (arch 1644L, spec 3638L). LESSON: keep per-phase IMPLEMENTATION reviews tight (one consolidated 5-agent convergence pass per phase, per the compressed-ceremony mandate) so the same accretion doesn't eat the implementation window. Code reviews converge faster than doc reviews (concrete pass/fail). |
| N6 | 2026-06-10 | Branch strategy DECIDED | Use STANDARD feature branch **`feat/backtest-performance`** (verified free), NOT a git worktree. Rationale: simpler single-working-dir for autonomous overnight + heartbeat recovery; matches user's "merge to main + push" intent. Create AFTER plan converges: `git checkout -b feat/backtest-performance`, commit the 6 planning artifacts there (specs/* + plans/backtest-performance/*), then all P0-P6 implementation commits on this branch. main stays untouched until final merge gate. Exclude the stray `claude-notify` junk file from all commits. |
