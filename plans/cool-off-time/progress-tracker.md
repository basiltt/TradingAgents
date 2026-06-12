# Progress Tracker: Cool Off Time

**Created:** 2026-06-11
**Last Updated:** 2026-06-11
**Current Step:** Step 5 (Spec Review) — folding R1 findings
**Status:** IN_PROGRESS
**Active Skill:** /new-feature (multi-agent convergence, minimal rounds)

---

## Feature Summary

Account-specific "Cool Off Time" for auto-trade. 4 optional settings, all default OFF:
1. Success cool off — pause after a winning cycle
2. Failure cool off — pause after a losing cycle
3. Double-success cool off — pause after 2 consecutive winning cycles
4. Double-failure cool off — pause after 2 consecutive losing cycles

Duration configurable (hours/minutes). Enabled per-account from BOTH the Scheduled
Market Scan auto-trade settings AND the Market Scan auto-trade settings. Must work in
BOTH live trading and backtesting. Handles real money — extreme care required.

---

## Session Log

### Session 1 — 2026-06-11

| # | Time | Activity | Status | Details |
|---|------|----------|--------|---------|
| 1 | — | Step 1: Codebase discovery | DONE | Direct exploration (Agent tool 400-erroring); mapped live + backtest + frontend |
| 2 | — | Step 2: Requirements brainstorm | PENDING | — |

---

## Step 1 — Discovery Findings (KEY REFERENCES)

### Live auto-trade path
- `backend/services/auto_trade_service.py` — `AutoTradeExecutor` (class @ L74). Scanner builds a FRESH executor per scan (scanner_service.py:564, :894), calls `init_configs()` → `init_balances()` → `execute_batch()`/`post_scan_recheck()`.
- **Existing pause pattern to MIRROR:** `_is_account_paused(account_id)` @ L346. Checks the account's active `PAUSE_TRADING` close rule: `reference_value` = ISO start time, `threshold_value` = hours. Elapsed >= hours → rule deleted (not paused); else paused. Fail-CLOSED on unparseable, fail-OPEN on list error. Called in `init_balances` (L483) and `post_scan_recheck` (L1006). Sets `state.stopped=True, stopped_reason="ai_paused_trading"`.
- Per-account runtime state: `_AccountState` (trades_executed, trades_failed, base_capital, stopped, stopped_reason).

### Cycle lifecycle (separate engine)
- `backend/services/trading_cycle_engine.py` — `TradingCycleEngine` (L112). `_finalize_cycle()` @ L542 writes terminal status + `stop_reason` + `completed_at`. `on_rule_triggered()` @ L587. Wired in main.py:407-428.
- `backend/services/cycle_repository.py` — `trading_cycles` table CRUD. `final_pnl`, `stop_reason` columns.
- NOTE: scheduled/manual scan auto-trading uses AutoTradeExecutor (per-scan), NOT TradingCycleEngine (which is the manual "trading cycles" router feature). The "account-level cycle" the user means = one scan's auto-trade execution for an account.

### Win/Loss determination (UNIVERSAL RULE)
- **`is_win = net_pnl > 0`** — `signal_performance_service.py:152` (live), backtest `pnl > 0` (`backtest_engine.py:1657`).
- Backtest `_close_position` @ L1954 computes `recorded_pnl` net of fees+funding; trade dict has `pnl`, `exit_time`, `symbol`, `strategy_kind`.

### Config schemas (mirror across all)
- `backend/schemas/__init__.py` — `AutoTradeConfig` @ L444 (`extra="forbid"`!). Optional pattern: `Optional[float] = Field(None, gt=0, le=720)`. Model validators @ L519+.
- `backend/schemas/backtest_schemas.py` — `BacktestCreateRequest` @ L40 = FLAT mirror of AutoTradeConfig. Has its own validators mirroring AutoTradeConfig.
- `frontend/src/api/client.ts` — `AutoTradeConfig` TS interface @ L326.

### Backtest engine
- `backend/services/backtest_engine.py` — `BacktestEngine.run()` @ L221. Main loop @ L395 iterates `scan_order` chronologically. `current_time = scan_signals[0]["signal_time"]` (simulated clock @ L403). `SimulationState` @ L165 has `cycle_active`, `cycle_start_time`, `scan_entered` (per-scan), `closed_trades`.
- Time-gated filter precedent: `_is_adaptively_blacklisted` @ L1597 (rolling win-rate from `state.closed_trades` within lookback window) — closest pattern for cool-off in sim time.
- `_apply_filter_chain` @ L1021 — 18-step filter; cool-off would gate at scan/cycle level (before processing signals), not per-signal.

### Scheduled scan storage
- `scan_scheduler_service.py` (L36) — schedules store `scan_config` JSON (schemaless blob) which contains `auto_trade_configs: [AutoTradeConfig,...]`. So new fields flow automatically once schema accepts them.

### Migrations
- `backend/async_persistence.py` — `_MIGRATIONS` list @ L1027, applied on startup (`_apply_migrations` @ L1650). Currently at **v60**. Pattern: `(N, "ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")`. `trading_cycles` table @ L1222.
- `emergency_cooldown_until TIMESTAMPTZ` (ai_manager_state, L297) — precedent for a persisted cooldown timestamp.

### Frontend UI
- `frontend/src/components/scanner/AutoTradeSection.tsx` — SHARED component, used by BOTH `ScannerPage.tsx:1053` (market scan) AND `ScheduledScansPage.tsx:1460` (scheduled). One change → both surfaces. `DEFAULT_CONFIG` @ L18. Optional toggle+number pattern @ L711-810 (breakeven/trailing). Uses `clampNumberOrNull`, `NeuSwitch`, persists to localStorage.
- `RegimeStrategyFields.tsx` — precedent for a grouped optional-feature block mounted in AutoTradeSection.

---

## Artifacts Created

| File | Step | Purpose |
|------|------|---------|
| plans/cool-off-time/progress-tracker.md | Step 1 | This tracker |

---

## Decided Log

| ID | Round | Decision | Reason |
|----|-------|----------|--------|
| D1 | User Q | Outcome decided by the close-rule that ENDED the cycle: EQUITY_RISE_PCT / BALANCE_ABOVE = success; EQUITY_DROP_PCT / BALANCE_BELOW = failure. Plain TP/SL / max_duration / breakeven endings produce NO outcome (no cool-off). EQUITY_DROP_PCT_SMART excluded (partial, cycle continues). | User choice; most money-precise; maps to explicit hooks in live (close_rule_evaluator:356-372) + backtest (equity_rise/close_on_profit vs equity_drop). |
| D2 | User Q | When both single + double qualify on the same event → DOUBLE overrides single (use double duration). | User choice; predictable, no stacking. |
| D3 | User Q | Active cool-off blocks the WHOLE account (all schedules + manual scans), mirroring existing account-wide PAUSE gate. Duration from the config of the cycle that just completed. | User choice; safest for money path. |
| D4 | User Q | UI: one number field + Minutes/Hours unit selector per setting. Stored canonically as minutes. | User choice; matches existing single-field optional pattern. |
| D5 | Self | Streak (consecutive_count) advances only on classified (equity-rule) terminations; resets to 1 on opposite outcome. >=2 same-outcome in a row = "double" tier. | Consistent with D1 trigger model. |
| D6 | Self | LIVE enforcement = dedicated per-account state table + new gate `_is_account_in_cooloff` (mirrors `_is_account_paused` fail-closed/fail-open conventions); NOT reusing AI PAUSE_TRADING rules. | Streak tracking already needs persisted state; isolation safer than overloading AI-manager pause semantics; survives restart. |
| D7 | Self | BACKTEST enforcement = `SimulationState` fields (cooloff_until, last_cycle_outcome, consecutive_count); gate at scan-processing entry mirrors skip_if_positions_open (no new entries, still evaluate open positions). Uses simulated `current_time`. | Single-account in-memory sim; parity with live semantics in sim time. |
| **D8 (CRITICAL)** | R1 verify | LIVE outcome hook = `close_rule_evaluator.py:360` (rule transitions to "executed"), NOT the cycle-engine `_cycle_callback`. VERIFIED: scan auto-trade creates EQUITY_RISE_PCT/EQUITY_DROP_PCT rules WITHOUT cycle_id (auto_trade_service.py:558-585), so `_cycle_callback` (gated on `rule.get("cycle_id")`, L366) never fires for the scan path. The :360 executed-point is universal. Classify by `rule["trigger_type"]`. | Money-correctness: the agents assumed _cycle_callback; that hook is dead for the user's primary surface (scheduled/manual scans). |
| D9 | R1 synth | Streak semantics: neutral (non-equity-rule) cycle endings are TRANSPARENT (neither advance nor reset streak); opposite classified outcome resets other side to 1; after a DOUBLE fires, that side resets to 0; re-arm while active = max(existing, new) (never shorten). TRAILING_PROFIT/MAX_DURATION/BREAKEVEN/SMART/server_restart/user_stopped = neutral. | Capital-safe (transparent can only make double-protection fire more readily, never less); standard; consistent across live+backtest. |
| D10 | R1 synth | Idempotency: streak+arm keyed by a stable cycle/rule identity; atomic single-statement upsert; classifier is a pure, total, never-throwing shared function (live+backtest) taking `now` + trigger_type as inputs. | Concurrency/retry safety on a money path. |
| D11 | R1 synth | Fail policy for the NEW cool-off gate: unparseable cooloff_until → fail-OPEN (allow trade), log ERROR, reset bad value; transient DB error → fail-OPEN, log WARNING. DELIBERATELY opposite to PAUSE's fail-closed, because cool-off is risk-reduction pacing (not a safety halt) and fail-closed-on-garbage risks unbounded silent lockout. Read-side clamp: cooloff_until > now+MAX → corrupt→reset. | Security agent R9/R10/R11; documented asymmetry. |
| D12 | User Q | v1 INCLUDES a manual "Resume now / clear cool-off" control + backend endpoint (audited, confirm dialog). Clearing nulls cooloff_until/reason; does NOT reset streak counters. | User choice. |
| D13 | User Q | Disabling a cool-off trigger affects FUTURE cool-offs only; an already-active pause runs to its expiry (early end only via the explicit Resume-now control from D12). | User choice; clean separation of "stop future" vs "end current". |
| D14 | User Q | Backtest: enforce cool-off in sim + report "signals skipped by cool-off" stat (by trigger) + shaded cool-off bands (ReferenceArea) on the equity-curve chart. | User choice; best for pre-live evaluation. |

