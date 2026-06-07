# Progress Tracker: Regime Multi-Strategy (3 Optional Features)

**Created:** 2026-06-07 05:10 UTC
**Last Updated:** 2026-06-07 05:10 UTC
**Active Skill:** `/new-feature` (`~/.claude/skills/new-feature/SKILL.md`)
**Current Step:** Step 1 — Pre-Flight Codebase Discovery
**Status:** IN_PROGRESS

---

## Feature Summary

Three OPTIONAL, default-off, toggleable features driven by the 2026-06-07 profitability research
(`docs/research/reports/2026-06-07_01-26-profitability-report.md`). Each enable-able from BOTH the
Scheduled Market Scan Form and the per-account Auto Trade ("Account Wise") Form — which in this
codebase are the SAME shared component (`AutoTradeSection.tsx`, used by both `ScannerPage.tsx` and
`ScheduledScansPage.tsx`).

- **Feature 1 — Regime/Session Entry Filter:** suppress/score-gate trend entries during detected chop
  (UTC session-hour windows + optional BTC realized-vol/ATR threshold + optional signal-breadth gate).
- **Feature 2 — Mean-Reversion Strategy:** a second strategy that activates only in "ranging" regime;
  fades range extremes, targets the mean, fast/tight exits. NO long-edge assumption beyond what data supports.
- **Feature 3 — Strategy-Cohort Accounts:** assign accounts to a strategy cohort (trend vs mean-rev),
  decorrelating the 21-account cloning.

**Hard constraint:** default off = current behavior byte-for-byte preserved. Do NOT add long trading
(longs have no validated edge). Features 2 & 3 should be validatable in the in-flight regime-segmented backtester.

---

## Session Log

### Session 1 — 2026-06-07

