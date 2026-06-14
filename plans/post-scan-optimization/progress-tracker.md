# Progress Tracker: Post-Market-Scan Optimization

**Created:** 2026-06-14
**Last Updated:** 2026-06-14
**Current Step:** Step 2 — Requirements Brainstorm
**Status:** IN_PROGRESS
**Skill:** `/new-feature` (`~/.claude/skills/new-feature/SKILL.md`)

**Feature summary:** Optimize the post-market-scan steps — (1) live WebSocket status of post-scan auto-trade activity on the Scanner page (replace 3s polling "one-shot" view), (2) parallelize the slow sequential per-account post-scan network I/O without changing behavior (money-critical), (3) enforce Bybit non-VIP rate limits via the centralized semaphore-based `BybitRateGate` (fix public/private channel mis-assignment + add per-endpoint order limits), (4) UX/look-and-feel polish.

---

## Session Log

### Session 1 — 2026-06-14

| # | Timestamp | Activity | Status | Details |
|---|-----------|----------|--------|---------|
| 1 | 00:30 | Step 1: Codebase Discovery | DONE | Read scanner_service, auto_trade_service, bybit_client/rate_gate, event_bus, ws_manager, ws/ws_backtest routers, backtest_progress_manager, market_data, accounts_service, ScannerPage, useBacktestProgressWS, main.py wiring. Created discovery-summary.md. |
| 2 | 00:50 | Step 2: Requirements Brainstorm R1 | DONE | 5 agents (product/arch/security/qa/frontend). Security agent fetched live Bybit doc → corrected limits. +125 requirements. specs/post-scan-optimization-requirements.md |
| 3 | 01:15 | Step 2: Requirements Brainstorm R2 | DONE | 5 agents (backend/qa-interrupted/perf/product/frontend). +~52 net (R126-R165) incl. CRITICAL frontend fixes (polling fallback broken on ScannerPage, dual-renderer dup, undefined `active` predicate) & pool/cross-subsystem gaps. |
| 4 | 01:40 | Step 2: Requirements Brainstorm R3 | DONE | 5 agents (qa/integration/migration/security/product). +R166-R196. Product agent produced the KEY MoSCoW partition (~118 MUST/38 SHOULD/21 WON'T). Stopping at 3 rounds per LITE directive. |
| 5 | 02:10 | Step 2: Requirements COMPLETE | DONE | ~196 raw requirements, MoSCoW-partitioned. specs/post-scan-optimization-requirements.md |
| 6 | 02:10 | Step 3+4: Architecture + Spec | DONE | specs/post-scan-optimization-spec.md — 26 sections, 46 FR + 12 NFR, architecture decisions AD1-AD7 folded in, scoped to MUST partition (4 phases: rate-gate→WS→parallelism→UX). |
| 7 | 02:30 | Step 5: Spec Review R1 | DONE | 5 agents, code-verified, ~74 findings (7 Crit, ~16 High). Resolved via Section AA (CR-1..7, HR-1..8 + structural fixes). Key: orderLinkId idempotency was false→deterministic key; per-UID limiter keys on internal account_id; worst-case rate math (12-13 calls/placement); combined-IP ceiling; golden test strengthened; config-count scan field; canonical lock order; ban-breaker→Phase 0/MUST. |
| 8 | 03:05 | Step 5: Spec Review R2 | DONE | 5 agents, code-verified. Found R1 resolutions themselves incoherent. Section AB consolidates: SC-1 DE-SCOPE the durable-resume/orderLinkId system (pre-existing risk, not parallelization-caused); SC-2 CORRECTED rate model = PRIVATE-channel-bound ~2 placements/s (win is latency-hiding, not throughput); SC-3 lock-order arbitrated; FR-047/048/049/004a/006a normative; FF-1..4 frontend fixes. |
| 9 | 03:40 | Step 5: Spec Review R3 | DONE | 3 agents, code-verified. VERDICT: PLAN-READY (all 8 contested points resolve to 1 value under AC>AB>AA>F-Z precedence). Section AC final corrections: AC-FIX-1 (reconciler does NOT auto-adopt orphans→detect+alert+manual; position protected by inline TP/SL); AC-FIX-2..6 (FR-049 formula, shared-UID, operator-control text, ban-breaker mechanism, stale numerals). DoR fully checked. |
| 10 | 03:55 | Step 5: Spec Review COMPLETE | DONE | 3 rounds, converged PLAN-READY. specs/post-scan-optimization-spec.md (Sections A-AC). |
| 11 | 03:55 | Step 6: Create Implementation Plan | DONE | 00-plan-summary + 01-phase0-rate-gate + 02-phase1-ws-transport + 03-phase2-parallelism + 04-phase3-ux. Built from effective AC>AB>AA>F-Z. 4 phases, TDD per task, golden-equality central net. |
| 12 | 04:15 | Step 7: Plan Review R1 | DONE | 5 agents, code-verified. ~50 findings → PLAN-REVIEW-R1.md (PR1-1..13 + lows). Key: set_trading_stop is INLINE not separate; golden tuple drop orderLinkId/rule-ids; fan-out needs resizable limiter; manual tail not drainable; kill-switch polarity (ships ON, reverts); init_balances boundary; FR-037/fan-out-switch unmapped. No-migration + default=1 + ordering AFFIRMED. |
| 13 | 04:45 | Step 7: Plan Review R2 | DONE | 3 agents, code-verified. New coupling defects → PLAN-REVIEW-R2.md (PR2-1..15). Key: too_many_failures guard must move into orchestrator; register 3 new kill-switches (revert endpoint rejects them); single-renderer mount/suppress axes unified on data-presence; RateGateBanAbort caught inside per-account task; reference_value excluded from golden; acct_ordinal canonical derivation; per-account dry_run badge. |
| 14 | 05:15 | Step 7: Plan Review R3 | DONE | 2 agents, code-verified. Backend PLAN-READY; frontend 1 substantive fix → PLAN-REVIEW-R3.md (PR3-1 auto-tail active predicate covers RUNNING window since placement happens before status=completed; PR3-2..4 backend pins). VERDICT: PLAN-READY CONVERGED. |
| 15 | 05:30 | Step 7: Plan Review COMPLETE | DONE | 3 rounds. Effective plan = phase files + PR1 + PR2 + PR3. |
| 16 | 05:30 | Step 8: Planning Phase Summary | DONE | Planning COMPLETE. No unresolved Critical/High. Spec + plan converged PLAN-READY. Proceeding to Part 2 (implementation). |
| 17 | 05:35 | Step 9: Create branch + baseline | DONE | Branch feature/post-scan-optimization; baseline tests GREEN (69 passed: rate_gate + rate_limiting + bybit_client_unit). Used a feature branch (not worktree — not user-requested per tool guard). |
| 18 | 05:40 | Checkpoint with user | DONE | User: proceed as planned, all 4 phases now. |
| 19 | 05:45 | Phase 0 impl (TASK-0.1..0.7) | DONE | TDD. New: bybit_endpoints.py (registry), post_scan_flags.py (revert switches), rate_gate per-account/endpoint sub-limiter + ban-breaker + RateGateBanAbort + thread-safe wait_count, bybit_client channel routing + _do_sync_time gated + 10006 breaker, accounts_service passes account_id, features.py +3 switches, main.py wiring + flags refresher. 118 Phase-0 tests green, 114 accounts/scanner green, 0 regressions. |
| 20 | 06:10 | Phase 0 review R1 (adversarial) | DONE | 2 agents. Found CRITICAL P0-F1: per-UID 10006 (recoverable throttle) tripped a process-wide 10-min ban → global outage. Plus P0-F2 herd recovery, F4 uncapped class, F7 first-victim exception, F10 sync un-gated, DB-blip flag coupling. ALL FIXED: ban only on IP-ban signal (10018/ip-banned msg), half-open single-probe recovery, registry validation, RateGateBanAbort on trip, _do_sync_time always gated, revert flags read own key (not __all__). 153 tests green, 0 regressions. |
| 21 | 06:35 | Phase 0 commit | DONE | 927ee08 — feat(rate-limit): Phase 0 Bybit rate-gate correctness + ban breaker. 153 tests green. |
| 22 | 07:00 | Phase 0 review R2 (5 agents) | DONE | CRITICAL: half-open was dead code (herd); RateGateBanAbort(BaseException) escaped `except Exception` in 5 supervisor-less loops → loops DIE on ban. FIXED via redesign: background lanes WAIT OUT bans (raise_on_ban=False default), only lane=order raises; proper single-probe half-open + clear_ban-on-success; validate_registry out of fail-open; scanner+manual catch ban. +tests. 258 green. |
| 23 | 07:30 | Phase 0 review R3 (5 agents) | DONE | Found CRITICAL residual both backend+integration agents flagged: detection-time RateGateBanAbort raise (bybit_client:247) was LANE-INDEPENDENT → first background loop to detect 10018 crashes. FIXED: lane-gated (order→RateGateBanAbort, background→catchable BybitAPIError); ABA generation guard on clear_ban; bare "banned" removed; probe window 30s≥timeout. +tests. 126 rate-gate + 152 scanner/accounts green. |
| 24 | 08:00 | Phase 0 review fixes commit | DONE | c53c5a9 — 3 review rounds complete, all Critical/High fixed. Phase 0 CLOSED. |
| 25 | 08:05 | Phase 1 impl (TASK-1.1..1.8) | DONE | TDD. Backend: scan_progress_manager.py (per-scan pub/sub), ws_scan_progress.py (strict-origin + scan-existence + identical-close), ScanAutoTradeProgressEvent, executor progress sink (None-safe fail-open), scanner+manual wiring, auto_trade_config_count serializer field, main.py manager+router. Frontend: api/ws.ts (shared base + close-code classifier), useScanAutoTradeProgressWS hook, PostScanExecutionPanel, ScannerPage poll-through-tail + active predicate + single-renderer. 17 backend + 7 hook tests green; 1062 frontend + 136 scanner/auto-trade regression green; prod build OK. |
| 26 | 10:35 | Phase 1 review R1 (5 agents) | DONE | backend/frontend/security/integration/qa. Key: account_id leaked over WS (latent); panel terminal state was WS-only (permanent grey stepper on cold-load); postScanTailActive null-completed_at polls forever; manager replay drops terminal on long scans; no idle GC. ALL FIXED: WS wire allow-list (strips account_id/label); poll-derived `done` prop; keep scanId always; WS-terminal→invalidate; newest-biased replay; idle GC; 3-state dry_run. +fail-open _emit_progress test + WS allow-list test + manager GC/replay tests + postScanTailActive test. 150 backend + 1070 frontend green. |
| 27 | 10:55 | Phase 1 review R2 (5 agents) | DONE | Verified R1 fixes hold. New: panel grey-stepper bug (showStepper+showPersisted both true on cold-load); empty-finished flicker at WS-terminal; manager idle-GC seq-reset with live subscriber; acct_ordinal seam (must freeze canonical sorted-distinct derivation NOW for Phase 2). FIXED: showStepper gated !showPersisted; showEmptyFinished keys on poll-done; idle-GC subscriber guard; _acct_ordinal_map (sorted distinct, stamped on get_summaries); TERMINAL_STAGES single source; hook stale-connected + terminal-status alignment; cooloff self-stop. Manual-rerun WS DEFERRED per spec R165g. +panel component tests + acct_ordinal + wire-sync tests. 37+120 backend + 21 frontend green. |
| 28 | 11:05 | Phase 1 review R3 (3 agents) | DONE | backend/security CONVERGED; frontend found 1 new MEDIUM (cooloff banner freezes at ~1m — R2 self-stop regression) FIXED + tested; architecture PHASE 1 DONE + PHASE 2 READY (recorded EC-1..4 emit-contract constraints in 03-phase2 plan). 144 backend + 157 frontend green. |
| 29 | 11:25 | Phase 1 review COMPLETE | DONE | 3 rounds converged. |
| 30 | 11:30 | Phase 1 review fixes commit | DONE | 61cb557 — Phase 1 WS security + state-sync hardening. 144 backend + 157 frontend green. Phase 1 CLOSED. |
| 31 | 11:45 | Phase 2 start — re-grounded | DONE | Re-read tracker + 03-phase2 plan + first-hand reads of auto_trade_service (init_configs/refresh_configs/execute_batch/fill_immediate_remaining/post_scan_recheck/_fill_to_max/_try_trade gates/_AccountState), scanner_service (3 executor sites 707/1040/tail 1322-1424), scanner.py router (_run_auto_trade 207-356), post_scan_flags, features. CONFIRMED partition-by-account = behavior-identical: execute_batch `traded` set keyed (account_id,symbol) L829; _try_trade max_same_direction(L1594)/max_same_sector(L1606) read ONLY per-_AccountState fields (zero cross-account dep). |
| 32 | 11:50 | Phase 2 TASK-2.1 (mock BybitClient) | DONE | TDD — tests/backend/post_scan_harness.py (RecordingAccountsService/RecordingCloseService, deterministic order_id=f(acct,sym,seq), RateAwareThrottle in-flight-count 10006, FakeThrottleError) + 7 self-tests green. Models the accounts/close_svc seam the executor actually calls (place_trade kwargs = golden tuple). Throttle window spans await (fixed: sleep inside enter/exit). |
| 33 | 12:00 | Phase 2 TASK-2.3 (concurrency singleton) | DONE | TDD — post_scan_concurrency.py: get_account_semaphore() (loop-rebind + width-change recreate, default 1, MAX_WIDTH=16 clamp), effective_width() honors fanout_disabled kill-switch, try_begin_tail/end_tail single-flight per scan_id. 12 tests green. Loop-binding correctness verified (asyncio.run x2). |
| 34 | 12:10 | Phase 2 TASK-2.2+2.4 (orchestrator + partition) | DONE | TDD. auto_trade_service: execute_batch/fill_immediate_remaining refactored to per-account fan-out via _fan_out_by_account (holds self._lock around whole fan-out → external _state mutators stay excluded as before; per-account tasks run under account-sem; merge from _merge_slots in _state order, NOT gather returns). run_post_scan_tail orchestrator (5 stages, place_trades gate, persist_cb replace-by-stage, per-stage ban/error isolation, EC-1/EC-2 stage emits + global pct + terminal complete). Wired BOTH call sites: scanner_service._run_scan (cleanup+summaries now in orchestrator, runs for any executor) + scanner.py manual _run_auto_trade. Central single-flight (try_begin_tail/end_tail) on both + manual 409 checks is_tail_in_flight. EC-4: resume path re-enters _run_scan tail (already routed). main.py: configure_account_concurrency from POST_SCAN_ACCOUNT_CONCURRENCY env (default 1). 7 orchestrator + 7 golden + 12 concurrency + 7 harness + 37 auto-trade + 12 router + 107 scanner/regime green. _fill_to_max lock-assert removed (single-writer-per-account invariant). |
| 35 | 12:40 | Phase 2 TASK-2.10 + emit wiring (EC-1) | DONE | TDD. Per-account live emits wired in _fan_out_by_account (_guarded emits per-account active+done rows w/ acct_ordinal + authoritative counters via _account_trades); batch _run_account emits per-symbol placed/failed order rows (EC-1: stage=mode never terminal). Full golden expanded: rules created+deleted fingerprint + summaries width-invariant (incl init_balances rule creation + cleanup-deletes-zero-trade-rules). 10 orchestrator (+3 emit-contract) + 9 golden green. 97 broad auto-trade/MR/regime regression green. |
| 36 | 13:00 | Phase 2 TASK-2.5 (lock-order + shield) | DONE | TDD. accounts_service.place_trade: asyncio.shield(place_market_order(...)) — TP/SL inline so a cancel can't orphan an unprotected position. Verified lock-order invariant (pool=leaf): only auto_trade_service + ai_manager_task acquire position-locks, both with pool INSIDE; close_rule_evaluator/reconciler acquire none. test_place_trade_shield.py (shield-completes-on-cancel + static pool-leaf assertion). 83 accounts/trade + 3 shield green. |
| 37 | 13:15 | Phase 2 TASK-2.6 (parallelize init/recheck/cleanup/summaries) | DONE | TDD. post_scan_recheck: per-account loop → per-account tasks under semaphore w/ local execs merged in insertion order (5 account-level `continue`→`return`; inner-loop `continue`s preserved; internal self._lock placement sections serialize). cleanup_unused_rules: per-account delete fan-out. emit_account_summaries: concurrent label PREFETCH then in-order emit (debug record order-sensitive). init_balances kept SEQUENTIAL (D20 — money-safety). +recheck width-invariant golden test. 47 instrumentation+golden+orchestrator green. |
| 38 | 13:35 | Phase 2 TASK-2.7/2.8/2.9 (persist ordering + orphan + cancel) | DONE | TDD. FR-036: terminal `complete` deferred via emit_complete=False param + executor.emit_tail_complete() called AFTER final db.update_scan at BOTH call sites (scanner_service + manual router). TASK-2.8: accounts_service post-placement DB-failure handler now logs structured HIGH-severity `orphan_order` record (reconciler detects+alerts, never auto-adopts; position protected by inline TP/SL). TASK-2.9: no-services-mode full-tail green test + cancel-mid-tail-persists-placed-orders test. Discovered 2 PRE-EXISTING golden_fingerprint failures (backtest engine tie-break nondeterminism, BTC/ETH equal score=8) — exonerated Phase 2 via stash-bisect; NOT my regression, out of scope. 250 broad + 170 scanner/WS/rate-gate green; frontend tsc clean. |
| 39 | 14:00 | Phase 2 implementation COMPLETE | DONE | All TASK-2.1..2.10 done w/ TDD. 0 regressions across 420 affected-surface tests. Ready for Phase 2 multi-agent review. |
| 40 | 14:05 | Phase 2 review R1 (5 agents) | DONE | adversarial-concurrency/correctness/reliability/emit-contract/testing. Findings: CRITICAL C1+H1 (single-flight return ignored on auto path → ran tail unconditionally; manual TOCTOU _in_flight add after await + lockless manual executor). HIGH-1 (3 agents agree: ban/cancel re-raise BEFORE merge → placed orders dropped from auto_trade_results; positions safe via inline TP/SL + trades table, but audit lost). MEDIUM: phantom batch/immediate stepper rows (FE coalesces per-account stage key); multi-config live-vs-terminal counter mismatch; pct=100 at summaries pre-commit; orphan log skipped on CancelledError. ALL FIXED: single-flight now hard-gates both call sites (skip if !began); manual atomic claim before any await + _reject() helper + position_lock_registry wired; fan-out merges BEFORE re-raise + per-account slot published in finally + orchestrator _run_stage drains _last_partial_merge on ban/cancel/error; FE builds byStage only for pure stage events; summaries pct capped 95 (only complete=100); orphan log catches (Exception, CancelledError) + re-raises cancel. +HIGH-1 ban-abort-survival test + FE phantom-step test. 146+93 backend + 15 FE green; tsc clean. |
| 41 | 15:00 | Phase 2 review R2 (5 agents) | DONE | adversarial-merge/single-flight/integration/backend-fresh/testing. Verified R1 HIGH-1 fix correct. NEW: CRITICAL (2 agents) manual single-flight SKIP path still ran db.update_scan([]) → clobbers in-flight tail's persisted results (full-column overwrite); HIGH _in_flight_auto_trades leak (db.get_scan/json.loads raise between .add and task-spawn → scan permanently 409-bricked); HIGH CancelledError re-raise from fan-out uncaught at call-site (BaseException) → skips DB commit+terminal; MEDIUM double/premature terminal on skip path; MEDIUM cross-path manual-init/auto-tail overlap on resumed scans; MEDIUM width-change semaphore split. ALL FIXED: manual skip now returns early (no DB write, no terminal); validation region wrapped try/except BaseException→discard claim; fan-out distinguishes real outer-cancel (current_task().cancelling()) from stray child-cancel (logs, continues); manual try_begin_tail moved BEFORE init_balances (covers force-close/rule-create); width-split documented as accepted. +strengthened HIGH-1 test (accB persist + no-double-persist) + in_flight-release integration tests + ban-persist-partial test. 190+90 backend + 15 FE green; tsc clean. |
| 42 | 15:50 | Phase 2 review R3 (5 agents) | DONE | adversarial/integration/backend-fresh/data-integrity/simplicity. 3 agents CONVERGED explicitly (concurrency R2-fixes-correct; integration both-call-sites-consistent + proved auto-skip UNREACHABLE via DB-status-gate ordering; data-integrity sound). NO new code Critical/High. Closed remaining items: MEDIUM-2 recheck partial-preservation on cancel (finally-merge sets _last_partial_merge); MEDIUM-1 orphan-on-cancel-during-submission (ensure_future + drain + orphan log + re-raise); LOW-1 recheck RateGateBanAbort re-raise parity; simplicity (removed dead _=ordinals, documented load-bearing reset, consolidated duplicate discard into single except-net owner). +stray-child-cancel test + manual-409-when-central-held test (+claim-release tests). 209 Phase2 + 189 cross-phase + 15 FE green; tsc clean. |
| 43 | 16:30 | Phase 2 review COMPLETE | DONE | 3 rounds converged. R1 Crit/High → fixed; R2 Crit/High → fixed; R3 no new code Crit/High, gaps closed. |
| 44 | 16:35 | Phase 2 commit | IN_PROGRESS | — |          

## Implementation Progress

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| Phase 0 (rate-gate) | ✅ DONE (3 review rounds) | 927ee08, c53c5a9 | Ban breaker money-safety |
| Phase 1 (WS) | ✅ DONE (3 review rounds) | (committing) | Live status; account_id wire-stripped; poll-derived done; acct_ordinal seam; Phase-2-ready |
| Phase 2 (parallelism) | ✅ DONE (3 review rounds) | (committing) | Orchestrator + bounded fan-out (default w=1 byte-identical); golden-equality; HIGH-1 merge-preservation; single-flight + TOCTOU hardened; FR-036 ordering; orphan-safe; live emits EC-1..4 |
| Phase 3 (UX) | PENDING | — | — |

**Deferred to Phase 3 (tracked):** admin-endpoint trust-boundary hardening (TASK-3.3), per-tail feasibility auto-reduce refinement, P0-F5 deque eviction (low), P0-F8 sync-lane reservation (low), P0-F11 WS-accounting confirmation (low).

---

## Planning Phase Summary (Step 8)

**Status:** COMPLETE — ready for implementation. Zero unresolved Critical/High findings.

**Artifacts:**
- `specs/post-scan-optimization-requirements.md` (~196 reqs, 3 brainstorm rounds, MoSCoW)
- `specs/post-scan-optimization-spec.md` (Sections A-AC; 3 review rounds; effective AC>AB>AA>F-Z)
- `plans/post-scan-optimization/00-plan-summary.md` + 4 phase files
- `plans/post-scan-optimization/PLAN-REVIEW-{R1,R2,R3}.md` (3 review rounds; effective phase+PR1+PR2+PR3)

**Key decisions that shaped the work (surface to user):**
1. **Speedup is latency-hiding, NOT throughput.** Bybit's PRIVATE rate limit (100/5s) bounds the tail to ~2 placements/s aggregate regardless of account count. Parallelism overlaps per-call RTT (today each account pays full network round-trips serially) → ~4-5× at N=10, then plateaus. Honest framing in NFR-002.
2. **De-scoped a durable crash-resume system** (deterministic orderLinkId / tail-in-progress sub-state): the crash-resume double-placement risk is PRE-EXISTING (R108/109), not caused by parallelization, and the proposed mechanism was impossible against the schema. Resume stays no-worse-than-today.
3. **Ships default concurrency=1** (sequential, byte-identical) behind runtime kill-switches; width>1 is operator opt-in after the DoD gate (golden-equality + speedup + zero-10006).
4. **Phase 0 (rate-gate correctness + ban-breaker) is a hard prerequisite** to Phase 2 (parallelism).
5. **No DB migration** (reuses existing JSONB columns + config-derived fields).

---

## Review Summary (updated)

| Step | Rounds | Outcome |
|------|--------|---------|
| Step 5 (Spec) | 3 | R1 ~74 findings→AA; R2 incoherent-resolutions→AB (private-bound rate model, de-scope resume); R3 PLAN-READY→AC. |
| Step 7 (Plan) | 3 | R1 ~50 findings→PR1; R2 coupling defects→PR2; R3 CONVERGED→PR3. |

**Spec Review summary:** R1 (~74 findings → Section AA), R2 (R1-resolutions incoherent → Section AB, major: private-bound rate model + de-scope durable-resume), R3 (PLAN-READY → Section AC final corrections). Effective spec = AC > AB > AA > F-Z.

**WORKFLOW MODE CHANGE (user directive ~01:30):** Switch to LITE workflow — keep ALL steps, but reviews run a meaningful **~3 rounds** each (not full 2-clean convergence, not just 1). User instruction overrides the project default convergence rule.

**Note:** Parallel Agent (Explore) dispatch returned transient `400 Bad Request` / `tool_use_id` errors repeatedly; pivoted to direct first-hand file reads for discovery (more reliable, gives direct code knowledge). Will retry agents for review rounds.

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/post-scan-optimization/discovery-summary.md | Step 1 | Codebase discovery findings |
| plans/post-scan-optimization/progress-tracker.md | Step 1 | This tracker |

---

## Review Summary

| Step | Rounds | Findings (C/H/M/L) | Fixed | Deferred |
|------|--------|---------------------|-------|----------|
| Step 5 (Spec) | — | — | — | — |
| Step 7 (Plan) | — | — | — | — |

---

## Decided Log (Cross-Reference)

| ID | Round | Decision | Reason |
|----|-------|----------|--------|
| D1 | Step 1 | Mirror BacktestProgressManager pub/sub for post-scan progress (not EventBus) | Simpler, proven, per-run history replay + terminal GC already solved |
| D2 | Step 1 | Parallelize across ACCOUNTS (independent), preserve within-account symbol ordering | Accounts have separate BybitClient/state; symbol order is best-score-first slot fill |
| D3 | Step 1 | Fix bybit_client channel: public endpoints → channel="public" | get_mark_price/instrument/kline wrongly consume private budget today |
| D4 | Step 1 | Both call sites (scanner_service tail + scanner.py manual re-run) must get progress + parallel | Avoid divergent behavior |
| D5 | Spec R1 | Placement idempotency = deterministic `orderLinkId` keyed (scan_id,account_id,symbol), written to pending_intents pre-submit; resume source = trades+pending_intents (NOT in-memory buffer) | orderLinkId was minted fresh per call → no real dedup (CR-1/HR-3) |
| D6 | Spec R1 | Per-UID rate limiter keys on internal `account_id` (1:1 with BybitClient), not a resolved Bybit UID | test_connection returns uid=None; no resolver exists (CR-2) |
| D7 | Spec R1 | Rate ceiling/feasibility computed on WORST case (~12-13 calls/placement incl. 7 fill-polls; peak=10·N) | _poll_order_fill multiplier under-counted (CR-3) |
| D8 | Spec R1 | Add a combined-IP counter hard-stop ≤540/5s; pin public=400+private=100 | two independent deques never enforced 600 ceiling (CR-4) |
| D9 | Spec R1 | Golden test = per-account ORDERED sequence + full payload tuple + close-rule create/delete + counts (exact, 0%) | "order set+counts" blind to ordering/payload/rules (CR-5) |
| D10 | Spec R1 | Add scan-level `auto_trade_config_count` to both serializers + ScanStatus; predicates read it, not local state | _serialize omits configs → cold-load freeze (CR-6) |
| D11 | Spec R1 | Canonical lock order: account-sem → position-lock → client-sem → gate(leaf) → DB-pool; never block on pool holding a position-lock | deadlock vector widened by fan-out (CR-7) |
| D12 | Spec R1 | Ban breaker (R74)+near-ban detector→Phase 0/MUST; gate fails-fast on ban so registry lock releases | registry-lock-across-ban starves protective close (HR-1) |
| D13 | Spec R1 | R135/R139/R136-R138 promoted SHOULD→MUST | R183 resume depends on R135 idempotency (HR-2) |
| D14 | Spec R1 | Operator controls gate on TCP PEER loopback + token, not server bind; handle Vite proxy XFF | trusted-LAN bind makes "non-loopback" the norm (HR-5) |
| D15 | Spec R2 | DE-SCOPE durable crash-resume (deterministic orderLinkId + trades-table re-derivation + tail-in-progress) → backlog. Resume stays no-worse-than-today; incremental persist = replace-by-stage; orphan→structured log→reconciler DETECTS+ALERTS (NEVER auto-adopts, AC-FIX-1)→manual intervention; position protected by inline TP/SL | resume risk is PRE-EXISTING (R108/109), not parallelization-caused; pending_intents has no order_link_id col; 2 unreconciled uuid mints; executor has no scan_id (SC-1) |
| D16 | Spec R2 | Rate ceiling is PRIVATE-channel-bound (~2 placements/s aggregate, 100/5s ÷ ~10 private calls). Speedup = latency-hiding up to private cap, then plateau. Feasibility projects PRIVATE load, not IP | of ~12-13 calls/placement only 2 are public; private saturates first (SC-2) |
| D17 | Spec R2 | Drop the inert 540 combined-counter; per-channel pin (400+100=500<600) + per-account_id/endpoint sub-limiter + feasibility auto-reduce are sufficient; ≤480 is observability-only | combined len can never exceed 500 so 540 counter is dead code (SC-2c) |
| D18 | Spec R2 | Lock order: trade-row write stays UNDER position-lock (pool=leaf); deadlock-free via invariant "no subsystem acquires a position-lock while holding a pool conn"; canonical order acct-sem→pos-lock→client-sem→gate→pool | CR-7 was self-contradictory (SC-3) |
| D19 | Spec R2 | set_trading_stop + fill-polls use lane=order (complete-an-open-position); free-text detail/label omitted from WS payload (log-only); FE renders from enums only | protective calls must not starve; raw error strings leak (FF-4) |
| D20 | Phase 2 (2.6) | SCOPE init_balances OUT of parallelization — keep it sequential. Parallelize ONLY the tail loops (post_scan_recheck per-account, cleanup_unused_rules per-account, emit_account_summaries label-prefetch). | init_balances is a one-time PRE-scan state machine with 5 interdependent cross-iteration caches (rules_created_for/positions_cache/account_valid_cache/emitted_scan_start/marked_stopped_for), a force-close→validate barrier, per-CONFIG (not per-account) iteration, and ~10 `continue` early-exits. Parallelizing it = near-total rewrite, high bug risk on a money path, for marginal one-time gain. The user-visible win (NFR-002 latency-hiding) is in the TAIL, already delivered by the execute_batch/fill partition + recheck. Money-safety > marginal init speedup (user directive: "not introducing any bugs"). |

---

## Implementation Progress

| Phase | Status | Commit | Steps Completed |
|-------|--------|--------|-----------------|
| (phases TBD in plan) | PENDING | — | — |

---

## Blockers & Notes

| # | Timestamp | Issue | Resolution |
|---|-----------|-------|------------|
| 1 | 00:45 | Agent tool (parallel Explore) returns 400 errors | Pivoted to direct reads; will retry for multi-agent reviews |