## Step 2 — Requirements Brainstorm Log

| Round | Agents | New reqs | Notes |
|-------|--------|----------|-------|
| R1 | product, architecture, qa, frontend, security | ~200 (raw) | Strong grounding; surfaced D8 (critical hook correction). Consolidating to specs/cool-off-time-requirements.md. Open scope Qs → user. |
| R2 | backend, qa(backtest), frontend | ~30 NEW (criticals) | NOT converged. Decisive findings below. Outcome model (D1) proven mostly INERT → re-confirm with user. |

## Step 2 — Round 2 Critical Findings (must resolve before spec)

**CF1 (CRITICAL — outcome model inert):** With D1 ("outcome from the close-rule that ended the cycle"), the live hook only fires when account-level equity rules exist:
- EQUITY_RISE_PCT created ONLY when `target_goal_type=="profit_pct"` (auto_trade_service.py:554). → success/double-success NEVER arm otherwise.
- EQUITY_DROP_PCT created ONLY when `max_drawdown_pct<100` (L576) AND not smart (smart→EQUITY_DROP_PCT_SMART, excluded). → failure/double-failure NEVER arm otherwise.
- Most cycles end via per-position TP/SL → NO classified outcome → cool-off effectively dead for typical configs.
- **→ Re-confirm outcome model with user (they likely didn't know C is mostly inert).**

**CF2 (wiring):** close_rule_evaluator is a separate long-lived service; close_rules has NO metadata/JSONB column; durations can't reach the :360 hook today. Options: (A) add close_rules.metadata JSONB, (B) snapshot durations into account_cooloff_state at rule-create. IF outcome model moves into the AutoTradeExecutor (equity-delta at cycle boundary), this wiring problem dissolves — executor already holds state.config + base_capital snapshot.

**CF3 (backtest terminators):** backtest closes via breakeven (L2505) & max_duration (L2518) WITHOUT setting cycle_start_equity=0; per-position tp/sl/liquidation/trailing/backtest_end never zero the cycle. close_reason→outcome map must be explicit; backtest_end must NOT arm.

**CF4 (backtest equity ref):** check_equity_drop (L2267) has no `cycle_start_equity>0` guard; a cool-off skip that preserves a zeroed anchor → spurious drop math. Need guard + defined equity ref during skip.

**CF5 (no-regression):** new filter_stats keys / band fields change serialized JSON even when OFF → must emit cool-off keys ONLY when feature ON (preserve byte-identical golden).

**CF6 (frontend status source):** `TradingAccount` (client.ts L753) has NO status field; live badge needs either a new `accountsApi.getCooloffStatus(id)` endpoint (mirror getAiManagerStatus L1528) or cooloff fields added to DashboardCard. CoolOffFields (config) must be separate from the live badge/Resume-now (status) — backtest form has no account.

**CF7 (idempotency):** recover_stuck_triggered_rules (async_persistence:3256) can re-fire a rule → double-arm; idempotency guard (last_processed key) must be atomic with the executed transition. Keyed by rule_id (UUID) for scan path / cycle_id for engine path.

**CF8 (minor, fold into spec):** streak transition table must be explicit (set vs accumulate); "double" threshold = 2 (hard-coded, document); 4 triggers enumerated = success/failure/double-success/double-failure; hours-decimal→minutes needs Math.round; gate must run before post_scan_recheck state resets (L1022); cool-off gate before skip_if_positions_open counter (one bucket).

## Step 2 — Round 3 (post-model-switch) + Outcome model RESOLVED

**D15 (SUPERSEDES D1/D8):** Outcome model switched to **NET REALIZED P&L AT FLAT** (user re-confirmed after CF1 evidence). A cycle = the scanner/cycle-source trades one scan opens for an account; it COMPLETES when the account has zero open auto-trade positions (went flat). Cycle outcome = sign of summed `net_pnl` of that cycle's trades: >0 success, <0 failure, ==0 neutral (no cool-off). Universal `is_win = net_pnl > 0` rule. Fires on ALL completed cycles regardless of close path (TP/SL/equity-rule/duration). This makes CF1/CF2 (close-rule hook inertness + close_rules.metadata wiring) OBSOLETE.

**Live hook feasibility (VERIFIED):**
- `trades` table (async_persistence.py:50) = source of truth: account_id, net_pnl, closed_at, status, source ('scanner'|'cycle'|'manual'), source_id. `idx_trades_active` (L108) defines open = status IN ('open','partially_filled','closing','partially_closed').
- Close paths funnel through: `trade_service._close_full` (L289 close_trade) [rule/manual], `trade_service.reconcile_close` (L340) [reconciler], both set status='closed'+net_pnl and call invalidate_stats_cache. `position_reconciler._reconcile_account` (L99) is per-account with exchange truth.
- → "Account went flat" detector is feasible at a post-close chokepoint. Exact centralized design = ARCHITECTURE (Step 3). Must: detect open-auto-trade-count→0 transition, sum the cycle's net_pnl, classify, update streak, arm cool-off — atomically, idempotently, across all close paths.
- Cool-off "cycle" deliberately EXCLUDES manual (source='manual') trades — only auto-trade ('scanner'/'cycle') cycles count.

**Backtest hook (VERIFIED via CF3/CF4):** classify at the point a scan's positions all close in sim. backtest already sums per-trade pnl; "cycle" P&L = sum of the scan-cohort's recorded pnl. Gate new entries when current_time < cooloff_until (mirror skip_if_positions_open). close_reason→outcome is by P&L SIGN now (not trigger type), which sidesteps CF3's terminator-mapping problem; backtest_end close still counts toward final cycle P&L but a cool-off armed at/after the last signal has no later scan to block (clamp bands to report end). cycle_start_equity>0 guard (CF4) still relevant for drop math but independent of cool-off.

**Step 2 status:** Requirements comprehensive (~230 across 2 rounds + model resolution). Model now locked (D15). Remaining hook-design uncertainty deferred to Step 3 (Architecture) which has its own review loop. Consolidating to specs/cool-off-time-requirements.md, then one targeted round-3 gap-check on the net-PnL-at-flat model to confirm convergence.

| R3 | backend, qa(backtest) | 11 NEW (architecture-level) | NOT converged at req level, but all NEW findings are ARCHITECTURE concerns (cohort key, 3rd close path, partial-child double-count, cross-path race, cycle-engine premature-arm, backtest flat model). Folded into specs (CO-DET-8..12, CO-BT-14..19). → triggers Step 3 (Architecture) where they get designed + reviewed to convergence. Requirements doc now 120 reqs; Step 2 COMPLETE. |

## Step 2 — COMPLETE
Requirements doc: specs/cool-off-time-requirements.md (120 tagged requirements). Outcome model locked (D15 net-P&L-at-flat). Round 3 confirmed the remaining open questions are all architecture-level (cohort grouping, flat-detection chokepoint across 3 close paths, partial-child summation, cross-path race serialization, cycle-engine interaction, backtest single-site flat hook). These are the agenda for Step 3.

## Step 3 — Architecture Review Log

| Round | Agents | Findings | Status |
|-------|--------|----------|--------|
| R1 | architecture, backend, database, qa(backtest), security | 1 CRITICAL, 6 High, ~12 Med, ~10 Low | NOT converged. Major redesign required (decouple arming from close txn). |
| R2 | security, backend, qa(backtest), architecture, database | R1 CRITICAL confirmed RESOLVED. New: 2 crit (doc-correctness), ~6 High, ~6 Med/Low. | NOT converged. All NEW are refinements of the deferred-classifier design w/ clear fixes (D31-D42). Fold + R3. |
| R3 | backend, qa(backtest), architecture | 0 crit, 3 High, ~4 Med/Low (mostly doc-consistency) | NOT converged but strong downward trend. Fixes D43-D49 (no contested decisions). Fold + R4. |
| R4 | backend, qa(backtest), architecture | 0 crit, 1 High, 3 Med (all narrow/clear) | NOT converged; trend continues down. Fixes D51-D54. Fold + R5. |
| R5 | backend, qa(backtest), architecture | backtest CLEAN; 2 trivial doc nits (pseudocode constant, "singleton" wording) | 1st near-clean round. Nits fixed (no design change). R6 to confirm 2nd clean. |
| R6 | backend, architecture | CONVERGED — both "no new findings" | **2nd consecutive clean round → Step 3 CONVERGED.** Architecture locked. |

## Step 3 — COMPLETE (CONVERGED at R6)
Architecture doc: specs/cool-off-time-architecture.md. 6 review rounds; convergence signature
1crit→2crit→0/3H→0/3M→nits→clean. 50 decisions logged (D1-D54). Core design LOCKED:
- Deferred CooloffClassifier (own txn, NEVER in close path) — driven by post-commit trigger +
  60s sweep + gate-time sync call. Settlement guard (exit_price<>0 OR net_pnl<>0) + 26h
  staleness escape. Composite (closed_at,id) high-water idempotency. source='scanner'-only
  arming+gating. Shared pure cooloff_core.decide() for live+backtest. account_cooloff_state
  table (migration v61), no trades-table change. Two column-scoped settings writers. Backtest:
  single-site _close_position hook + 3 gate sites + funding-excluded net (pnl+funding_paid) +
  OFF byte-identical via state.cooloff_enabled.

### R4 Findings → Resolutions (Decided Log)
- **D51 (XR-R4-F1 — STALE_MIN margin):** STALE_MIN must EXCEED the reconciler horizon by more than the max backfill SELECT→COMMIT lag (the reconciler selects eligible rows at `closed_at > now−24h` but commits the UPDATE seconds-to-minutes later). Set STALE_MIN = 24h + reconciler_interval + max_paging_time ≈ 26h (NOT equal to 24h). Corrects D43's "must not drift" → they MUST drift by that lag so the classifier only escapes after any in-flight backfill has provably committed.
- **D52 (YR-R4-F1 — cooloff_enabled threading in backtest):** Add `SimulationState.cooloff_enabled: bool = False`, initialized in run() at SimulationState construction from `any(4 tiers enabled in config)`. `_close_position` reads `state.cooloff_enabled` to gate the `trade_record["funding_paid"]` persist (OFF ⇒ key absent ⇒ byte-identical golden). §7 names state.cooloff_enabled as the gate source.
- **D53 (ZR-R4-F1 — §3 D21 leftover):** Remove the stale "config-save path AND the executor at cycle start" wording in §3; point to §11's authoritative two-writer model (config-save for scheduled + un-gated init_balances pre-pass before L461 for manual+freshness). Fix "cycle start"→"scan start".
- **D54 (ZR-R4-F2 — scanner_service DI home):** AutoTradeExecutor.__init__ gains cooloff_repo + cooloff_classifier kwargs (None-guarded). Injection: (a) router (scanner.py) passes from request.app.state; (b) scanner_service builds (L564/L894) self-construct CooloffRepository(self._db) from its existing ctor _db handle (scanner_service has _db, no app handle) and read the classifier from a main.py attribute-stamp on app.state.scanner_service (mirroring the existing L449 `app.state.scanner_service._ai_manager_service=...` pattern). main.py adds the cooloff wiring (currently none).

### R3 Findings → Resolutions (Decided Log)
- **D43 (XR-R3-F1 — settlement signal + staleness vs reconciler horizon):** "Settled" ⇔ `status='closed' AND (exit_price<>0 OR net_pnl<>0)` (placeholder writes BOTH exit_price=0 AND net_pnl=0.0, so it's caught; a reconciler-backfilled row with real net_pnl but missing avgExitPrice is caught by net_pnl<>0). Staleness escape (D32) fires ONLY for an episode whose max(closed_at) < now − RECONCILER_BACKFILL_HORIZON (the reconciler's 24h give-up window, position_reconciler.py:119) — so a recoverable backfill is never pre-empted; only a genuinely-abandoned trade is advanced-as-neutral + ERROR alert. STALE_MIN is DEFINED as that 24h horizon (documented coupling, single source).
- **D44 (YR-R3-F1 — backtest funding_paid):** Persist `trade_record["funding_paid"] = position.funding_paid` on EVERY backtest close, but add the key ONLY when cooloff_enabled (OFF ⇒ key absent ⇒ byte-identical golden). Remove the "compute from live position before close" alternative (broken for multi-trade cohorts — only the last trade has a live Position).
- **D45 (YR-R3-F2 — episode boundary equality, parity-critical):** Flat boundary rule, IDENTICAL in live + backtest: two consecutive scanner trades are in the SAME episode iff `next.opened_at <= prior.closed_at` (intervals touch/overlap); a strict gap `next.opened_at > prior.closed_at` ⇒ SPLIT. Equal timestamps (next.opened_at == prior.closed_at) ⇒ SAME episode (touch = merge)... NO: pin to MATCH backtest behavior — backtest closes the carried position in the next scan's pre-open _evaluate_window so the book empties → SPLIT. THEREFORE the canonical rule both engines implement: episode boundary (flat) occurs when open scanner count reaches 0 at any instant; a close at time T and an open at time T leave the account flat at T ⇒ SPLIT. Live orders by (closed_at,id) and treats a close as taking effect before a same-instant open. Documented + tested with an equal-timestamp fixture in BOTH engines.
- **D46 (ZR-R3-F2/F3 — settings writer model, RESOLVED to TWO writers):** Settings snapshot has TWO writers, both column-scoped (settings cols only): (1) the config-save path for SCHEDULED scans (POST/PATCH /scheduled-scans → persists immediately, survives even if the scan never runs, handles toggle-off); (2) an UN-GATED PRE-PASS in AutoTradeExecutor.init_balances over self._state.values() BEFORE the L461 stopped-check (mirroring the existing close_on_profit pre-pass at L403-410) — handles MANUAL scans (no persisted config-save) AND keeps the row fresh even when the account is cooling off/paused/positions-open. Correct D36's "sole writer" wording → "two column-scoped writers." Manual-scan rationale: manual scan config is ephemeral, so the executor pre-pass is the only place its settings can be captured.
- **D47 (ZR-R3-F1 — out of scope):** Add to requirements Out-of-Scope: "Cycle-engine / source='cycle' cool-off gating AND arming (TradingCycleEngine honors no gate in v1, matching the existing PAUSE_TRADING limitation)." Fix §5 pointer.
- **D48 (ZR-R3-F4 — DI source):** main.py stashes a singleton CooloffRepository (+ CooloffClassifier) on app.state; scanner_service + scanner.py router read app.state.cooloff_repo at executor-build time (mirroring app.state.accounts_service threading) and inject (None-guarded). trade_service.set_cooloff_classifier wired in main.py after both built.
- **D49 (ZR-R3-F5 — wording):** §13 checklist reworded: "gate covers all SCAN auto-trade for the account; cycle-engine ungated (D35)" (not "whole-account").
- **D50 (XR-R3 low — pool safety):** The gate must NOT be mid-txn / holding a pooled conn when it calls maybe_classify (which acquires its own conn) — avoid pool starvation. Gate reads + classify use separate sequential acquisitions, not nested.

### R2 Findings → Resolutions (Decided Log)
- **D31 (SR-F2/BR-F1 — settlement signal + resume window):** Operative "settled" signal = `exit_price<>0` (the `_handle_close_failure` placeholder path writes exit_price=0, net_pnl=0.0; reconciler backfills). Guard = `status='closed' AND exit_price<>0 AND net_pnl IS NOT NULL`. The GATE (at scan start, before opening) triggers a synchronous best-effort `maybe_classify(account_id)` BEFORE reading cooloff_until → eliminates the resume-window for rule-driven closes. Reconciler-driven exchange closes inherit the system's existing ≤60s close-detection latency (a position isn't DB-flat until the reconciler closes it, so the account isn't eligible to arm OR to re-trade-while-flat early); documented as inherent.
- **D32 (SR-F1 — head-of-line starvation):** Staleness escape hatch — if the earliest unprocessed episode stays unsettled > STALE_MIN (e.g. 30m), advance the high-water past it as NEUTRAL + emit ERROR alert + metric, so one permanently-stuck trade can't starve all future cool-offs.
- **D33 (QR-F1 — canonical episode net, VERIFIED):** LIVE episode net = `SUM(net_pnl)` directly (Bybit net_pnl = closedPnl − fees, ALREADY funding-excluded). BACKTEST net = `sum(pnl + funding_paid)` (backtest recorded pnl is funding-INCLUSIVE: price_pnl−fees−funding; adding funding_paid back yields price_pnl−fees). Both = realized P&L minus trading fees, funding EXCLUDED. classify_outcome on the sign.
- **D34 (QR-F5 — OFF golden):** Backtest computes the funding-excluded net at classify time; any new per-trade field (funding_paid) is added to the sim trade dict ONLY when cooloff_enabled, OR the result serializer is confirmed to whitelist fields. Preserve byte-identical OFF golden.
- **D35 (AR-F1 — SCOPE, supersedes part of D3):** Cool-off GATE reaches the SAME surface as the existing PAUSE_TRADING gate: the AutoTradeExecutor path = scheduled + manual SCAN auto-trade. The manual TradingCycleEngine (source='cycle') places via accounts.place_trade and honors NO gate (not even PAUSE) → NOT gated by cool-off in v1, consistent with the existing PAUSE limitation. "Whole-account" = all scan auto-trade for the account (matches the user's feature). Documented; cycle-engine cool-off out of scope.
- **D36 (AR-F2/F3 — settings writer + DI):** AutoTradeExecutor gets a CooloffRepository/service injected at its 3 live build sites (scanner_service scheduled L564 + manual L894, scanner.py router), None-guarded like _close_svc (backtest-equivalent inert). The executor at init_balances is the SOLE settings-snapshot writer (covers BOTH manual + scheduled; manual scans have no persisted config-save). Config-save path need not write settings.
- **D37 (AR-F4 — classifier wiring):** trade_service gets the classifier via a deferred setter set_cooloff_classifier (mirror set_trade_service), wired in main.py after both are built; avoids constructor cycle.
- **D38 (BR-F2/F3, DR-F1/F2 — composite high-water key):** Idempotency/episode key = composite `(closed_at, id)` with `last_processed_close_at` + `last_processed_close_id`; predicate `(closed_at, id) > (mark_at, mark_id)` NULL-safe via COALESCE(mark,'-infinity'). Served by existing idx_trades_account_closed (account_id, closed_at DESC, id DESC). Prevents tie-skip/double-count.
- **D39 (BR-F5/F6, QR-F4/F6 — boundary + windows):** Flat-boundary reconstruction loads opened_at+closed_at; on equal timestamps apply closes(−1) before opens(+1); classifier reads all candidates in ONE snapshot under the advisory lock (no per-iteration re-COUNT). ORDER BY (closed_at, id) in BOTH live + backtest as the deterministic tiebreaker. Gated backtest post-recheck window = [evaluate_from_time, next_scan_start] (NOT scan_started_at — the [scan_started_at, post_recheck_time] window is already evaluated at L454-455; avoid double-eval).
- **D40 (SR-F3/F4 — task safety):** Post-commit trigger uses the safe pattern (store task ref in a set + add_done_callback to discard) and wraps the SCHEDULING in try/except so it can never raise out of a committed close. Doc reworded: "repository close methods + the close transaction are unmodified"; trade_service close methods gain only the post-commit trigger line strictly AFTER the txn context exits.
- **D41 (BR-F4 — netting convention):** Episode net sums net_pnl over ALL episode rows INCLUDING partial children (no parent_trade_id IS NULL filter). Mandatory test asserts a partial-then-full close sums both portions to true realized P&L; verify parent/child net_pnl accounting during impl (TDD).
- **D42 (SR-F5 — lock discipline):** Classifier trades-table reads are plain SELECT/COUNT (ACCESS SHARE); NEVER FOR UPDATE/FOR SHARE (would conflict with the close's row-exclusive UPDATE and reintroduce indirect blocking).

### R1 Findings → Resolutions (Decided Log additions)
- **D16 (CRITICAL — AR-F1/BR-F1/BR-F5/SR-F1/SR-F2):** Arming MUST be fully decoupled from the close transaction. A cool-off error must NEVER roll back or delay a position close. RESOLUTION: classification/arming runs in a SEPARATE transaction, never inside close_trade/reconcile_close. Implemented via a deferred classifier (post-commit best-effort trigger + periodic sweep safety net), each idempotent. Close path is 100% untouched.
- **D17 (HIGH — BR-F2/AR-F1/SR-F5/QR... deferred PnL):** net_pnl is NOT final at close-commit (reconciler backfills via direct UPDATE). RESOLUTION: the deferred classifier only classifies an episode once ALL its trades are fully SETTLED (status='closed' AND exit_price<>0 AND net_pnl NOT NULL); otherwise it waits for the next sweep. Never classify on placeholder/null pnl.
- **D18 (HIGH — QR-F1 funding parity):** Canonical episode-net = realized P&L net of FEES, EXCLUDING funding, in BOTH engines. Backtest cool-off cohort sum uses (pnl - entry_fee - exit_fee), NOT funding-inclusive recorded_pnl. Documented; keeps live==backtest sign.
- **D19 (HIGH — AR-F2/F4/F5/SR-F3 cycle engine):** EXCLUDE source='cycle' from cool-off arming in v1 (the cycle engine has no final_pnl and the user's feature targets scan auto-trade). Cool-off classification keys on source='scanner' only. The account-level GATE still blocks ALL auto-trade (scanner+cycle) when armed (whole-account D3 preserved). Resolves the §3/§5 inconsistency + CO-LIVE-9 (forced terminations N/A).
- **D20 (HIGH — AR-F3/OQ1 streak-when-OFF):** Amend CO-STREAK-7: streak tracking BEGINS when cool-off is first enabled for the account (a settings row with any tier enabled exists). Scanner trades stamp episode key only when the account has cool-off configured. First fully-tracked episode is the first that can arm. (Avoids maintaining hidden state on every close for default-off accounts.)
- **D21 (HIGH — DR-F2/AR-F6/DR-F3 settings snapshot):** account_cooloff_state holds an ACCOUNT-GLOBAL settings snapshot. Writers use COLUMN-SCOPED upsert (settings cols only; never touch cooloff_until/streak/seq). Config-save path upserts settings synchronously on every change. Cool-off is account-level (D3) so cross-schedule divergence is unsupported — last-saved wins; UI treats cool-off as an account setting.
- **D22 (Med — BR-F3 idempotency):** Idempotency guard is MONOTONIC: skip if episode_seq <= last_processed_cycle_seq (not ==), so a late/out-of-order stale episode cannot regress state.
- **D23 (Med — BR-F4 pending trades):** "Account flat / new episode" counts ALL non-terminal auto trades INCLUDING 'pending' (unfilled limit/MR pre-submit), not just idx_trades_active statuses, so a pending leg doesn't fragment an episode or trigger premature flat.
- **D24 (Med — QR-F2/F3/F4 backtest gates):** Backtest mirrors live's TWO gate sites: re-check cool-off at the real open instant (post_recheck_time) AND selection_time, not one pre-branch gate. Cooled branch still evaluates carried positions over the SAME window the non-cooled branch uses (only opens are suppressed). live_selection branch is gated too (or documented out-of-scope + asserted).
- **D25 (Med — QR-F5/QR-F6 OFF-identical + terminal):** Bands/skip stats live in the existing `summary` dict, emitted only when cooloff_enabled (no new typed top-level response field). Terminal-flatten suppression scoped strictly to close_reason=='backtest_end' (NOT all forced closes — live_selection_sync flats are real).
- **D26 (Med — SR-F6 lazy-expiry):** Lazy-expiry is a GUARDED conditional UPDATE: `SET cooloff_until=NULL WHERE cooloff_until=<value_read> AND cooloff_until<=now`, so it cannot clobber a concurrently-armed fresh value.
- **D27 (Med — SR-F8 clamp):** Read-side corruption clamp threshold strictly GREATER than max legal duration (e.g., 31d), so a legitimate 30d arm is never false-reset.
- **D28 (Low — SR-F4 authz):** Clear + status endpoints enforce the SAME per-account ownership authz as other account mutations; audit captures actor, account_id, reset_streak flag, before/after cooloff_until.
- **D29 (Low — DR-F1/F7/F8):** account_cooloff_state: omit ON DELETE CASCADE to match ai_manager_state (NO ACTION) OR comment-justify; add CHECK ((cooloff_until IS NULL)=(cooloff_reason IS NULL)), CHECK (wins>=0 AND losses>=0), CHECK (*_minutes IS NULL OR BETWEEN 1 AND 43200); use two-arg pg_advisory_xact_lock(classid, hashtext(account_id)) to isolate from migration lock.
- **D30 (Low — BR-F8/AR-F9):** Episode-grouping by closed_at high-water-mark (not requiring a seq column on children) — children's own closed_at places them in the cohort naturally; OR if seq column used, create_child_trade must explicitly copy parent seq (tested). Architecture picks closed_at-window grouping to avoid open-path changes (see revised §4).

---

## Blockers & Notes

- Agent/Explore subagent tool returns API 400 this session → discovery done via direct Grep/Read (complete).
- Open product questions to confirm with user before spec (see Step 2).

## Step 5 — Spec Review Log

| Round | Agents | Findings | Status |
|-------|--------|----------|--------|
| R1 | product, backend(401 err), qa, security, frontend | 0 crit; ~6 High; ~20 Med; ~10 Low — all spec-completeness (FRs summarized FE/test detail; ACs thin) | NOT converged. Fold S-fixes; re-run backend agent that 401'd. |

### Step 5 R1 Findings -> Resolutions (Decided Log)
- DS1 (SPR-F1/SFR-F1 High): Add FR-024 — backtest results FRONTEND rendering (MetricsGrid skipped stat + EquityCurveChart cooloffBands prop + legend + default-ON toggle, sourced from run.results; absent when OFF) + AC-011.
- DS2 (SFR-F2/SPR-F3 High): Add FR-025 — frontend validation: inline error, unit-aware [1,43200] bounds, BLOCK Save/Launch, identify offending account+tier.
- DS3 (SSR-F1 High): Add NFR-009 — an active cool-off MUST NOT delay/skip close-rule eval, TP/SL, duration, equity, trailing closes; the stopped flag gates only NEW-entry selection (closes run in close_rule_evaluator/position_reconciler, which do NOT read executor.stopped). + AC-012 (open position still closes on schedule during cool-off).
- DS4 (SQR-F2 High): Define completion_time = max(closed_at) of the settled episode (the flat instant), NOT detection wall-clock; live arm-time == backtest arm-time for the same episode. Update FR-007 + AC-001.
- DS5 (SQR-F3/F8 High): Define "byte-identical" precisely (AC-005): checked-in golden SimulationResult from master on fixed data; assert exact equality of json.dumps(result, sort_keys=True), zero float tolerance; determinism (AC-006) compares the FULL result incl cooloff_bands + signals_skipped_cooloff.
- DS6 (SQR-F4/F5 High + SSR near-zero): Pin funding_paid SIGN convention (signed cost; backtest net = pnl + funding_paid for both + and - funding) + test. AC-007 scoped to non-marginal episodes (|net|>epsilon); near-zero documented as tolerance-bound (fee/slippage models differ live vs backtest). 
- DS7 (SQR-F1 High): Add AC for equal-timestamp episode boundary SPLIT (live + backtest fixture).
- DS8 (SSR-F3 Med->High-if-no-auth): Name the exact per-account ownership primitive both endpoints use; assert it is a real enforced control; ACs for 403 non-owner + 404 unknown on BOTH status + clear; state threat model (localhost operator tool); CSRF on clear if cookie-auth.
- DS9 (SQR-F6 Med): FR-008 explicitly hooks ALL THREE close chokepoints (close_trade, reconcile_close, close_trade_record_only) + _handle_close_failure branch; discrete test obligations for sweep + gate-time-sync drivers.
- DS10 (SQR-F9/F10 Med): Enumerate duration boundary tests (0 reject,1 accept,43200 accept,43201 reject, NaN/Inf/non-int reject); resolve clamp threshold to 31d (margin over 30d max) consistently in spec §S + arch.
- DS11 (SQR-F11 Med): Add AC — double-overrides-single when BOTH enabled (reason=double_failure, dur=120 not 60/180).
- DS12 (SSR-F5 Med): Gate-blocking predicate is a PURE time comparison: block iff cooloff_until IS NOT NULL AND now < cooloff_until; lazy-expiry is cleanup only — a failed expiry UPDATE never extends a block. + AC.
- DS13 (FE batch, Med/Low SFR-F3..F15): Add NFR-010 (cool-off UI a11y: switch roles, Min/Hr radiogroup, aria-describedby errors, aria-live throttled countdown, prefers-reduced-motion, text-not-color) + NFR-011 (responsive reflow, >=44px targets, badge truncation, dark/light parity). Expand FR-021 (grouped layout, defaults-on-enable + OFF-preserve, display-inference Hr rule) + FR-022 (badge data source = status endpoint, 3 mount points, distinct-from-PAUSE, countdown authority = server remaining_seconds anchor, conditional polling 15-30s, zero-tick refetch, invalidation set, loading/error/empty/404 states). Add FR-026 (ScannerPage pre-launch cooling-off warn/confirm). Add FR-027 (render cooloff_active stopped_reason in scan/lifecycle UI).
- DS14 (SPR-F5/F9/F13 Low): Add Assumptions — streak tracked only while >=1 tier enabled (supersedes CO-STREAK-7 literal); streak account-scoped shared across scheduled+manual+cohorts; account-global settings cross-surface last-saved-wins surfaced in UI.
- DS15 (SPR-F8 Med): Add edge/AC — scanner force-close on shutdown/restart must NOT misclassify/arm (non-trading termination => no outcome).
- DS16 (SPR-F11 Low): MCP accounts/config payload exposes the 8 fields (CO-API-3) — add to §K or note deferred.
- DS17 (SQR-F13/F20 Med/Low): Add edges — cancelled/never-filled scan (no flat transition, no outcome); duration 0/neg reaching engine => past cooloff_until => no block.
- DS18 (SQR-F16/F17 Med): Test obligations — ERROR on corruption-reset + staleness-escape, WARNING on transient fail-open; init_balances settings pre-pass runs BEFORE stopped-check (cooling-off account still refreshes snapshot).

| R2 | backend, product, qa, security(CONVERGED), frontend | 1 High, ~7 Med, ~3 Low; security clean | NOT converged. Fixes DS19-DS26 (incl 2 arch-doc fixes + 1 real clobber bug). Fold + R3. |

### Step 5 R2 Findings -> Resolutions (Decided Log)
- DS19 (SBR-R2-F5 REAL BUG — settings clobber): The manual-scan init_balances pre-pass must NOT downgrade an enabled persisted tier to OFF using a manual config whose cool-off defaulted OFF from localStorage. Rule: writer-2 (executor pre-pass) upserts cool-off settings ONLY when the in-hand config has >=1 tier enabled (explicit opt-in); an all-OFF manual config does NOT overwrite the account row. config-save (scheduled) remains the authoritative writer. A user disables cool-off via the scheduled config or Resume-now, not by launching an all-OFF manual scan.
- DS20 (SBR/SPR FR-028 scope): Scanner auto-trade has NO engine shutdown-force-close path (that is the cycle engine only); scanner positions left open on restart are reconciled as REAL exchange closes (legitimately count). So the only non-trading termination for scanner = trades that cancel/never-fill (account never went non-flat -> no flat transition -> no outcome). Re-scope FR-028 to that; remove the shutdown-force-close half (no discriminator needed).
- DS21 (SQR-R2-F1 epsilon vs FR-005): FR-005 stays EXACT: ==0 -> neutral (no dead-band). AC-019/AC-007 reframed: given IDENTICAL inputs (fills/fees/funding/close prices) live and backtest compute the SAME canonical net (realized_pnl - fees, funding-excluded) and the sign matches EXACTLY — no epsilon. NFR-005 <1% is a separate AGGREGATE real-world goal (different fee/slippage models), NOT a per-episode AC. Drop "epsilon" wording.
- DS22 (SQR-R2-F2 byte-identical mechanism into spec): AC-005 text states: a golden SimulationResult is captured from master on a fixed dataset and checked in; the OFF-branch run asserts exact equality of json.dumps(result, sort_keys=True) (zero float tolerance); relies on the cooloff_enabled-gated unchanged code path (FR-020).
- DS23 (SQR-R2-F4 STALE_MIN concrete): STALE_MIN = 1560 minutes (26 hours) exactly (= reconciler 24h horizon + 2h margin for interval+paging). Used verbatim in FR-009/AC-018 + arch.
- DS24 (SFR-R2-F1 Hr-unit): Drop the contradictory display-inference. The Min/Hr unit selector is STICKY per-card edit state (not re-derived each render): defaults to Min, or Hr if the stored minutes %60==0 and >=60 on FIRST load; thereafter the user's selection persists. Stored value is always integer minutes (Hr entry -> Math.round(value*60)). Validation bounds against the SELECTED unit. Allow 1-decimal hours on input but minutes is the source of truth.
- DS25 (SFR-R2-F2 polling bootstrap): When >=1 account on the page has cool-off tiers ENABLED, run a baseline status poll (e.g. 30-60s) + window-focus refetch so a newly-armed cool-off surfaces even from the not-cooling state; additionally invalidate cooloff-status on scan-complete / scheduled-run settle. (Not only Resume-now.)
- DS26 (SBR-R2-F4 head-of-line — accept+document): The single monotonic high-water forces in-order episode processing; one permanently-stuck earlier episode can delay arming of later settled episodes up to STALE_MIN (26h). Accepted for v1: rare (needs a stuck trade), bounded by the staleness escape, and the gate-time sync classify handles the common just-completed-cycle path immediately. Documented in §S/Risks (R6).
- DS27 (SBR-R2-F2 index claim): NFR-006 must cite idx_trades_account_status_created (not idx_trades_active, whose partial predicate excludes 'pending') for the open-scanner COUNT; OR keep idx_trades_active and drop 'pending' from the count. Decision: the open-count includes 'pending' (D23) so cite idx_trades_account_status_created. Arch §8 note corrected.
- DS28 (SBR-R2-F1 arch contradiction): Arch §3 classifier pseudocode arming line corrected from now()+minutes to episode.max_closed_at+minutes (matches spec FR-007). Arch §10 settlement guard corrected from AND/IS NOT NULL to the OR form (matches §3/FR-009).
- DS29 (SBR-R2-F7 status endpoint): GET status — a known account with NO account_cooloff_state row returns 200 with cooloff_until=null, streaks=0 (NOT 404); cooloff_remaining_seconds = max(0, until-now); now>=until reported as not-cooling regardless of lazy-expiry. (404 only for unknown account.)
- DS30 (§Y / missing ACs): Add ACs for FR-025 (block save/launch on invalid enabled tier), FR-026 (pre-launch warn), FR-027 (cooloff_active reason rendered distinct), FR-028 (cancel/never-fill -> no outcome), FR-030 (MCP fields present). Keeps the §Y invariant true.

| R3 | backend, product, qa(CONVERGED), frontend | 2 unapplied-fix (NFR-006 index, FR-022 polling were logged but not edited into canonical FR/NFR), 1 stale S2 bullet, 1 Hr-display edge | NOT converged — fixes were in tracker but missed canonical spec text; now applied (DS27/DS25/DS20/DS24 into FR-022/NFR-006/§N/S2/FR-021). + DS31. |

### Step 5 R3 Findings -> Resolutions
- DS31 (SBR-R3-F2b pending-count vs FR-028): RESOLVED via clarification, not a conflict. Pending-inclusive open count is correct; a place-then-cancel order resolves to status='cancelled' (terminal, non-open) so it never created a non-flat->flat transition that fabricates an episode. Documented in NFR-006.
- Applied to canonical text: NFR-006 (idx_trades_account_status_created + pending rationale), FR-022 (polling bootstrap), §N (index name), S2 bullet (restart=real close, not no-arm), FR-021 (Hr-display full-precision, never re-round canonical minutes).

| R4 | backend, product(CONVERGED), frontend | 1 expanded-FR-022 leftover (ONLY-while-cooling in K2), 1 NFR-006/FR-028 wording (reason vs flatness) | NOT converged — both pure wording; fixed. |
| R5 | backend, frontend(CONVERGED) | 1 wording propagation (FR-028/AC-024/S2 still said "no flat transition") | NOT converged — same fix propagated to FR-028/AC-024/S2 ("empty closed-trade set" not "never went non-flat"). |

| R6 | backend(CONVERGED) | "no new findings" | **All 5 perspectives converged → Step 5 COMPLETE.** |

## Step 5 — COMPLETE (CONVERGED)
Spec: specs/cool-off-time-spec.md — 70 FR/NFR/AC items, all traced to requirements + decisions (D1-D54, DS1-DS31).
Convergence: security R2, product R4, qa R3-R4, frontend R5, backend R6 (each 2 consecutive clean or clean-then-stable). No unresolved Critical/High. Spec is implementation-ready.

## Step 6 — COMPLETE
Plan: plans/cool-off-time/implementation-plan.md — 6 phases, 23 tasks, traceability matrix, rollback, manual-verify, DoD. Verified file refs (MetricsGrid/EquityCurveChart exist; accounts.py uses _get_service/_validate_id, no per-user ownership -> AC-017 403 N/A for this localhost tool).

## Step 7 — Plan Review Log

| R1 | backend, qa(backtest), frontend, security, product | 0 crit; 3 High; ~18 Med; ~8 Low | NOT converged. Fixes DP1-DP18 (real algo/integration catches + test gaps). Fold + R2. |

### Step 7 R1 Findings -> Resolutions (Decided Log)
- DP1 (PBR-F1 Med — LIMIT divergence): fetch_unprocessed_closed has NO LIMIT (match arch — the open==0 flat-gate guarantees complete episodes). If a bound is kept for safety, MUST loop/re-fetch and NEVER classify a partial run. Spec/plan: remove LIMIT n.
- DP2 (PBR-F2 High — post_scan_recheck gate loop shape): the L1006 gate action must EXACTLY mirror the PAUSE block L1008-1012: `for state in states: state.stopped=True; state.stopped_reason="cooloff_active"` then `continue` — BEFORE the L1022 reset block. Written explicitly in P3-3 (not "single state").
- DP3 (PSR-F1/PPR-F1 High — cardinal-invariant test MISSING): add test_auto_trade_cooloff_closes_unaffected (CR-2/AC-012/NFR-009): (a) close_rule_evaluator output byte-identical with/without cooling, (b) close_on_profit pre-pass still fires for a cooling account, (c) cooling account + open position hitting TP/SL still closes. Wire to §R. + backtest analog (PSR-F4): carried position closes inside a cool-off band identically to OFF.
- DP4 (PFR-F1 High — backtest form reuse): CoolOffFields cannot drop into BacktestConfigForm (react-hook-form: CheckField/ToggleNumberField bound to BacktestCreateRequest, no onChange(partial)). Split P6-1: (a) {config,onChange} component for AutoTradeCard; (b) a separate RHF block (CheckField+ToggleNumberField) in BacktestConfigForm. Do NOT claim single-component reuse.
- DP5 (PFR-F2 High — ReferenceArea on categorical X-axis): EquityCurveChart X-axis is categorical (dataKey="label", lossy formatTsLabel). Band x1/x2 (arbitrary timestamps) won't match category values. Decision: attach a per-row band membership flag to the charted data and shade rows whose ts falls in a band (avoids the number-axis refactor); OR convert XAxis to type="number" time-scale. Pin the row-flag approach in P6-4 (lower-risk). Also add the ReferenceArea import note (PFR-F5).
- DP6 (PSR-F2 Med — unguarded upsert fail-open): wrap the P3-3 settings pre-pass upsert per-account in try/except -> log WARNING, continue (NFR-001 — never abort a scan).
- DP7 (PSR-F3 Med — CLAMP_MAX_DAYS unused): apply it. On arm: cooloff_until = min(computed, now + CLAMP_MAX_DAYS). On read (repo.read_status): cooloff_until > now + CLAMP_MAX_DAYS -> treat corrupt -> cooling=False + log ERROR + best-effort reset (CR-4). Add test.
- DP8 (PQR-F1 Med — backtest settings plumb): P5-5 must stash self._cooloff_settings = CooloffSettings(...) in run() (alongside cooloff_enabled); the P5-2 hook reads self._cooloff_settings. Add to P5-1 attr list.
- DP9 (PQR-F2/F3 Med — backtest gate instant + live_selection insert): open_instant = selection_time for BOTH the selection and live_selection branches (post_scan_recheck uses post_recheck_time). live_selection gate goes at L426 (AFTER the L425 force-close, before _open_scan_signals) so a live_selection flat still ARMs (arch §7). No "live_selection instant".
- DP10 (PQR-F4 Med — golden capture ordering): add an explicit P5 PRE-STEP (before P5-1): on master, run the fixed dataset/config, serialize, commit tests/backend/fixtures/cooloff_golden.json. ALL P5 code lands after.
- DP11 (PQR-F5 Med — golden serialization executable): AC-005 compare uses json.dumps(dataclasses.asdict(result), sort_keys=True, default=str) (SimulationResult is a dataclass w/ datetimes), or reuse backtest_service _json_safe. Confirm float-repr stability.
- DP12 (PQR-F6 Med — P5-4 schema files): DROP the SimulationResult/BacktestResultsResponse field edits; bands+skipped live in the EXISTING summary dict (no typed field), populated only when cooloff_enabled (preserves OFF golden). Correct P5-4.
- DP13 (PQR-F7/F9 Med — parity exact value + AC-015): test_cooloff_parity asserts live_net == bt_net (exact, not just sign) + the equal-timestamp SPLIT exercised in BOTH the live _earliest_episode grouping and the backtest cohort (concrete synthetic fixture feeding both).
- DP14 (PFR-F3/F4 Med — frontend types): define CooloffStatus TS interface in client.ts (cooloff_until, cooloff_reason, consecutive_wins/losses, cooloff_remaining_seconds, cooling) per K3; add skipped-by-trigger + bands to types.ts (BacktestMetrics or a results field) and decide MetricsGrid prop (pass results or extend metrics) — pin one source.
- DP15 (PFR-F6/F7 Med — host-page refs + shared validator): cite components/scanner/ScannerPage.tsx (handleStart, button L1057) + components/scanner/ScheduledScansPage.tsx (handleSubmit, button L1464). Add a shared validateCooloff(config) TS helper consumed by CoolOffFields inline error AND both host-page disable gates; runs on the account_id-filtered config set.
- DP16 (PBR-F3/F4/F5/F6/F7 Low — backend polish): apply_classification reason follows chosen until (CASE WHEN new_until>existing THEN new_reason ELSE keep); CooloffRepository holds db and resolves db.pool per call (not a _pool snapshot, match TradeRepository); inline the full v61 DDL + upsert SQL in the task bodies; scanner fallback constructs the classifier too (or document the asymmetry); cite L400-457 for the pre-pass mirror.
- DP17 (PSR-F5 Low — _close_partial note): P3-4 adds a one-line note that _close_partial is intentionally excluded (non-flat -> classifier no-ops; sweep+gate-time backstop).
- DP18 (PPR-F2..F9 Med/Low — traceability + test depth): FR-013 writer-1 (scheduled config-save) — add a task wiring upsert_settings into the scheduled-scan save endpoint (same clobber guard) OR document writer-2-at-execution supersedes (decision: ADD writer-1 to the scheduled-scan PATCH/POST path for save-before-run freshness). Extend §R with ALL 12 NFR rows + tests (NFR-007 UTC/DST, NFR-008 logging, NFR-010/011 a11y/responsive via P6-5 TDD). Add enumerated tests: AC-024 cancelled-only fixture, AC-023 cooloff_active reason render, AC-010 partial+parent sum, AC-016 backtest boundary, AC-020 pre-pass-runs-while-gated, AC-009 cross-surface, FR-023 localStorage hydration guard. Move FR-023 to a P1-4 row in §R.

| R2 | backend+security, qa(backtest), frontend+product | 0 crit; 3 High (DI db._pool, backtest emission scope, FR-013 writer-1 not a real task); ~3 Med/Low | NOT converged — all are corrections to R1 edits. Fixed: DI passes db (not _pool) + classifier fallback; P5-4 emits into result.filter_stats in run(); golden input fixture; TASK-P4-3 promoted real; EquityChart Area-by-flag pinned; FR-013 matrix row. |

| R3 | backend+backtest, frontend | 1 stale db.pool note + 1 recharts render detail (both narrow) | NOT converged — fixed (PR3-F1 note + band render detail). |
| R4 | backend+backtest | "no new findings" | CLEAN (1st). |
| R5 | backend+backtest, frontend | both "Converged: no new findings" | **2nd consecutive clean → Step 7 CONVERGED. PLAN COMPLETE.** |

## Step 7 — COMPLETE (CONVERGED). PART 1 PLANNING DONE.
Plan converged after 5 review rounds. All 70 FR/NFR/AC traced to tasks+tests. No unresolved Critical/High. Ready for Part 2 implementation.

## PART 2 — IMPLEMENTATION

### Step 9-11 (adapted): worktree decision
- DECISION: Implement IN-PLACE (no git worktree) — the EnterWorktree tool is gated to "only when explicitly instructed", planning docs are already in the main working tree, and the strict commit-discipline rule means nothing is committed without explicit user request. Isolation goal met by leaving work UNCOMMITTED until the user reviews at Step 18.
- Step 10 (validate plan vs codebase): DONE via the 5 plan-review rounds (all file/line refs verified against current code).
- Step 11 (impl tracker): this progress-tracker.md serves as the implementation tracker (phase/task status below).

### Implementation Progress
| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| P1 | P1-1 cooloff_core.py | DONE | 30 tests green |
| P1 | P1-2 AutoTradeConfig fields+validator | DONE | golden-sweep deny-list updated |
| P1 | P1-3 BacktestCreateRequest fields+validator | DONE | 16 schema tests green |
| P1 | P1-4 TS type + DEFAULT_CONFIG | DONE | tsc clean |

### Phase 1 — COMPLETE
- cooloff_core.py: 100% coverage, 62 tests (test_cooloff_core 38 + test_cooloff_schema 24). decide() reset-only-fired-side aligned to spec.
- AutoTradeConfig + BacktestCreateRequest: 8 fields + validate_cooloff + extra="forbid" (added to BacktestCreateRequest). golden-sweep KNOWN_DENY updated (cool-off = non-sweepable risk config).
- TS AutoTradeConfig + DEFAULT_CONFIG: 8 fields; tsc clean.
- Per-phase review: 2 agents R1 (correct logic, found test-symmetry + reset-wording + extra=forbid gaps; all fixed), R2 converged.
- Regression: test_backtest_schemas + test_golden_sweep green.

| P2 | P2-1 migration v61 | DONE | applied on live test DB; constraints validated |
| P2 | P2-2 CooloffRepository | DONE | 12 repo tests green vs real Postgres |

### Phase 2 — COMPLETE
- Migration v61 applied on live test DB; CooloffRepository: 19 tests green vs real Postgres.
- Per-phase review (database + qa/security): core money-safety confirmed correct (plain reads, non-blocking try-lock, parameterized SQL, column-scoped settings, max-rearm+clamp). Fixes: clear() now takes advisory lock + own txn (P2R-F1/SR-F10); tz-coerce now; settings.get default False for NOT NULL bools; reason ternary simplified. Tests strengthened +7 (exact cooloff_until clobber assert, non-arming-preserves-active, fresh-account insert path, equal-closed_at id tiebreak, no-row clear=False, status matrix, try_lock concurrency, corruption resets reason).
- Regression: persistence + golden-sweep green. 87 cooloff+regression tests pass.

### Phase 3 — implemented (review pending)
- cooloff_classifier.py (maybe_classify own-txn fail-open + split_earliest_episode pure helper): 15 tests green (arming, win-no-arm, no-settings noop, open-skip, settlement-defer-then-classify, staleness escape, idempotent, two-episode double-failure, fail-open, D45 split).
- cooloff_sweep.py (60s loop, PositionReconciler-modeled).
- trade_service: set_cooloff_classifier + _fire_cooloff (post-commit, never-raises, task-ref held) at 4 close sites (reconcile_close, close_trade_record_only, _close_full, _handle_close_failure genuinely-gone). asyncio imported.
- auto_trade_service: __init__ +cooloff_repo/_classifier (None-guarded); _account_in_cooloff (fail-open gate-time classify + pure-time read); _upsert_cooloff_settings_prepass (un-gated, clobber guard, fail-open) called at top of init_balances; gate wired at init_balances (alongside PAUSE) + post_scan_recheck (mirrors PAUSE block, before reset).
- main.py: build cooloff_repo+classifier+sweep; set_cooloff_classifier; stamp scanner_service; start/shutdown sweep; else-branch None defaults.
- scanner_service: _resolve_cooloff_repo/_classifier (stamped-or-self._db fallback); both executor builds pass deps. scanner.py router build passes from app.state.
- Phase 3 wiring tests: 13 green. Regression: 333 auto_trade/trade_service/close_rule/reconcil/scanner tests green (close path behaviorally unchanged).

### Phase 3 — COMPLETE
- Per-phase review (security + 2x backend): CARDINAL rule confirmed (cool-off never blocks/delays/rolls back a close; entry-only). Classifier logic verified correct (split_earliest_episode D45 split, loop termination, settlement guard, staleness escape, anchor=max_closed_at).
- Fix applied: P3R-F1 — moved _fire_cooloff OUTSIDE the _handle_close_failure try (was safe-only-via-internal-swallow; now structurally cannot fall through to revert-to-open). 
- Info findings documented (P3B-F1 zero-duration boundary invariant — unreachable at real µs timestamps, fail-open).
- 109 cooloff tests + 77 trade_service regression green.

### Phase 4 — COMPLETE
- accounts.py: GET /accounts/{id}/cooloff (200 defaults no-row, 404 unknown, 400 invalid, 503 off) + POST /accounts/{id}/cooloff/clear (reset_streak flag, idempotent, audited w/ actor+before/after). 9 API tests.
- scan_scheduler_service: _persist_cooloff_settings writer-1 in create()+update() (clobber guard, column-scoped, fail-open + hardened non-list guard + wrapped call sites). 6 tests.
- MCP: cool-off fields pass strip_secret_keys automatically (denylist) — no code needed; 1 lock-in test.
- Per-phase review (backend/security): endpoints correct; fixes P4R-F1 (harden non-list + wrap call sites) + P4R-F2 (audit actor+after-state). clear is NOT a money-path mutation (DB-only, advisory-locked).
- Regression: 50 accounts-router + 50 scheduler tests green.

### Phase 5 — COMPLETE
- backtest_engine: SimulationState cool-off fields (all inert when OFF); run() builds cooloff_enabled + self._cooloff_settings once; 3 gate sites (_cooloff_blocks at live_selection/post_recheck/normal, correct per-branch open_instant, after force-close); _close_position ARM hook (_cooloff_arm_on_flat, funding-excluded net=pnl+funding_paid, anchored exit_time, max-rearm, advance-on-every-flat, backtest_end excluded); filter_stats emits cooloff_* keys ONLY when enabled; _cooloff_finalize_bands (clamp+merge+sort).
- Per-phase review (qa/parity): NO behavioral defects across all 6 areas (OFF byte-identical, ARM, gate, determinism, bands, parity). Fixes: P5R-F3 band reason follows authoritative pair; P5R-F1/F2 test gaps closed (neutral-no-inflation, backtest_end-no-arm; equal-ts split covered live-side).
- 11 cool-off backtest tests + 374 pre-existing backtest tests green (golden byte-identical). Enforcement VERIFIED: OFF=2 trades, failure-cooloff-ON=1 trade (2nd scan skipped, band emitted).

### Phase 6 — implemented (review pending)
- client.ts: AutoTradeConfig +8 cool-off fields; CooloffStatus interface; accountsApi.getCooloffStatus + clearCooloff.
- CoolOffFields.tsx: 4 tiers grouped Single-trade / Win-loss-streak; NeuSwitch + Input + Min/Hr sticky-unit selector; toMinutes/fromMinutes (round, clamp ≤43200); enable applies default, preserves existing on re-enable; inline error.
- cooloffValidation.ts: validateCooloff + cooloffConfigsValid (mirrors backend validate_cooloff: enabled tier ⇒ 1..43200). Wired as Launch (ScannerPage, alert) + Save (ScheduledScansPage, toast) disable gates.
- CoolOffBadge.tsx: live "Cooling off" badge; useQuery poll (15s cooling / 45s baseline / off when no tier); client countdown; Resume-now mutation w/ confirm + invalidations; mounted in AutoTradeSection only when account_id present.
- Backtest UI: configSchema.ts + types.ts +8 fields (CheckField+NumberField pairs); BacktestResultsPage extractCooloff(summary) → skipped stat + by-reason chips + band legend; EquityCurveChart cooloffBands prop → computeCooloffMembership (categorical-axis per-row flag, DP5) → full-height warning-shaded Area behind equity line (OFF parity: no key ⇒ pre-feature render).
- NeuSwitch: added optional ariaLabel prop (forwarded to button) — fixes a11y gap (switch had no accessible name); 16 existing usages unaffected.
- Tests: cooloffValidation (10), CoolOffFields (8), CoolOffBadge (6), EquityCurveChart band+membership (+9 → 28), BacktestResultsPage cool-off (+2 → 24). Full FE suite: 906 pass / 84 files; tsc clean.

### Phase 6 review — Round 1 (5 agents: frontend, correctness, races, typescript, testing)
Findings fixed (all valid Crit/High/Med + cheap a11y Lows):
- **CRITICAL** F1: backtest Zod schema had no enabled→minutes refine → enabled-but-blank tier could submit (backend would reject). Added 4 cross-field refines + wired cool-off minutes into advancedHasError (section auto-opens on invalid submit).
- **HIGH** (correctness): Hr-mode decimal typing silently corrupted value (controlled input rewrote mid-keystroke). Fixed with per-tier raw-draft state; reformat only on blur/unit-switch.
- **HIGH** (testing): OFF-parity render invariant was tautological. Extracted pure buildCooloffChartData (returns input BY REFERENCE when no band) + referential-identity test.
- **HIGH** (testing): no host-page gate tests. Extracted cooloffGateValid + collectCooloffGateErrors shared seam (account_id filter), wired both pages to it, added gate tests.
- **MED** (3 agents): badge interval-storm — re-invalidate every 1s when server returns constant remaining. Rewrote countdown as pure cooloff_until-deadline minus ticking nowMs (no setState-in-effect, no busy-loop, ref-guarded single zero invalidate). lint-clean (purity/refs/set-state rules).
- **MED**: badge polled only when tiersEnabled → an actively-cooling account vanished if user toggled tiers off in draft. Now polls on accountId (120s baseline).
- **MED**: badge no optimistic clear → phantom countdown after Resume-now. Added onMutate optimistic cooling:false.
- **MED/LOW**: inline error/aria-invalid omitted >MAX bound (validateCooloff rejects it). Unified via tierMinutesValid; Hr-mode clamp; aria-describedby; flex-wrap; double-confirm guard.
- **MED** (TS): unsafe casts + DRY. Created cooloffTiers.ts single-source descriptor (narrowed template-literal key types remove casts + prevent mispaired-key bug); CooloffReason exported from client.ts, reused in typed label maps.
- **LOW**: results empty-strip when tier on but nothing skipped → added hasContent gate; legend swatch opacity aligned to band fill.
- a11y: live-region no longer re-announces per-second countdown (sr-only stable label + aria-hidden ticker); NeuSwitch gained ariaLabel (fixed switch-with-no-accessible-name).
- New tests: cooloffResults (extractCooloff branches), buildCooloffChartData OFF-parity, badge fake-timer countdown+zero-invalidate, gate helpers, all-4-tier defaults, Hr-clamp, configSchema refines. FE suite 939 pass / 85 files; tsc + eslint clean (1 pre-existing unrelated _current warning untouched).

### Phase 6 review — Round 2 (5 agents: correctness, races, frontend, maintainability, testing)
Races agent: CONVERGED (R1 storm + optimistic-clear fixes confirmed, no new Med+). Others found NEW regressions from R1 rewrites → fixed:
- **MED** (2 agents): configSchema.ts hardcoded 1/43200 instead of shared consts → drift. Now imports COOLOFF_MIN/MAX_MINUTES from cooloffTiers.
- **MED** (correctness): badge stale nowMs on not-cooling→cooling could overstate countdown ≤1s. Clamped deadline-derived remaining to server cooloff_remaining_seconds upper bound (+NaN guard).
- **MED** (frontend): toMinutes silently clamped over-max → the >MAX inline error was unreachable while typing (silent intent change). Removed clamp; value stored as-typed, flagged invalid + gate-blocked.
- **MED** (frontend, new edge): legend swatch rendered on bands.length>0 but chart shades on actual membership → legend could claim shading not drawn. Gated legend on computeCooloffMembership(...).some(); swatch opacity aligned to 0.14 band fill.
- **MED** (a11y, 2 rounds): Min/Hr role=radio lacked keyboard contract. Switched to role=group + aria-pressed toggle buttons (Tab+Enter/Space satisfies contract, no roving tabindex needed).
- **MED** (testing): badge "none after" assertion near-tautological. Added re-arm test (deadline pushed back after zero) that exercises zeroFiredRef reset + a 2nd invalidate — makes the guard load-bearing.
- **MED** (testing): raw-draft mechanism untested. Added decimal-draft-survives-then-reconciles-on-blur test.
- **LOW**: clear draft on tier enable/disable; extractCooloff by-reason-only branch test; configSchema below-min test; aria-pressed assertion test.
- Pre-existing _current unused-var in configSchema (unrelated to cool-off) left untouched (scope discipline).
- FE suite 945 pass / 85 files; tsc + my-files eslint clean.

### Phase 6 review — Round 3 (5 agents: correctness, frontend, testing, maintainability)
Frontend/a11y: CONVERGED (all R2 fixes verified; 1 LOW optional role=alert). Maintainability: CONVERGED (import direction fine, no dead code; 1 LOW hint-string centralization optional). Correctness + testing found NEW Mediums → fixed:
- **MED** (correctness, NEW from R2 no-clamp): enable tier→type over-max→disable preserved the over-max value; validateCooloff skipped disabled tiers but the backend Field(None, ge=1, le=43200) rejects out-of-range UNCONDITIONALLY → 422 on a hidden field. Two-part fix: (a) NeuSwitch onChange nulls an out-of-range value on disable (keeps in-range for re-enable); (b) validateCooloff now ALSO flags a non-null out-of-range value on a DISABLED tier (matches backend field constraint, covers localStorage/imported configs). Backtest Zod path already rejected it.
- **MED** (testing, NEW): legend-gating on cooloffBandsVisible was untested. Added both branches: existing test now asserts legend ABSENT when band doesn't overlap a sample; new test asserts legend PRESENT when a sample falls in-band.
- Tests added: disabled-tier out-of-range flagged + in-range-kept (validateCooloff); disable-nulls-over-max (CoolOffFields); legend present/absent (BacktestResultsPage).
- LOW deferred (optional polish, non-blocking): inline-error role=alert; hint-string constant centralization; anyCooloffMembership early-exit. All AA-met / cosmetic.
- FE suite 949 pass / 85 files; tsc + eslint clean.

### Phase 6 review — Round 4 (2 active lenses: correctness, testing)
Correctness: CONVERGED — verified validateCooloff matches the backend across ALL 6 (enabled × {null,in-range,out-of-range}) states exactly; disable-null + atomic patch + re-enable-default all correct. No new Med+.
Testing: found one MED — the disable-KEEP-in-range branch (other arm of the disable ternary) was untested. Added the complement test (disable keeps 60). Pure test addition, no source change. Fixed stale fixture comment.
- LOW deferred: scanner tierMinutesValid lacks .int() (corrupt-localStorage-only non-integer; backtest Zod already guards) — pre-existing, out of scope.
- FE suite 950 pass / 85 files.

### Phase 6 review — Round 5 (testing + holistic correctness)
Testing: CONVERGED — disable-ternary both arms covered, R4 complement test sound, no Med+ gaps; page-wiring-absence re-confirmed acceptable (helper-tested seam).
Holistic correctness: found one NEW MED — badge guard `if (isError || !data?.cooling)` hid an actively-cooling badge on a WARM refetch error (TanStack v5 keeps last-good data but flips isError; global retry:1). Violated never-hide-active-pause invariant. Fixed: dropped isError from the guard (cold error still fail-opens via undefined data; warm error retains the cooling badge, countdown anchored to absolute cooloff_until). Added warm-error regression test (cooling badge persists through a failing refetch).
- LOW deferred (non-blocking): optimistic resume lacks cancelQueries (self-corrects via onSettled); membership computed in both page+chart (perf nit, output stable); tierMinutesValid .int() gap (UI-unreachable).
- FE suite 951 pass / 85 files; tsc + eslint clean.

### Phase 6 review — Round 6 (correctness holistic + races) — CONVERGED
Both lenses: ZERO new findings. Correctness verified the isError-drop is correct+complete (cold fail-opens, warm retains, permanent-error degrades fail-SAFE to stuck-0m-with-Resume rather than silent-hide — judged strictly better for a money app, no invalidate storm). Races verified the edit is race-neutral (hooks always ran above the guard; only JSX output changed; no storm, optimistic-resume persists through failed refetch).

### PHASE 6 — COMPLETE (CONVERGED)
Review converged: R5 (testing) + R6 (correctness+races) = 2 consecutive clean rounds on the active lenses; frontend/a11y converged R3, maintainability converged R3, correctness converged R4. Total 6 review rounds, 30 agent-reviews. All Critical/High/Medium findings fixed; documented LOW items deferred as non-blocking optional polish. FE suite 951 pass / 85 files; tsc + eslint clean (1 pre-existing unrelated _current warning untouched).

## Step 13-14 — Cross-phase + final review

### Cross-phase Round 1 (5 agents: parity, integration, adversarial-money, requirements, migration)
HOLDING invariants confirmed with evidence: funding-excluded win/loss live↔backtest parity; shared cooloff_core (no reimpl); OFF byte-identical; "close can never be rolled back/blocked by cool-off" (adversarial agent cited every defense — advisory-lock idempotency, post-commit fire-and-forget, fail-open gate, corruption clamp). Requirements: ALL 8 user requirements MET, no scope creep.
Findings fixed:
- **HIGH** (integration): all-OFF clobber guard made DISABLE a no-op — a tier couldn't be turned off once enabled (contradicts user "optional/default-off"). Fixed: scheduled-save writer now persists all-OFF (explicit durable disable, column-scoped so active pause still runs to expiry); manual prepass KEEPS its guard (documented — an all-OFF transient manual scan must not wipe a scheduled account's policy = fail-safe). Disable path = scheduled save; active pause = Resume-now.
- **MED** (migration): v61 account FK was NO ACTION → blocked account deletion. Added migration v62 (callable, not DO$$ — runner splits on ';') making the FK ON DELETE CASCADE. +DB cascade test.
- **MED** (deploy): COOLOFF_SWEEP_INTERVAL_S int() could crash startup on a bad value → _parse_interval guard (default + floor-1). +9 parse tests.
- **MED** (deploy): main.py cool-off wiring not exception-isolated → wrapped in try/except (logs + None defaults; can't abort startup or take down position_reconciler).
- **MED** (parity): equal-timestamp episode boundary — VERIFIED structurally equivalent (backtest closes-before-opens by loop construction = live close-before-open split); added a lock-test (two same-instant episodes → double_failure, not one merged cohort).
- Migration contiguity test was pre-existing-stale (asserted head=58 while tree had 59-61); updated to head=62.
- Rollback CRITICAL/HIGH (version-guard + extra=forbid): inherent to the migration framework (every added field), NOT cool-off bugs → runbook items (revert keeps new code OR manual schema_version downgrade + extra=ignore build). Documented, not code-fixed.
- LOW deferred: clear-endpoint per-route auth (app-wide model); anchor-at-close vs delayed-settlement pacing gap (live, STALE_MIN-bounded); gate-time classify race (one extra entry, self-heals).
- Backend cool-off suite: 147 pass. Full backend (scheduler/auto_trade/backtest/migration slice): 486 pass + migration test fixed.

### Cross-phase Round 2 — CONVERGED
3 agents (disable-path/backend, migration/deploy, testing/qa) ALL declared convergence. No new Critical/High.
- Disable fix VERIFIED correct+complete on the scheduled surface (column-scoped upsert preserves active pause; all-OFF persists = working disable). Residual MED: manual-ONLY users disable via scheduled save not manual surface (fail-SAFE, pre-existing guard deliberately retained, working durable workaround) — judged non-blocking, logged as follow-up.
- Migration v62 VERIFIED safe (idempotent via schema_version guard + re-runnable function; atomic txn; conname catalog-safe; lock_timeout 30s mitigates; tiny tables). _parse_interval crash-proof. main.py wiring isolation correct (logger in scope, position_reconciler unaffected).
- Tests VERIFIED sound (two-episode parity rules out the merged bug; FK cascade genuinely exercises v62; _parse_interval full branch coverage).
- LOW doc fixes applied: sweep docstring (floors→default), test comment (-18). LOW deferred: main.py partial-wiring app.state cosmetic; manual-only disable follow-up.
- CROSS-PHASE CONVERGED: R1 (findings+fixes) → R2 (3/3 converged) = clean. Final review complete.

### Step 15-17 — Final validation + traceability
- Backend: full cool-off suite 147 pass; broad `-k cooloff|backtest|scheduled|migration` slice 535 pass / 3 skip (1 transient pool-exhaustion ERROR in the mega-run, PASSES in isolation + as a file — test-infra artifact, not a logic defect). Migration v62 applies clean on the test DB.
- Frontend: tsc --noEmit clean; **production build (tsc -b + vite) SUCCEEDS** — the build's stricter project-ref tsc caught a generic-return type issue in buildCooloffChartData (T[] vs (T&{cooloffBand?})[]) that --noEmit missed; fixed with an OFF-parity-preserving cast. Full vitest 951 pass / 85 files.
- Traceability (product reviewer cross-phase R1 table): all 8 user requirements MET with code+test evidence — 4 tiers, account-specific, optional/default-OFF, BOTH manual+scheduled surfaces, hr/min, live+backtest, real pause enforcement; plus double-overrides-single (D2), net-realized-P&L-at-flat outcome (D15), Resume-now (D12), backtest bands+skipped-stat (D14). No scope creep. No requirement lacks a test.

### STATUS: ALL STEPS COMPLETE — feature ready, work UNCOMMITTED (in-place per worktree decision).
Awaiting user decision: commit / PR / keep uncommitted.