| # | Timestamp | Activity | Status | Details |
|---|-----------|----------|--------|---------|
| 1 | 05:10 | Step 1: Codebase Discovery | IN_PROGRESS | Read schema, executor, regime module, forms, migrations |
| 2 | 05:25 | Step 1: User scope decisions (D4-D7) | DONE | 4 forks resolved; 2 override constraints (RF1, RF2 logged) |
| 3 | 05:26 | Step 1: Complete | DONE | Discovery summary + tracker written |
| 4 | 05:27 | Step 2: Requirements Brainstorm R1 | DONE | 5 agents (product/arch/qa/frontend/security), ~200 reqs |
| 5 | 05:45 | Step 2: Compile requirements doc (R1) | DONE | specs/regime-multistrategy-requirements.md, ~95 reqs |
| 6 | 06:10 | Step 2: Requirements Brainstorm R2 | DONE | 5 agents (backend/db/product/perf/maint), +85 reqs, critical gaps |
| 7 | 06:12 | Step 2: R2 decisions + conflict resolution | DONE | YAGNI cuts, scope triage, contradiction fix; doc ~180 reqs |
| 8 | 06:40 | Step 2: Requirements Brainstorm R3 | DONE | 5 agents (integration/sec/qa/frontend/migration); sec timed out, +28 reqs |
| 9 | 06:42 | Step 2: Integrate R3 | DONE | 2 CRITICAL deploy gaps; doc ~208 reqs |
| 10 | 07:10 | Step 2: Requirements Brainstorm R4 | DONE | 5 agents (sec/backend/product/arch/qa); NOT clean; critical arch bug + scope question |
| 11 | 07:12 | Step 2: Scope decision escalation | DONE | User: ALL 3, F2 both-dir live, backtest DEFERRED to v2 |
| 12 | 07:14 | Step 2: Integrate R4 + decisions | DONE | doc ~233 reqs; scope locked |
| 13 | 07:45 | Step 2: Requirements Brainstorm R5 | DONE | 5 agents (arch/backend/qa/migration/maint); CONVERGING — arch declared coherent+phaseable |
| 14 | 07:48 | Step 2: Integrate R5 (decisions + cuts) | DONE | 2 cuts, naming ratified, build order; doc updated |
| 15 | 08:05 | Step 2: Requirements Brainstorm R6 | DONE | 3 agents convergence; arch="converged"; 2 items (R6-1 orderLinkId infeasible, R6-2 ack neg-tests) |
| 16 | 08:07 | Step 2: Integrate R6 | DONE | R6-1 pending-intent primary, R6-2 ack tests, R6-3 regime_snapshots clarify |
| 17 | 08:08 | Step 2: Requirements Brainstorm R7 (clean-check #1) | DONE | 3 agents ALL "CONVERGED — ready for spec". CLEAN ROUND 1. |
| 18 | 08:18 | Step 2: Requirements Brainstorm R8 (clean-check #2) | DONE | 1 inventory fix (R8-1: migrations 46 ack-table + 47 pending-intent). Resets clean streak. |
| 19 | 08:20 | Step 2: Integrate R8-1 | DONE | migration set finalized 43-47; doc ~235 reqs |
| 20 | 08:21 | Step 2: Requirements Brainstorm R9 (clean-check #1 redo) | DONE | 2 agents CONVERGED; nit R9-1 (mr_max_trades re-ack) folded |
| 21 | 08:30 | Step 2: Requirements Brainstorm R10 (clean #2) | DONE | CONFIRMED CONVERGED. 2 consecutive clean (R9→R10), 10 rounds total. |
| 22 | 08:32 | Step 2: COMPLETE | DONE | ~235 reqs, requirements doc final. Exit criteria met. |
| 23 | 08:33 | Step 3: Architecture decision gate | DONE | CREATE required: new modules, 2 tables+3 col migrations, spans 6+ services, complex state |
| 24 | 08:35 | Step 3: Author architecture doc | DONE | specs/regime-multistrategy-architecture.md (13 sections, full req coverage) |
| 25 | 08:50 | Step 3: Architecture Review R1 | DONE | 5 agents; NOT clean; ~20 findings (1 High logic bug, kill-switch×3, ack-dual×2) |
| 26 | 08:55 | Step 3: Integrate Arch-R1 (AD1-AD14) | DONE | §14 resolutions; migration set 43-48 |
| 27 | 09:05 | Step 3: Architecture Review R2 | DONE | 5 agents; propagation gaps + 3 new (ScanContext contract, rollback boot-guard, period enum) |
| 28 | 09:20 | Step 3: Integrate Arch-R2 (AD15-AD20) + body propagation | DONE | §15 + inline fixes (§10 bug, renames, mig 48 DDL, 43-48) |
| 29 | 09:25 | Step 3: Architecture Review R3 | DONE | 5 agents; propagation residue (kill-switch cadence, renames, means key) — NOT clean |
| 30 | 09:35 | Step 3: Integrate Arch-R3 (AD21-22 + propagation) | DONE | §16; kill-switch cadence/§11/§13 fixed, means two-level key, §2 diagram renamed |
| 31 | 09:38 | Step 3: Architecture Review R4 | DONE | 2 agents BOTH "CONVERGED". CLEAN ROUND 1. Cosmetic history residue cleaned. |
| 32 | 09:45 | Step 3: Architecture Review R5 | DONE | 2 agents BOTH "CONFIRMED CONVERGED". 2 consecutive clean (R4→R5). |
| 33 | 09:47 | Step 3: COMPLETE | DONE | Architecture doc final (16 sections), every req has a home, acyclic build order. |
| 34 | 09:48 | Step 4: Create Specification | DONE | specs/regime-multistrategy-spec.md (A-Z, FR-001..065, NFR-001..013, AC, risks, traceability) |
| 35 | 10:00 | Step 5: Spec Review R1 | DONE | 5 agents (sec timed out); 2 High + ~10 Med; NOT clean |
| 36 | 10:10 | Step 5: Integrate Spec-R1 (SD1-SD18) | DONE | §AA + inline; classifier defined, exit persistence, config table, gate taxonomy, +4 AC, +8 tests |
| 37 | 10:25 | Step 5: Spec Review R2 | DONE | 3 agents (sec timed out again); 2 High CONFIRMED resolved; ~6 Med/Low (atr_ratio depth, thresholds, traceability) |
| 38 | 10:40 | Step 5: Integrate Spec-R2 (SD19-SD27) | DONE | §AB; atr depth pinned, override hardened, thresholds, migration nums 49/50 |
| 39 | 10:45 | Step 5: Spec Review R3 | DONE | security PASSED (sound, 1 Low); verify agent "CONVERGED" + 3 Low fold-backs. Near-clean. |
| 40 | 10:52 | Step 5: Integrate Spec-R3 (SD28-29 + fold-backs) | DONE | price_drift wording, §Y rows, breaker constants, ack snapshot server-derived |
| 41 | 10:55 | Step 5: Spec Review R4 | DONE | 2 agents BOTH "CONFIRMED CONVERGED". 2 consecutive clean (R3→R4). |
| 42 | 10:58 | Step 5: COMPLETE | DONE | Spec final + implementation-ready. 26-field config table, classifier defined, full traceability. |

**STEP 5 COMPLETE** — Spec Review: 4 rounds, 2 consecutive clean. Resolved 2 High (BTC classifier definition, MR exit persistence) + ~22 Med/Low (atr depth, ack snapshot, thresholds, gate taxonomy, traceability). Security passed. Spec is self-contained & backend-implementable.

## PLANNING PHASE (Steps 1-5) COMPLETE
- Requirements: 10 rounds, 2 clean (~235 reqs)
- Architecture: 5 rounds, 2 clean (16 sections, modules + migrations 43-48)
- Spec: 4 rounds, 2 clean (FR-001..067, NFR, AC-001..017, full traceability)
- Total: 19 review rounds across planning. Next: Step 6 (implementation plan).

| 43 | 11:10 | Step 6: Author implementation plan | DONE | 00-summary + 6 phase files (Phase 0-5), executable detail, per-task TDD |
| 44 | 11:15 | Step 6: Plan-validation (parity + codebase-alignment) | DONE | parity: 4 contract mismatches; alignment: 5 code-reality mismatches + 1 good-news |
| 45 | 11:25 | Step 6: Apply plan-validation fixes (PD1-PD14) | DONE | rename create_child_trade, drop sync parity, fix AI-enable loc, add place_trade param, reconciler key (account,symbol,side), drop mig 49, routing_regime helper, ReasonCodes |
| 46 | 11:30 | Step 6: COMPLETE | DONE | Plan = summary + 6 phase files, codebase-aligned |
| 47 | 11:35 | Step 7: Plan Review R1 | DONE | 5 agents; 2 HIGH (kill-switch unwired, staleness unwired) + ~15 Med; NOT clean |
| 48 | 11:50 | Step 7: Integrate Plan-R1 (PR1-1..20) | DONE | kill-switch gate wired (Phase2), staleness wired (Phase4), ScanContext 2-key+prices, admin endpoint, concurrency, coverage, field count 28 |
| 49 | 12:05 | Step 7: Plan Review R2 | DONE | HIGH items CONFIRMED resolved; propagation residue (summary §D 3-tuple) + kill-switch enabled-semantics ambiguity (R2-F2) |
| 50 | 12:20 | Step 7: Integrate Plan-R2 (R2-F1..F5) | DONE | summary §D 2-key+prices, kill col renamed `killed`, slot-0 gate ordering, MR_REGIME_STALE/PRICE_UNAVAILABLE, degraded epoch, per-module coverage |
| 51 | 12:25 | Step 7: Plan Review R3 | DONE | all R2 fixes verified; 1 real residual (R3-F1: kill read inside precompute predicate = no-op for trend-only fleets) + low test items |
| 52 | 12:40 | Step 7: Integrate Plan-R3 (R3-F1/F2/F3) | DONE | kill read UNCONDITIONAL in start_scan; empty() carries kill; degraded-scan E2E; perf worst-case fixture |
| 53 | 12:45 | Step 7: Plan Review R4 | DONE | 2 agents BOTH "CONVERGED — implementation-ready". 2 consecutive clean (R3→R4). |
| 54 | 12:50 | Step 7: COMPLETE | DONE | Plan reviewed: 4 rounds, 2 clean. 2 HIGH + ~30 Med/Low resolved. |
| 55 | 12:52 | Step 8: Planning Phase Summary | DONE | plans/regime-multistrategy/08-planning-summary.md |
| 56 | 12:55 | Step 9: Create worktree | IN_PROGRESS | EnterWorktree for isolated implementation |

**STEP 8 COMPLETE** — Planning phase done. 23 review rounds, all artifacts converged, zero Critical/High. Ready for Part 2 implementation.

**STEP 7 COMPLETE** — Plan Review: 4 rounds, 2 consecutive clean. Resolved 2 HIGH (kill-switch enforcement wired + read unconditionally; staleness wired into MR) + ~30 Med/Low (ScanContext contract, codebase-reality mismatches from validation, concurrency, coverage, admin endpoint). Non-blocking v2 note: kill-switch is eventually-consistent within a scan cycle (re-read per-phase for immediate-stop).

## PLANNING PHASE (Steps 1-8) — COMPLETE
- Step 1 Discovery · Step 2 Requirements (10 rds, 2 clean) · Step 3 Architecture (5 rds, 2 clean) · Step 4 Spec · Step 5 Spec Review (4 rds, 2 clean) · Step 6 Plan + validation · Step 7 Plan Review (4 rds, 2 clean)
- TOTAL: 23 review rounds across planning. Artifacts: requirements, architecture, spec, 7-file plan.
- Next: Step 9 (worktree) → Step 12 (per-phase TDD implementation).

### Plan-R1 Decisions (PR1-1 .. PR1-18)
**HIGH (block — safety controls nullified):**
- **PR1-1 [kill-switch enforcement]:** Add `gate_kill_switch` consumed FIRST in `_try_trade` (Phase 2 pipeline): `if ctx.is_killed(feature): skip` with new `ReasonCode.FEATURE_KILLED`. Feature keys: "f1","f2","f2_long","__all__". Test `test_killed_feature_suppresses_placement()` (the AC-010 assertion, not just the row flip). Wire in Phase 2 (pipeline) + assert in Phase 4 (F2/F2-long).
- **PR1-2 [staleness wiring]:** Phase 4 TASK-4.1 MR eligibility: before entry, `if ctx.is_stale(now, cfg["regime_staleness_minutes"]): skip mr_regime_excluded (fail-closed)`. Test `test_mr_skips_when_context_stale_beyond_ttl()` + fresh-within-TTL pass.

**MEDIUM (contracts/wiring):**
- **PR1-3 [ScanContext btc-key arity]:** standardize on 2-key `(interval, lookback)` everywhere (PD8 dropped metric). Fix Phase 0 TASK-0.4 dataclass + `get_btc(interval,lookback)`; add `routing_regime(interval,lookback)` to Phase 0 helper scaffold; fix Summary D.
- **PR1-4 [golden harness stub seam]:** Phase 0 TASK-0.1 specify: patch `accounts_service.place_trade` (record args + synthetic fill) + intercept `_emit_decision` to capture skip tuples. tp/sl/qty computed inside place_trade → capture at the place_trade boundary.
- **PR1-5 [Phase 0 exit gate]:** replace `test_migration_parity.py` → `test_migration_apply.py` in validation cmd + exit criteria; drop "parity test green" clause (PD2). Update Summary C exit cell. Note arch AD14/NFR-009 parity clause VOID per PD2.
- **PR1-6 [BTC tuple scope — silent F2 break]:** Phase 1 TASK-1.4 step 2: MR-enabled/MR-cohort configs contribute their `(btc_vol_interval, btc_vol_lookback)` tuple to the BTC fetch set EVEN WHEN `btc_vol_filter_enabled` is false (else routing_regime→unknown→route none→MR never fires). Test `test_mr_cohort_with_vol_filter_off_still_classifies_regime()`.
- **PR1-7 [admin kill-switch endpoint]:** add task for `POST /admin/kill-switch` (admin authz + audit, populate updated_by/updated_at) + 403 test. Phase 4 or a small Phase 2 addition.
- **PR1-8 [ack relaxed-proof]:** Phase 4 TASK-4.5 ack gate fires under relaxed=True; `test_long_ack_required_under_relaxed()`. Add ack gate to EC-15 relaxed enumeration.
- **PR1-9 [mark_price N+1]:** fold mark price into precompute as a per-qualifying-symbol ScanContext entry (account-independent), OR per-scan per-symbol price cache; perf test asserts one price fetch per symbol. Phase 1 TASK-1.4 + Phase 4 TASK-4.1.
- **PR1-10 [precompute concurrency]:** Phase 1 TASK-1.4 use bounded-concurrency `asyncio.gather` (semaphore-capped, subordinate to rate gate) over deduped tuple-sets; state the cap; perf test asserts against it.
- **PR1-11 [single-flight scope]:** move in-flight Future map to the GLOBAL fetch/cache layer (cross-scan coalescing) keyed same as LRU, OR drop it + document concurrent cold scans may 2× fetch. Phase 1 TASK-1.3.
- **PR1-12 [coverage scope]:** Phase 5 TASK-5.6 gate = `--cov-branch --cov-fail-under=90` over ALL new modules (market_data, strategy_router, scan_context, kill_switch, pending_intents, f2_long_ack, market_data_fetch + gate predicates).
- **PR1-13 [child INSERT]:** Phase 2 TASK-2.5 explicitly extend `create_child_trade` INSERT (:669) column list +3 cols/placeholders (else partial-close child always 'trend').
- **PR1-14 [reconciler rationale + stale line]:** Phase 2 cross-phase context L14 still says `order_link_id UUID PK` — fix to `(account,symbol,side)`. Restate PD5 rationale: Bybit POSITION reconciliation returns no orderLinkId (orphans matched by symbol/side) — the orderLinkId IS sent on the order (place_market_order:410), just not available on position sync. (Correct the factual claim; design unchanged.)
- **PR1-15 [field count]:** normalize to 28 across Summary C, Phase 0 exit, Phase 5. Note arch §4 also lists `regime_filter_fail_open` which plan dropped (F1-OPEN hardcoded) — reconcile.
- **PR1-16 [per-account surface test]:** Phase 5 TASK-5.1 add per-account surface to round-trip parametrization (or assert it shares the exact AutoTradeSection mount). AC-012 names 3 surfaces.
- **PR1-17 [min-sample guard]:** Phase 5 TASK-5.5 `test_auto_disable_no_trip_below_min_sample()` (EC-14: <20 trades → no trip).
- **PR1-18 [rollback lenient test]:** Phase 0 TASK-0.3 add `test_extra_keys_ignored_on_lenient_load()` (AD7 lenient re-validation for old code) OR confirm AD20 strip step. Also update arch §4 mig 47 to (account,symbol,side) key (sync arch doc).
- **PR1-19 [migration-45 lock test]:** Phase 0 TASK-0.6 add prod-snapshot lock-window check (T-09/RV-03) or justify drop.
- **PR1-20 [batch regime_snapshots writes + retention]:** Phase 1 TASK-1.5 batch the per-config INSERTs into one write; add regime_snapshots retention/rollup.

**STEP 6 COMPLETE** — Implementation plan: 7 files (summary + Phase 0-5), per-task TDD detail, codebase-aligned (parity + alignment checks caught 9 real mismatches, all fixed). Key codebase truths: place_trade needs new strategy_kind param; create_child_trade (not create_partial_close_child); sync persistence dead (async-only migrations); close_rules NUMERIC (no mig 49); order_link_id never sent to exchange → intent keyed by (account,symbol,side) + quarantine-first.

### Plan-Validation Decisions (PD1-PD14) — from codebase-alignment + parity checks
**Code-reality fixes (CRITICAL — would break implementation):**
- **PD1:** `create_partial_close_child` DOES NOT EXIST → real method is `create_child_trade` (trade_repository.py:658). Rename in Phase 2 TASK-2.5.
- **PD2 [sync persistence is DEAD]:** sync `persistence.py` `_MIGRATIONS` is at line 211, ends at **v35** (36-42 missing), and `AnalysisDB` is NOT imported anywhere — only `AsyncAnalysisDB` is wired. DROP the sync/async byte-parity requirement (NFR-009 was predicated on both being live — false). Migrations are ASYNC-ONLY. Document: if sync is ever revived, backport 36-48. Removes the parity test (TASK-0.5) + DDL-parity (AD14) as moot.
- **PD3:** AI auto-enable trigger is in `auto_trade_service.py:1196` (`if cfg.get("ai_manager_enabled")... enable()`), NOT `ai_account_manager_service.py`. Fix TASK-4.6: the auto-enable SKIP for MR goes at :1196; the position FILTER (FR-052) goes in ai_account_manager_service.
- **PD4:** `place_trade` (accounts_service.py:199) has NO strategy param + `source` is validated to {manual,cycle,scanner}. Must ADD a new `strategy_kind` param to `place_trade` AND extend the explicit `create_trade` INSERT column list (trade_repository:136, 22-col INSERT + $N placeholders). New TASK-4.0 + update TASK-2.5.
- **PD5 [CRITICAL reconciler]:** `order_link_id` is generated INSIDE `create_trade` AFTER the exchange call + NEVER sent to Bybit as orderLinkId (place_market_order:325 omits it). So joining an orphan by order_link_id is NOT achievable. DECISION: key `pending_trade_intents` by `(account_id, symbol, side)` — the SAME tuple the reconciler ALREADY matches orphans by (position_reconciler:144-161, get_open_trades_by_symbol_side:719) — NOT order_link_id. Reconciler joins intent by (account,symbol,side) to recover strategy_kind; quarantine-first remains the always-safe fallback (reconciler already quarantines orphans w/ WS alert). Rewrite migration 47 PK + TASK-2.6 + TASK-4.4.
- **PD6 [GOOD NEWS]:** `close_rules.threshold_value` is `NUMERIC(20,8)` (async_persistence:944), already read as float (close_rule_evaluator:456,361). 0.083h stores fine. DROP migration 49 contingency entirely — no new migration for time-stop float. Simplifies Phase 4 TASK-4.3.

**Parity/contract fixes:**
- **PD7:** config field count: enumerated = 28 (26 SD10 + regime_volatile_atr + regime_trend_ema_dist_pct). Fix "26"→"28" in summary/Phase0/Phase5. (But see PD8.)
- **PD8:** `btc_vol_metric` was CUT in D9c (atr_ratio-only). Remove all `cfg["btc_vol_metric"]` reads (Phase3 TASK-3.2); metric is the constant "atr_ratio". ScanContext.btc key = `(interval, lookback)` (drop metric dim, or keep constant). Net config fields = 28 (no btc_vol_metric field).
- **PD9:** `ctx.regime` scalar doesn't exist. Add `ScanContext.routing_regime(interval, lookback) -> str` helper → looks up `btc[(interval,lookback)].regime`. route_strategy/F2 call `ctx.routing_regime(cfg.btc_vol_interval, cfg.btc_vol_lookback_candles)`. Fix Phase2 TASK-2.3, Phase4 TASK-4.1.
- **PD10:** Add missing F2 guard reason codes to Phase 0 ReasonCode enum: `MR_FEE_FLOOR`, `MR_SL_LIQUIDATION`, `MR_INVERTED_GEOMETRY`.
- **PD11:** update summary `route_strategy` signature to include `*, mr_regime="ranging"`.
- **PD12/13:** migration 45 async-only is fine (PD2 drops parity); drop migration 50 reference (no contingency needed).
- **PD14:** FR coverage matrix consolidated at Step 16; per-phase footers cover implemented FRs (acceptable for now).
- **_emit_decision real signature:** uses `**detail` not `**kw` (functionally identical — TASK-0.2 note).

### Spec-R1 Decisions (SD1-SD18)
- **SD1 [HIGH — BTC regime classifier defined]:** `market_data.classify_regime()` computes from BTC klines: `atr_ratio` = ATR(n)/SMA(ATR,n) AND `ema_distance_pct` = (close−EMA(n))/EMA(n). Rules: `volatile` if atr_ratio ≥ 2.0; `trending` if |ema_distance_pct| ≥ 1.0% (and atr_ratio < 2.0); `ranging` otherwise; `unknown` if candles < lookback. Thresholds are bounded config (defaults given). Mirrors ai_manager_regime's atr_ratio semantics but market-scoped + simpler (no MTF). Truth-table test.
- **SD2 [HIGH — MR per-trade exit persistence]:** MR per-position exit params (time-stop minutes as FLOAT-derived hours, tight-SL pct) are stored ON THE `close_rules` ROW at registration (existing table has threshold_value/reference_value/cycle_id — per-position) — NOT read from account config at eval. `post_scan_recheck` recreate sources from the existing rule row (or excludes open MR positions). NO new trades column needed; but close_rules MAX_DURATION must accept a float/minute-precision value (verify column type during planning; if INT-hours, add a per-rule minutes field — migration 49 contingency). EC-08 asserts no truncation-to-0.
- **SD3 [EC-10 fail-closed wording — recurring bug]:** Reword EC-10: "single-flight fetch fails → all awaiters see an `unavailable` sentinel; EACH applies its own policy (F1 open, F2 closed) — never a blanket fail-closed." Aligns with NFR-006/FR-014/AD1.
- **SD4 [F1 toggle hierarchy]:** `regime_filter_enabled` is the F1 UMBRELLA master; BOTH session (`session_filter_enabled`) and vol (`btc_vol_filter_enabled`) sub-modes require it. Precompute-enable predicate = `(regime_filter_enabled ∧ btc_vol_filter_enabled) ∨ F2-enabled ∨ mean_reversion-cohort`. Session-only F1 needs NO BTC precompute (session is placement-time UTC only).
- **SD5 [f1_active session-hour]:** session-hour is DERIVED from `hour(created_at AT TIME ZONE UTC)` — NO separate column. Only `f1_active BOOLEAN` added (mig 44).
- **SD6 [regime_snapshots]:** enumerate columns written (scan_id, ts, btc_regime, atr_ratio, ema_distance_pct, computed_at); confirm existing table during planning; if absent → contingency migration. Reconcile: scan-global regime → regime_snapshots table; per-scan suppressed/allowed COUNTS → run/config snapshot JSONB (two different things, both stated).
- **SD7 [pending_trade_intents lifecycle]:** delete site = after successful `create_trade`; TTL/GC sweep for unadopted intents (rejected/never-filled orders) — background cleanup like debug_trace retention; reconciler obtains order_link_id via existing position→order-history path (confirm reconciler already does this in planning).
- **SD8 [staleness TTL]:** `ScanContext` staleness TTL default = scan-interval-bounded (e.g. 30 min default, bounded config field `regime_staleness_minutes`). F2 skips if `now − computed_at > TTL`. EC-04 boundary test.
- **SD9 [TP formula explicit]:** FR-022 inline: `margin_tp_pct = mr_target_capture_pct/100 × (|entry−mean|/entry) × mr_leverage × 100`, clamped to `min(exchange_max_tp, distance_implied_max)`.
- **SD10 [config field table]:** add a canonical 23-field table (name, type, default, bounds, feature) to §H. Reconcile "~23" counters (7 F1 + 15 F2 + 1 F3 = 23; arch enumerated 26 includes 3 that are sub-fields — align).
- **SD11 [type unify]:** `strategy_kind` and `strategy_cohort` both `TEXT` with CHECK (drop VARCHAR(15)) — consistent.
- **SD12 [gate taxonomy table]:** enumerate all 13 existing gates classified trend-only / market-condition / agnostic (resolves RV-05 price_drift). price_drift = trend-only (skipped/inverted for MR).
- **SD13 [missing ACs]:** add AC-013 BTC-vol suppression (FR-012); AC-014 decorrelation+concentration warning (F3); AC-015 AI-manager MR exclusion (FR-052); AC-016 per-strategy×direction PnL view (FR-062).
- **SD14 [missing tests]:** T-15 AI-manager MR exclusion; T-16 double-exposure one-symbol-one-strategy (FR-029); T-17 fee-floor + liquidation-distance guards (FR-025); T-18 auto-disable + suppression alert (FR-065); T-19 MR counter cross-phase+resume (FR-028); T-20 recheck preserves MR params (FR-053); T-21 kill-switch master-key + read-fail-closed (FR-007).
- **SD15 [R4-21 caveat]:** add A-006 + RV-10: F1 is entry-only; if Asian bleed is dominated by positions HELD-THROUGH the session (not entered during), F1 underdelivers; session-aware exit is the v2 remedy. Document.
- **SD16 [F1-22 manual override + F3-12 concentration]:** add FR-066 (manual "run anyway, ignore session filter this scan" behind confirmation) + FR-067 (fleet concentration warning when too many accounts in one cohort).
- **SD17 [NFR-002 ≤21 → ≤account-count]:** express memo bound as "≤ account count" not literal 21 (consistent w/ 50-account NFR-013).
- **SD18 [bulk-assign user flow + AD-ref inline]:** add bulk cohort assignment as a primary §J flow; inline the one-line AD9/AD20 decisions in §W.

**STEP 4 COMPLETE** — Spec authored from converged requirements + architecture. 65 FRs, 13 NFRs, 16 edge cases, 14 test reqs, 12 ACs, 9 risks, traceability matrix.

**STEP 3 COMPLETE** — Architecture: 5 review rounds, 2 consecutive clean. Modules: market_data.py, strategy_router.py, scan_context.py. Migrations 43-48. ScanContext frozen contract. Build phases 0-5 acyclic. All R1-R5 findings (AD1-AD22) resolved including the single-flight×fail-open bug, kill-switch store, rollback boot-guard ordering, index-out-of-band, ScanContext tuple contract.

### Arch-R1 Decisions (AD1-AD14)
- **AD1 [HIGH bug — single-flight × fail-open]:** A rejected shared BTC fetch future MUST resolve to an `unavailable` SENTINEL; fail policy applied PER-CONSUMER after settle (F1→OPEN/no-suppress, F2→CLOSED/no-entry). NEVER blanket phase-level fail-closed (that would wrongly suppress trend when F1 on). Mark-price single-flight is a placement prerequisite (fail-closed both). Fix §6+§10.
- **AD2 [kill-switch store — 3 reviewers]:** New `feature_kill_switches` table (migration 48) — feature_name PK, enabled bool, updated_by, updated_at. Read = in-process cache w/ short TTL (≤30s) + read-failure FAILS CLOSED (assume killed). Shared across replicas via DB. One master "disable-all-new-features" flip + per-feature. Add §13 row + §2 path. Admin-only authed write, audit-logged.
- **AD3 [ack dual-source — 2 reviewers]:** `mr_long_ack` config field is NON-AUTHORITATIVE UI-intent only → RENAME `mr_long_ack_requested`. The `f2_long_ack` TABLE is the SOLE gate; any inbound config bool is ignored. State precedence explicitly.
- **AD4 [MR mean home + scope]:** Rescope `market_regime.py` → `market_data.py` owning BOTH BTC market regime/vol AND per-symbol EMA mean helper. MR mean precomputed AFTER extreme-score signal filtering, scoped to {qualifying MR symbols} ∩ {mean_reversion-enabled accounts} — NOT all 570. Pin ordering in §2.
- **AD5 [ScanContext freeze]:** Define `ScanContext` dataclass in new `scan_context.py`: fields = `btc_regime: Literal["ranging","trending","volatile","unknown"]`, `btc_vol_value: float|None`, `vol_unavailable: bool`, `means: dict[(symbol,period,interval), float]`, `computed_at: datetime`, `degraded: bool`. Explicit degraded flag (not absence). regime enum pinned.
- **AD6 [index on boot — deploy hazard]:** Migration 45 index built OUT-OF-BAND/post-deploy (ops step or deferred background migration), NOT on startup boot (avoids readiness-probe crashloop + multi-instance advisory-lock stall). Startup runs only catalog-only DDL (43/44/46/47/48). Document: default-off ≠ migration-free.
- **AD7 [persisted-config rollback safety]:** Use a LENIENT (ignore-extra) model for RE-VALIDATING persisted scheduled-scan configs (old code reading new-written JSONB must not 422), distinct from the strict `extra="forbid"` request-ingress model. Add to rollback runbook.
- **AD8 [perf budget + cache bound]:** Kline cache keyed `(symbol, interval, lookback-bucket)`; capacity ≥ max per-scan working set + headroom (no intra-scan eviction); state entry cap + memory estimate. Explicit latency budget: all-on adds ≤ +30s cold-cache / ≤ +2s warm vs default-off baseline (perf test threshold). MR mean memo cardinality bounded by constraining (period,interval) to small enumerated set.
- **AD9 [authz]:** Specify ownership assertion (authenticated principal owns {account_id}) on ack + cohort + kill-switch endpoints; negative test (cross-account ack → 403). If genuinely single-operator, document that + drop role language. (Confirm against existing auth in codebase during planning.)
- **AD10 [alerting]:** Add alert thresholds: F1 suppression_rate > 95% over N scans; F2-long rolling drawdown. Name metrics sink. Auto-disable circuit-breaker for F2-long that trips the kill-switch (promote DEF-3 partly — a safety auto-off, not the full breaker).
- **AD11 [/trades/stats additive]:** Retain existing top-level aggregate keys; ADD per-strategy breakdown under new `by_strategy` key (old clients unaffected).
- **AD12 [rate-gate + kline TTL]:** Kline cache TTL ≥ minimum manual-scan interval (bursts coalesce); kline fetches strictly subordinate to order placement on `bybit_rate_gate` (never delay an order) OR partitioned budgets.
- **AD13 [rollback sequencing]:** Runbook order: (1) kill-switch off → (2) close/reconcile open MR positions → (3) roll back code → (4) `UPDATE schema_version` w/ post-condition check. Verify v42 reconciler/close-rule safe on pre-existing MR positions (per-trade persisted params suggest safe — confirm).
- **AD14 [DDL parity]:** CI asserts DDL-BYTE parity across sync/async `_MIGRATIONS` (not just version-list); single shared advisory-lock key for the index across both runners.
- NOTE: migration set now 43-48 (added 48 kill-switches table per AD2).

**STEP 2 COMPLETE** — Requirements: 10 rounds, ~235 active requirements, 2 consecutive clean (R9-R10). Build order ratified acyclic (Phases 0-5). All criticals resolved: F2 place_trade TP conversion, trades migration, F1/F2 regime coupling, deploy index-lock, rollback-brick, reconciler orphan, F2-long ack, naming collision, scan-context persistence, price-drift inversion. Scope cuts: `both` cohort + breadth gate + backtest → v2.

### R5 Decisions (D22)
- **D22a (CUT): Drop `both` strategy_cohort to v2** — enum = `Literal["trend","mean_reversion"]` only. Decorrelation value comes ENTIRELY from cross-account diversity; no single account needs both. Does NOT violate D21a (that lock = F2 long+short, NOT F3 `both`-cohort). Deletes R3-15, most of R4-5/R4-10 hard cases, simplifies R2-9, R2-10/R2-52. Enum extensible for v2.
- **D22b (CUT): Drop signal-breadth gate to v2** — only chop gate with NO empirical basis; weakest proxy; trend-only; adds to trace-saturation. F1 ships with session + BTC-vol (both empirically grounded). Cut F1-4/F1-14/breadth reason + clauses.
- **D22c (NAMING): `trades.strategy_kind`** (NOT `strategy`) — avoids collision with `/strategies` router + table + `strategy_id` FK. `place_trade(strategy_kind=)`, index `idx_trades_account_strategy_kind`. `strategy_cohort` unchanged.
- **D22d: Module home** — new `backend/services/strategy_router.py` owns `route_strategy()`, `resolve_final_side()`, gate predicates, `GateChain`. Executor imports FROM it (no cycle). `market_regime.py` separate.
- **D22e: Scan-context persistence** — regime/vol/mean persist to existing `regime_snapshots` table (NOT config JSONB). Resolves R2-23↔R4-4: strip `_computed_*` from config insert; F1-20 replay reads regime_snapshots.
- **D22f: F2-long ack concrete** — field `mr_long_ack: bool` (default false) + server-side ack record (account_id, acked_at, acked_leverage, acked_capital_pct); authed write; re-ack if mr_leverage/mr_capital_pct escalate. Skip reason `mr_long_unacknowledged`. Server rejects long-fade when ack absent/stale.
- **D22g: Backtest-deferral safety** — KEEP `BacktestCreateRequest extra="forbid"` so a backtest carrying F1/F2/F3 fields FAILS LOUDLY rather than silently running trend-only.
- **D22h: Migration 44 = ONE multi-clause statement** (comma-separated ADD COLUMN, single semicolon) — both trades.strategy_kind + trades.strategy_cohort in one catalog-only statement.

### R5 New Gaps → carried into SPEC
- R5-G1 [reconciler, was BLOCKING]: encode strategy_kind in exchange `orderLinkId` at submit (reconciler reads back) + pre-submit pending-intent fallback; never silent auto-'trend' (quarantine/flag). Reconciler INSERT = a strategy_kind write site.
- R5-G2 [recheck]: post_scan_recheck rule recreate sources from per-trade persisted params OR excludes open MR positions. Test: 5-min MR stop survives recheck.
- R5-G3 [F1 efficacy]: persist `f1_active`+session-hour on allowed trend trades so trend PnL is sliceable before/after (F1 effect visible in v1 w/o backtest).
- R5-G4 [test]: fixtures/E2E/characterization/TP-oracle each exercise BOTH overbought (short fade) AND oversold (long fade, ack'd) w/ geometry assertions.
- R5-G5 [acceptance]: each toggle renders+persists+round-trips on EACH surface {manual scan, scheduled scan, per-account}. Resolve F1/F2 per-account home.
- R5-G6 [CI test]: CHECK == Pydantic-Literal set-equality, CI-gated, all enum domains.
- R5-G7 [validators]: per-feature validator helpers + single cross-field-invariant table in spec.

### R5 Supersession-Reconciliation (apply when authoring SPEC — spec is the single coherent source)
- F2-18: strike "(F1)" + global framing — routing lives in route_strategy; trend-cohort runs trend in all regimes.
- F1-2/5/6/desc: session+vol gate BOTH strategies; F1 off => no gate; regime computed when ANY consumer enabled (D8).
- SUPERSEDED (D9): F1-7/8 score_gate, F1-11 realized_vol, F2-9 list, F2-10 multi-basis — spec uses suppress-only/atr_ratio-only/scalar/EMA-only.
- AF5/R2-11/X-6/R2-34/R2-42: regime/vol/mean via scan-context (D22e), not per-config; `_computed_*` reserved for adaptive_blacklist.
- R2-45 clock rationale = test determinism. X-9 fold into R2-32. R2-17 backtest-version-coord moot.

### FINAL SCOPE DECISIONS (D21 — user, R4)
- **D21a: v1 = ALL 3 features** (F1 + F2 + F3 together). Migrations 43/44/45 in scope; plan MUST mitigate the 2 critical deploy gaps (R3-1 index-lock, R3-2 rollback-brick).
- **D21b: F2 = BOTH directions live** (reaffirmed D6). Long side: default-off, per-account opt-in, server-enforced acknowledgement (R3-20), regime-gated. RF1 risk flag STAYS VISIBLE through all reviews + UI.
- **D21c: Backtest DEFERRED to v2.** Remove from v1: X-1, X-2, X-3, X-4, R3-6, R3-7, R2-44, QA-G1 (<1% parity test). KEEP `market_regime.py` shared module (live use). KEEP `BacktestCreateRequest extra="forbid"` note ONLY as a "don't silently break" guard — but no new backtest fields added in v1 (so backtest simply ignores new config, runs trend-only — acceptable since backtest deferred).
  - NOTE: since backtest deferred, the architecture's "pure-function gate seam for live+backtest parity" (ARCH#2) downgrades from CRITICAL to RECOMMENDED — still build gates as testable pure functions (good hygiene + QA-G2 enabled-path tests need them), but no live-vs-backtest equivalence obligation in v1.

### R4 findings → all INTEGRATED into spec (Round 4 Additions section)
All ARCH#1-5, BACKEND#1-5, SEC-R4 (kill-switch storage/auth), QA-G2..G7 added. QA-G1 (<1% parity) dropped per D21c. Product G1 (bleed source: entry-time vs hold-through) + G2 (zero-decorrelation-by-default) added as open analysis items.

### R4 Critical Findings (integrate regardless of scope answer)
- **ARCH#3 (CRITICAL latent bug):** existing `price_drift` gate is INVERTED for MR — trend skips when price moved in signal dir (consumed); MR FADES and WANTS deeper extreme. Reusing `_try_trade` blindly skips MR's best setups. Golden snapshot (all-off) can't catch it. => extraction must classify each gate strategy-agnostic vs trend-only; router skips/inverts trend-only gates for MR; explicit price-drift-under-fade test.
- **ARCH#1:** `market_regime.py` is MARKET-scoped (BTC scalar) vs `ai_manager_regime` PER-SYMBOL. MR fade is per-symbol but gated by BTC regime — document MR eligibility as a market-PROXY gate; keep classifiers separate (different scope/inputs), share concept not math.
- **ARCH#2:** R2-30 gate extraction must target MODULE-LEVEL PURE functions (or stateless GateChain param'd by config+computed+clock), callable identically by live `_try_trade` AND backtest harness — else backtest reimplements → drift (defeats X-3). The seam is the purpose, not just maintainability.
- **ARCH#4:** `_computed_*` per-config channel is WRONG for scan-GLOBAL data (regime/vol/mean identical across 21 configs) + it's JSON-serialized into scans table on every scan (bloat ~570 syms). Use a scan-level context object passed to executor; reserve per-config `_computed_*` for genuinely per-config data (adaptive_blacklist).
- **ARCH#5:** `route_strategy(cohort, regime)->{trend|mean_reversion|none}` is a real component (not scattered); MUST run BEFORE strategy-scoped gates. Adaptive_blacklist gate (line 1070, strategy-scoped per R2-20/27) currently runs early — unsequenced dependency for `both` cohort (strategy unknown until routing).
- **BACKEND#1:** orphaned MR position (order fills, rule write fails) → `position_reconciler.py` (never mentioned in 208 reqs!) re-adopts as default 'trend' → cascades: MR exits never fire, AI-mgr exclusion fails, loss poisons trend blacklist. Need reconciler strategy-awareness + MR-placement partial-failure contract.
- **BACKEND#2:** `start_scan` precompute throwing (not per-symbol) must NOT abort the scan and regress core trend trading. Global try/except + degrade (F1 no suppress, F2 no MR, trend proceeds) + bounded precompute time budget.
- **BACKEND#3:** trace volume: 570×21×~10 reasons could saturate bounded drop-on-pressure debug buffer, evicting load-bearing traces. Sampling/severity-gating (per-decision skips at debug level, aggregates at info).
- **BACKEND#4:** `_AccountState` MR counter reset-vs-carry across 4 phases + resume (R2-47) unpinned — could overshoot mr_max_trades N×4.
- **SEC R4:** kill-switch's OWN storage/auth — where stored, who flips, is IT injectable via client config path? Must be server-side separate store, authed admin endpoint, audit-logged, synchronous hot-path read.
- **QA R4:** G1 no <1%-deviation equivalence test (live `_try_trade` ≡ backtest replay); G2 no all-on E2E + no per-feature ENABLED characterization snapshot (only OFF parity); G3 no canonical fixture corpus (BTC klines + per-symbol klines + extreme-score scan_results + fixed clock); G4 no TP-conversion oracle test (known exchange-correct values); G5 no fan-out perf test (fetch-count bounds + latency budget); G6 sync/async behavioral round-trip; G7 no 90% coverage target stated.

### R3 Critical Findings + Decisions
- **D12 (CRITICAL deploy):** Migration 45 `CREATE INDEX` (non-concurrent) locks `trades` writes during startup; `CREATE INDEX CONCURRENTLY` is IMPOSSIBLE in current runner (wraps every migration in `conn.transaction()`). **Resolution:** add a non-transactional migration path OR accept+bound the lock window via a prod-snapshot test. Plan must pick. INVALID-index recovery (DROP+retry) if concurrent path chosen.
- **D13 (CRITICAL rollback):** Runner boot-guard raises RuntimeError if `schema_version > max_version` → rolling code back past v42 BRICKS startup. Resolution: rollback runbook (manual `UPDATE schema_version`, confirm old code tolerates additive columns). Forward-only documented.
- **D14:** `BacktestCreateRequest` (backtest_schemas.py:35) is a HAND-COPIED flat mirror with `extra="ignore"` — new fields silently dropped → backtest runs as if features off. Must add fields explicitly + `extra="forbid"`. Backtest trade response needs `strategy` field + filter.
- **D15:** NAMING COLLISION — existing `/strategies` router + `strategies` table + `strategy_id` FK + VALID_STRATEGY_CATEGORIES. New `trades.strategy`/`place_trade(strategy=)` overloads the word. Resolution: name new column `strategy` but DOCUMENT "no relation to strategies table"; or use `strategy_kind`. Plan decides; flag in spec.
- **D16:** Missing `mr_mean_interval` (count-of-candles `mr_mean_period` has no timeframe). Add `mr_mean_interval` default "1h"; precompute key (symbol, period, interval).
- **D17:** `both`-cohort regime router must be TOTAL over regime vocab (volatile/compression/trending_up/down/ranging) — define strategy per label, not just binary. Pin classifier boundary tie-break.
- **D18:** Mean/kline precompute failure + insufficient-history (candles < period) need fail-closed skip reasons (`mr_mean_unavailable`, `mr_insufficient_history`). Min-candle guard.
- **D19:** `both`-account combined exposure ceiling: total trades ≤ account limit, `capital_pct + mr_capital_pct ≤ 100` (warn). Partial-close child inherits BOTH strategy AND strategy_cohort.
- **D20:** Frontend: account-level cohort needs an editor surface (migration-43 column); bulk-assign needs a fleet/roster multi-select view (new surface); preset apply needs preview+undo; per-strategy PnL split needs an IA home (load-bearing safety net per DEF-2).

### R2 Critical Findings + Decisions

**CONTRADICTION FOUND & RESOLVED (D8):** F1-5 ("F1 off => no regime computed") contradicts F2-2 (F2 needs scan-time regime) + F2-23 (F2 fail-closed without it) => F2-on + F1-off would mean F2 silently never trades. **Resolution:** regime/vol pre-compute is gated by "ANY consumer enabled" (F1 ∨ F2 ∨ `both`-cohort ∨ backtest), NOT by F1 specifically. F1-5 reworded: "when NO regime consumer is enabled, no regime computed."

**YAGNI CUTS adopted (D9) — simplify v1:**
- D9a: `mr_mean_basis` 3-way -> **EMA only** (drop vwap/bb_mid; VWAP needs volume-weighted intraday data we don't have cheaply).
- D9b: `regime_filter_mode` -> **suppress only** (drop score_gate mode + score_penalty — second suppression pathway, unproven benefit).
- D9c: `btc_vol_metric` -> **atr_ratio only** (drop realized_vol; doubles boundary-test surface for no evidence).
- D9d: `mr_allowed_regimes: List` -> **scalar `mr_regime` default "ranging"** (one realistic value).

**KEY ARCH DECISIONS (D10):**
- D10a: **F2 reuses existing `place_trade` TP/SL (percent-of-margin)** — F2 computes price-distance-to-mean, converts to margin-% given leverage, passes through existing params + new `strategy="mean_reversion"` arg. NO parallel place path. (Resolves backend gap #4.)
- D10b: **F2 fast exits reuse EXISTING close machinery** — tight-SL = `stop_loss_pct`; time-stop = set `max_trade_duration_hours = mr_time_stop_minutes/60` (reuses MAX_DURATION). **Range-break exit DEFERRED to v2** (YAGNI — time-stop + tight-SL + mean-TP already deliver fast exits; avoids new trigger_type + constraint migration).
- D10c: **Migrations:** 43 = `trading_accounts.strategy_cohort` (enum trend/mean_reversion/both), 44 = `trades.strategy` (enum trend/mean_reversion — NO "both") + denormalized `trades.strategy_cohort` (point-in-time), 45 = `idx_trades_account_strategy`. All mirrored into sync `persistence.py`; parity regression test. Constant-default single-statement ADD COLUMN (lock-safe, PG11+); no embedded semicolons; IF NOT EXISTS. Coordinate version numbers at merge (backtesting owns some).
- D10d: **trades.strategy** propagated through BOTH insert paths (`create_trade` + `create_partial_close_child` inherits parent) + UPDATABLE_COLUMNS audit.
- D10e: **Mean precomputed at scan-time** per distinct (symbol, period) — only `get_mark_price` stays on trade-time hot path. Single-flight dedup across 21 accounts. `_computed_*` shared by reference (immutable), not deep-copied.
- D10f: **AI Manager excludes MR positions** — MR success must NOT trigger AI auto-enable; AI manager filters strategy=mean_reversion (needs trades.strategy).
- D10g: **Code structure:** extract `_try_trade` gates into named helpers under X-10 golden-snapshot guard; `ReasonCode` enum (no magic strings); new `backend/services/market_regime.py` owns BTC vol+regime (shared live/backtest); single `resolve_final_side()` with exhaustive truth-table test.

**PRODUCT SCOPE TRIAGE (D11):**
- ADOPT in v1 (high value/low cost): recommended-defaults one-click preset; "enable affects only NEW entries" (in-flight positions keep current management); longitudinal enable/disable marker to research-history; bulk cohort assignment; AI-manager×MR interaction defined (D10f).
- DEFER to "Future Enhancements" (out of v1): shadow/observe-only mode, canary automation, before/after dashboard, A/B control framework, what-if preview, proactive nudge, periodic digest. (v1 ships the mechanism; measurement via existing debug_trace + per-strategy PnL split.)

### Key architectural findings from R1 (carry to spec)
- **AF1 (CRITICAL):** `scan_results` carry NO price (only ticker/direction/confidence/score). F2 mean-target TP needs a price reference -> must read mark price at trade-time (`get_mark_price`) + mean level from klines. Source = existing `KlineCacheService.get_klines()` / Bybit, via `bybit_rate_gate`.
- **AF2 (design):** Strong QA+security consensus that **F1 fail-OPEN** (risk-reducing filter, never blocks money path) but **F2 fail-CLOSED** (never enter a new strategy on stale/missing regime data). Documented per-feature, not global.
- **AF3 (decision):** Governing timestamp for session filter = **trade-placement UTC time** (not scan-trigger time). compute_regime/vol = scan-time (cached); session-hour bucket = evaluated at `_try_trade`. Both tz-aware UTC.
- **AF4:** F3 cohort needs BOTH a per-account persisted field (migration 43 on `trading_accounts`) AND a per-scan `AutoTradeConfig.strategy_cohort` override. Default `"trend"` = current behavior.
- **AF5:** Reuse `_computed_*` underscore-key injection (bypasses `extra="forbid"` like `_computed_adaptive_blacklist`). New keys: `_computed_regime`, `_computed_btc_vol`, `_computed_session_chop`.
- **AF6 (UX safety):** F2-long enable requires explicit acknowledgement checkbox + persistent danger Notice (negative expectancy). Server re-validates (never trust client).

---

## Key Discovery Findings (Step 1)

| Area | Finding | File:Line |
|------|---------|-----------|
| Config schema | `AutoTradeConfig` (Pydantic v2, `extra="forbid"`) — optional fields w/ defaults + `@model_validator` pairs. ALL new config fields go here. | `backend/schemas/__init__.py:426` |
| Entry gate chain | `_try_trade()` is a clean sequence of "skip if filter fails" gates, each calling `_emit_decision(...,"skipped",reason,...)`. Feature 1 = a new gate here. | `backend/services/auto_trade_service.py:1001` |
| Scan-time pre-compute | `_compute_adaptive_blacklist()` → injects `cfg["_computed_adaptive_blacklist"]` before executor runs. EXACT pattern for Feature 1 scan-time regime/vol pre-compute. | `backend/services/scanner_service.py:339,407` |
| Regime classifier (REUSE) | `compute_regime(indicators, mtf_data)` already returns trending_up/down/ranging/volatile/compression + confidence. Reusable for F1/F2. | `backend/services/ai_manager_regime.py:12` |
| Close rules (REUSE) | `close_rule_evaluator.py` already has TRAILING_PROFIT, MAX_DURATION, BREAKEVEN_TIMEOUT, EQUITY_* triggers. F2 fast-exit hooks here. | `backend/services/close_rule_evaluator.py:184,344` |
| Frontend form (BOTH) | `AutoTradeSection.tsx` is shared by manual `ScannerPage` + `ScheduledScansPage` → editing it satisfies "both forms". `ToggleRow`, `DEFAULT_CONFIG`, `onChange({field})`, localStorage `STORAGE_KEY`. | `frontend/src/components/scanner/AutoTradeSection.tsx` |
| API client type | TS `AutoTradeConfig` interface mirrors backend; add fields here too. | `frontend/src/api/client.ts:247` |
| Migrations | Registry `_MIGRATIONS: list[tuple[int, _MigrationSQL]]`; latest = **42**. Next = 43. Auto-applies on startup. SQL string or callable. | `backend/async_persistence.py:776,1223` |
| Persistence parity | TWO files: `async_persistence.py` (live) + `persistence.py` (sync). Auto-merge hazard noted in history — keep both in sync. | both files |

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/regime-multistrategy/progress-tracker.md | Step 1 | This tracker |

---

## Review Summary

| Step | Rounds | Findings (C/H/M/L) | Fixed | Deferred |
|------|--------|---------------------|-------|----------|
| (pending) | — | — | — | — |

---

## Decided Log (Cross-Reference)

| ID | Round | Decision | Reason |
|----|-------|----------|--------|
| D1 | Step 1 | Edit shared `AutoTradeSection.tsx` (not two separate forms) | It is already mounted by both ScannerPage + ScheduledScansPage |
| D2 | Step 1 | Reuse `compute_regime()` from ai_manager_regime.py | Avoid duplicate regime logic; proven classifier |
| D3 | Step 1 | Feature 1 detection pre-computed at scan-time like adaptive_blacklist | Single BTC/vol fetch per scan, injected into cfg |
| D4 | Step 1 (user) | **F2 signal source = reuse LLM `scan_results`** (not a new live-TA pipeline) | Fastest, lowest-risk, fits `_try_trade` gate chain; entries gated to scan cadence |
| D5 | Step 1 (user) | **Rollout = all 3 features live-enabled immediately** on toggle | User override of research "backtest-first". MUST stay default-off; backtest hooks still built for optional validation |
| D6 | Step 1 (user) | **F2 = BOTH directions** (long range-lows + short range-highs), live | User override of "no long trading" constraint. ⚠️ RISK: longs have negative expectancy per research. Mitigate: default-off, per-account opt-in, regime-gated, separate long-enable sub-flag |
| D7 | Step 1 (user) | **F3 cohort = `strategy_cohort` field on `AutoTradeConfig`** | Consistent w/ every per-account setting; no new table; rides existing config flow |

## ⚠️ Standing Risk Flags (carry through all reviews)

- **RF1 — Live longs in F2 contradict the data.** Research: longs = 55% WR but −$0.57/trade (negative expectancy). User chose both-directions + live. Build must make long-side: (a) default OFF, (b) per-account opt-in via explicit sub-flag, (c) only fire in confirmed `ranging` regime, (d) backtestable. Surface this in spec NFR + UI warning copy.
- **RF2 — Unvalidated strategy on live money path.** F2 is a new strategy going live without a backtest gate (user choice). Mitigate with conservative defaults (small capital_pct default, tight exits) + prominent UI "unvalidated" notice.

---

## Implementation Progress

| Phase | Status | Commit | Steps Completed |
|-------|--------|--------|-----------------|
| (defined in plan) | PENDING | — | — |

---

## Blockers & Notes

| # | Timestamp | Issue | Resolution |
|---|-----------|-------|------------|
| — | — | — | — |
