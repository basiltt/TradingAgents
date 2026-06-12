# Requirements: Cool Off Time

**Feature:** Account-specific cool-off pause for auto-trading.
**Status:** Step 2 (Requirements) — consolidated from 2 brainstorm rounds + model resolution.
**Date:** 2026-06-11

## Feature Description

Add an optional, account-specific "Cool Off Time" capability to the auto-trade system.
After an account's auto-trade **cycle** completes, trading for that account can be paused
for a configurable duration based on the cycle's outcome. Four independent, optional
settings (all default OFF):

1. **Success cool off** — pause after a winning cycle.
2. **Failure cool off** — pause after a losing cycle.
3. **Double-success cool off** — pause after 2 consecutive winning cycles.
4. **Double-failure cool off** — pause after 2 consecutive losing cycles.

Each setting has a duration entered as a number + Minutes/Hours unit selector (stored
canonically as minutes). Configurable per-account from BOTH the manual Market Scan
auto-trade settings AND the Scheduled Market Scan auto-trade settings (the shared
`AutoTradeSection`). Must be implemented in BOTH live trading and backtesting. Handles
real money — correctness and safety are paramount.

## Resolved Model (locked decisions — see progress-tracker Decided Log)

- **D15 — Outcome = net realized P&L at flat.** A cycle = the auto-trade trades
  (`source IN ('scanner','cycle')`, NOT manual) one scan opens for an account. The cycle
  **completes** when the account returns to zero open auto-trade positions ("went flat").
  Outcome = sign of the summed `net_pnl` of that cycle's trades: `>0` success, `<0`
  failure, `==0` neutral (no cool-off, no streak change). Universal `is_win = net_pnl>0`.
  Fires on EVERY completed cycle regardless of how positions closed (TP/SL/equity-rule/
  duration/manual-close-of-auto-position).
- **D2/D9 — Double overrides single.** When both a single and its double tier qualify on
  the same cycle end, arm only the double duration (not summed, not longest).
- **D3 — Whole-account scope.** An active cool-off blocks ALL auto-trading for that
  account (every schedule + manual scan). It does NOT block the user's own manual trades.
- **D5/D9 — Streak semantics.** Streak counts only classified (non-neutral) cycle
  outcomes. A neutral cycle (net==0) is transparent (no advance, no reset). An opposite
  outcome resets the other side to 1. After a double tier fires, that side resets to 0.
  Re-arm while active = `max(existing, new)` (never shorten).
- **D11 — Fail policy.** The cool-off gate fails OPEN (allow trading) on unparseable/
  transient state errors — deliberately opposite to the existing PAUSE_TRADING gate
  (which fails closed) because cool-off is risk-reduction pacing, not a safety halt;
  fail-closed-on-garbage risks unbounded silent lockout. Read-side clamp resets corrupt
  values.
- **D4 — UI.** Number field + Min/Hr unit selector per setting; stored as minutes.
- **D12 — Manual override.** v1 includes a "Resume now / clear cool-off" control + audited
  backend endpoint. Clearing ends the active pause but does NOT reset streak counters.
- **D13 — Disable semantics.** Disabling a trigger affects FUTURE cool-offs only; an
  already-active pause runs to expiry (early end only via the Resume-now control).
- **D14 — Backtest reporting.** Backtest enforces cool-off in sim time + reports a
  "signals skipped by cool-off" stat (by trigger) + shaded equity-curve bands.

## Total Requirements Count: (see sections)
## Rounds Completed: 2 (+ model resolution) → round 3 gap-check pending

---

## Core Semantics [CORE]

- CO-CORE-1: Four independent cool-off triggers per account: success, failure, double_success, double_failure. Each has an `enabled` flag (default false) and a duration in minutes.
- CO-CORE-2: A cycle's outcome is the sign of the summed net_pnl of its auto-trade trades, evaluated when the account goes flat (zero open auto-trade positions). >0=success, <0=failure, ==0=neutral.
- CO-CORE-3: Only trades with source IN ('scanner','cycle') count toward a cycle; manual trades (source='manual') are excluded from cycle outcome and never trigger cool-off.
- CO-CORE-4: On a classified cycle completion, evaluate triggers in this order: if failure and consecutive_losses>=2 and double_failure enabled -> arm double_failure; elif failure and failure enabled -> arm failure. Symmetric for wins. At most one cool-off armed per cycle (success/failure are mutually exclusive for one cycle).
- CO-CORE-5: Arming sets cooloff_until = cycle_completion_time + duration_minutes, and records cooloff_reason (enum: success|failure|double_success|double_failure).
- CO-CORE-6: Double overrides single: when both a single tier and its double tier are enabled and a 2nd consecutive same-outcome occurs, arm only the double duration.
- CO-CORE-7: An active cool-off blocks ALL new auto-trade entries for the account (all schedules + manual scans), layered on top of (not replacing) the existing "no new cycle while one running" and skip_if_positions_open gates.
- CO-CORE-8: Cool-off NEVER opens or closes a position itself. It only gates NEW entries. Open positions, their close rules (TP/SL/drawdown/trailing/breakeven/max-duration), the cycle engine, and reconciliation continue untouched while a cool-off is active.
- CO-CORE-9: Cool-off is independent of and additive to the existing AI PAUSE_TRADING gate. Either active => auto-trade blocked. Clearing/expiring one never affects the other.
- CO-CORE-10: Cool-off is per-account isolated: one account's cool-off never affects another account.
- CO-CORE-11: Manual (user-initiated) trades are never blocked by an auto-trade cool-off — the user always retains control of their own capital.

## Streak State Machine [STREAK]

- CO-STREAK-1: Maintain consecutive_wins and consecutive_losses per account (persisted, survive restart).
- CO-STREAK-2: On success outcome: consecutive_wins += 1; consecutive_losses = 0. On failure: consecutive_losses += 1; consecutive_wins = 0.
- CO-STREAK-3: Neutral outcome (net_pnl == 0) leaves both counters UNCHANGED (transparent) and arms nothing.
- CO-STREAK-4: A cycle with no qualifying trades (zero auto-trade trades opened/closed) is NOT a cycle completion — no outcome, no streak change.
- CO-STREAK-5: After a double tier fires, reset that side's counter to 0 (a fresh pair of consecutive outcomes is required before it can fire again).
- CO-STREAK-6: First-ever cycle for an account: uninitialized counters default to 0; the first classified outcome sets the relevant counter to 1; can never produce a false double-fire.
- CO-STREAK-7: Streak counters are maintained even when all cool-off tiers are OFF, but have zero observable effect when OFF (preserves predictable behavior when a tier is enabled mid-streak). Clamp stored counters at a small max (e.g., 2) to bound state.
- CO-STREAK-8: Toggling which tiers are enabled, or editing a duration, never corrupts or resets streak counters.
- CO-STREAK-9: Streak is account-scoped and SHARED across scheduled + manual scans and across strategy cohorts (trend/MR) for the same account. Documented as intended (a trend loss + an MR loss = account-wide double-failure).
- CO-STREAK-10: "Double" threshold is hard-coded at 2 consecutive (not configurable in v1); documented.

## Configuration & Schema [CONFIG]

- CO-CFG-1: Add 8 flat fields to AutoTradeConfig (backend/schemas/__init__.py, extra="forbid"): cooloff_on_success_enabled (bool=False), cooloff_on_success_minutes (Optional[int]); same for _failure, _double_success, _double_failure.
- CO-CFG-2: Mirror the identical 8 fields in BacktestCreateRequest (backend/schemas/backtest_schemas.py) and in the TS AutoTradeConfig interface (frontend/src/api/client.ts) + DEFAULT_CONFIG.
- CO-CFG-3: Duration bounds: minutes Optional[int] = Field(None, ge=1, le=43200) (1 minute to 30 days). Reject 0, negative, non-integer, NaN/Inf.
- CO-CFG-4: model_validator: if a *_enabled flag is True, its *_minutes is required and >= 1; reject otherwise (mirror style of validate_target_goal). No cross-field ordering constraint between single/double durations.
- CO-CFG-5: Absent fields in stored scan_config JSON blobs (legacy scheduled scans) deserialize to all-OFF via Pydantic defaults — fully backward compatible.
- CO-CFG-6: Unit selection (Min/Hr) is a UI concern; the API/DB store minutes only. Hours->minutes conversion uses Math.round(value*60) and is bounds-checked on the converted minutes.
- CO-CFG-7: The same 8 fields are accepted on the manual-scan auto-trade path (POST /scanner/{scan_id}/auto-trade) and the scheduled-scan path; verify round-trip persistence in both.

## Live Backend [LIVE]

- CO-LIVE-1: Add a persisted per-account cool-off state store (new table account_cooloff_state) with: account_id PK, cooloff_until timestamptz NULL, cooloff_reason text NULL (CHECK enum), consecutive_wins int default 0, consecutive_losses int default 0, last_processed_cycle_key text NULL (idempotency), updated_at timestamptz.
- CO-LIVE-2: Add a live gate method (sibling to AutoTradeExecutor._is_account_paused) e.g. _account_in_cooloff(account_id) -> bool, called at the SAME two sites: init_balances (~L483) and post_scan_recheck (~L1006), setting state.stopped=True, state.stopped_reason="cooloff_active".
- CO-LIVE-3: The cool-off gate must run BEFORE the post_scan_recheck state-reset block (~L1022) so cooloff_active is not clobbered; mirror the PAUSE pattern (L1007-1012) exactly with a `continue`.
- CO-LIVE-4: Lazy expiry: when the gate reads cooloff_until <= now (UTC), treat as inactive and clear (NULL) the cooloff_until/reason (mirror the expired-pause-rule delete at auto_trade_service.py:377).
- CO-LIVE-5: Outcome detection: detect when an account transitions to zero open auto-trade positions, sum the completed cycle's net_pnl, classify, update streak + arm cool-off — atomically and idempotently, across ALL close paths (trade_service._close_full, reconcile_close). Exact chokepoint design = Architecture (Step 3).
- CO-LIVE-6: Outcome classification + streak update + arming MUST be a single atomic DB transaction (asyncpg), keyed on account_id. No partial application (paused but streak not advanced, or vice-versa).
- CO-LIVE-7: Idempotency: a cycle's outcome is processed exactly once even under retries / reconciler re-runs / the recover_stuck_triggered_rules path. Use a stable cycle key (last_processed_cycle_key) checked+written in the same transaction.
- CO-LIVE-8: Re-arm while a cool-off is already active sets cooloff_until = max(existing, new); never shortens an active pause.
- CO-LIVE-9: Forced/non-trading cycle terminations (server_restart, user_stopped, server_shutdown) produce NO outcome and never touch streak or arm cool-off.
- CO-LIVE-10: Clock source = datetime.now(timezone.utc), consistent with _is_account_paused. Store cooloff_until as tz-aware UTC (timestamptz). DST has no effect.
- CO-LIVE-11: Concurrency: two cycles completing near-simultaneously for the same account must update the streak atomically (single UPDATE ... RETURNING or per-account advisory lock); no lost update.

## Cycle Completion / Outcome Detection [DETECT] (design constraints for Architecture)

- CO-DET-1: "Account went flat" = the count of open auto-trade positions/trades for the account (status IN open/partially_filled/closing/partially_closed, source IN scanner/cycle) transitions from >0 to 0.
- CO-DET-2: A cycle's net_pnl = SUM(net_pnl) of the trades belonging to that cycle. Must define the cycle grouping key (candidate: trades opened since the last flat point; or grouped by scan/source_id). Architecture must pin this precisely.
- CO-DET-3: Detection must be robust to partial closes (a position closing in parts must not be judged flat until all parts close) and to the reconciler closing trades asynchronously.
- CO-DET-4: Detection must NOT misfire on manual-only flatness (closing a manual position when no auto cycle was running) — only auto-trade cycles count.
- CO-DET-5: If positions are still open, do not classify (cycle not complete) — no premature arming.
- CO-DET-6: Two equity/close events in one reconcile/evaluate pass for one account must yield exactly one cycle outcome (the flat transition), not double-count.
- CO-DET-7: net_pnl summation reads the authoritative persisted net_pnl on closed trades (already fees+funding net). Null/NaN net_pnl on any contributing trade => treat that contribution as 0 and log; never classify on corrupt data in a way that fabricates a win/loss (if total is indeterminate, prefer neutral + WARNING).

## Backtest [BACKTEST]

- CO-BT-1: BacktestEngine enforces cool-off in simulated time: when current scan's effective entry time < cooloff_until, skip opening new entries for that scan (mirror skip_if_positions_open gate), while still evaluating/closing open positions.
- CO-BT-2: Backtest classifies a cycle when the scan's opened cohort fully closes in sim; outcome = sign of summed recorded pnl of that cohort. Same streak state machine + double-overrides-single + max-re-arm as live, in SimulationState (cooloff_until, consecutive_wins/losses, last arm key).
- CO-BT-3: A cool-off-skipped scan opens nothing, is NOT a cycle, and never advances the streak.
- CO-BT-4: Shared, pure classifier + streak/arm logic across live and backtest, taking now (UTC vs sim time) and a state store as injected dependencies — one algorithm, two backends.
- CO-BT-5: NO-REGRESSION INVARIANT: a backtest with all 4 cool-off tiers OFF must be byte-identical to current output (same trades, equity_curve, metrics, filter_stats keys). New cool-off stat/band fields are emitted ONLY when at least one tier is enabled.
- CO-BT-6: Determinism: cool-off logic uses no wall-clock and no RNG; identical config+data => identical cool-off behavior and identical skipped-signal set across repeated runs.
- CO-BT-7: The cool-off gate comparator uses the SAME instant entries would open at for that scan branch (selection_time / post_recheck_time), not a single current_time, to preserve parity across recheck/live-selection branches.
- CO-BT-8: Count "signals skipped by cool-off" in a NEW counter (not signals_filtered), broken down by triggering reason; surface in SimulationResult.filter_stats and metrics (only when feature ON).
- CO-BT-9: Cool-off gate runs BEFORE the skip_if_positions_open counter so each skipped scan's signals land in exactly one bucket.
- CO-BT-10: Emit cool-off band data: list of {start, end, reason} (start=cycle completion/arm time, end=cooloff_until), clamped to [report_start, report/backtest end]; merge overlapping bands (from max re-arm); sorted; added to SimulationResult dataclass AND BacktestResultsResponse AND result persistence.
- CO-BT-11: A cool-off armed at/after the last signal has no later scan to block (no-op) but its band is still clamped and reported.
- CO-BT-12: Backtest cool-off state is fresh per run (no leak across runs); parallel runs share no mutable cool-off state; backtest NEVER reads or writes the live account_cooloff_state table.
- CO-BT-13: Durations shorter than the simulation_interval may block zero scans — intended no-op, documented; no rounding of stored minutes to the interval.

## Frontend [FE]

- CO-FE-1: New CoolOffFields.tsx component (mirroring RegimeStrategyFields.tsx) mounted inside the shared AutoTradeSection.tsx per-account card -> appears on BOTH ScannerPage (manual) and ScheduledScansPage (scheduled) automatically.
- CO-FE-2: Grouped neumorphic inset sub-section "Cool Off Time" with two groups: "Single trade" (Success, Failure) and "Win/Loss streak" (Double-success = 2 wins in a row, Double-failure = 2 losses in a row).
- CO-FE-3: Each setting = NeuSwitch toggle + (when ON) numeric Input + Min/Hr segmented unit selector. Reuse the L711-810 toggle+input pattern and clampNumberOrNull. Collapsed/hidden inputs when OFF.
- CO-FE-4: Sensible defaults applied when a toggle flips ON (e.g., success 30m, failure 60m, double-success 60m, double-failure 120m); immediately editable. Toggling OFF preserves the last value in local state.
- CO-FE-5: Storage is minutes; Hr display converts via Math.round(value*60) on store and divide on render. Decide and implement unit display inference (e.g., show Hr when minutes is an exact multiple of 60 and >=60). Allow 1 decimal place for hours.
- CO-FE-6: 8 new fields on the TS AutoTradeConfig interface + DEFAULT_CONFIG (all OFF/null). localStorage hydration guards missing keys to OFF.
- CO-FE-7: Validation: enabled tier requires duration in [1, 43200] minutes (unit-aware bounds in UI); inline neumorphic error; block Save/Launch on the host page if any enabled tier has invalid/blank duration; identify the offending account+tier.
- CO-FE-8: Live "Cooling off" badge on the account card (and account selector on ScannerPage, per-account row on ScheduledScansPage) showing reason + live countdown + absolute resume time tooltip. Distinct styling from an AI PAUSE badge.
- CO-FE-9: Badge data comes from a per-account live status source. Add accountsApi.getCooloffStatus(id) -> { cooloff_until, cooloff_reason, consecutive_wins, consecutive_losses } (mirror getAiManagerStatus), OR extend the accounts dashboard payload. The live badge + Resume-now must be a separate component rendered by AutoTradeSection ONLY when config.account_id is present (NOT inside CoolOffFields, which the backtest form reuses).
- CO-FE-10: "Resume now / clear cool-off" button on the badge -> useMutation calling the clear endpoint, confirm dialog, server-confirmed (not optimistic); on success invalidate the cooloff-status query + ["accounts"] + dashboard query.
- CO-FE-11: Countdown derived client-side from server cooloff_until (one ticking clock source for many accounts, not N intervals); on reaching 0, refetch/invalidate cooloff-status to flip badge to active. Poll cooloff-status (~15-30s) only while at least one account is cooling off.
- CO-FE-12: ScannerPage handleStart (~L497-526) pre-launch check: if a selected account is cooling off, warn/confirm before firing startMutation (manual scan only; scheduled persists config, no immediate launch).
- CO-FE-13: Backtest config form reuses CoolOffFields. Backtest results: add a "Signals skipped (cool-off): N" stat (by trigger) to MetricsGrid, and shaded ReferenceArea bands on EquityCurveChart (new cooloffBands prop), with a legend entry and a show/hide toggle (default ON). Band data sourced from run.results.
- CO-FE-14: A11y: switch roles/aria-checked; Min/Hr as keyboard radiogroup with aria-label; inputs aria-describedby validation; countdown badge aria-live=polite throttled to ~1/min; respect prefers-reduced-motion; reason+time as text not color-only.
- CO-FE-15: Responsive: rows reflow (input+unit stack below toggle) on narrow widths; touch targets >=44px; badge truncates to icon+time with full text in tooltip. Full dark/light parity.

## API [API]

- CO-API-1: GET account cool-off status (new endpoint or extension): returns cooloff_until (UTC ISO), cooloff_reason, consecutive_wins, consecutive_losses, server-computed cooloff_remaining_seconds. Behind existing per-account authz.
- CO-API-2: POST /accounts/{account_id}/cooloff/clear -> nulls cooloff_until/reason; does NOT reset streak (unless explicit ?reset_streak=true). Audited (actor + timestamp). Idempotent (clearing twice == once).
- CO-API-3: Expose the 8 cool-off fields in the MCP accounts/config payloads as needed; timestamps/counters need no money-redaction.
- CO-API-4: The API echoes computed cooloff_until on arming responses/logs so users can sanity-check minutes-vs-hours.
- CO-API-5: All new request fields validated by Pydantic; extra="forbid" catches misspelled keys.

## Observability & Audit [OBS]

- CO-OBS-1: Structured logs (extra={...} style) at each transition: cooloff_armed (account_id, reason, duration_minutes, cooloff_until, cycle_key, net_pnl, streak), cooloff_blocked_scan (account_id, cooloff_until, scan_id), cooloff_expired, cooloff_cleared (actor).
- CO-OBS-2: Log the classification of every completed cycle including neutral (cooloff_outcome=neutral/success/failure, net_pnl, streak after) for audit of why a streak advanced or not.
- CO-OBS-3: Distinct log levels: WARNING for transient fail-open, ERROR for corrupt-value reset.
- CO-OBS-4: When the gate blocks a scan, emit a lifecycle event (reuse _emit_life marked_stopped with reason="cooloff_active") so the UI explains the no-trade outcome; set stopped_reason="cooloff_active" (distinct from "ai_paused_trading").
- CO-OBS-5: Optional metrics counters: cool-offs armed by trigger, scans skipped, fail-opens, corruption resets.

## Migration & Compatibility [MIGRATION]

- CO-MIG-1: Add migration v61 (next in _MIGRATIONS, currently v60): CREATE TABLE IF NOT EXISTS account_cooloff_state (...) + index; additive, idempotent, matches v60 style.
- CO-MIG-2: No historical backfill: all accounts start streak 0 / no cool-off. Avoids a surprise immediate pause on first post-upgrade cycle.
- CO-MIG-3: Backward compatible: previous app version (post-rollback) ignores the new config fields and the new table; old configs deserialize to feature-OFF.
- CO-MIG-4: account_cooloff_state.account_id is PK/unique (one row per account) — prevents split-brain streak counting; indexed for O(1) gate lookup on the hot path.

## Edge Cases and Failure Modes [EDGE]

- CO-EDGE-1: Unparseable cooloff_until at gate read => fail-OPEN (allow), log ERROR, reset the bad value. (Opposite to PAUSE fail-closed; documented.)
- CO-EDGE-2: Transient DB error reading cool-off state => fail-OPEN (allow), log WARNING; other risk controls (TP/SL/leverage/max-trades/PAUSE) remain in force.
- CO-EDGE-3: Read-side clamp: cooloff_until > now + MAX (e.g., 30d) => treat as corrupt, fail-open, ERROR, reset (defense-in-depth vs a unit bug).
- CO-EDGE-4: Streak-read failure at arm time: still arm enabled SINGLE tiers (need only this cycle's outcome); do NOT arm DOUBLE tiers (need streak); attempt the streak write idempotently.
- CO-EDGE-5: Duration 0/negative reaching the engine (defense in depth past validation) => cooloff_until in the past => no block; log.
- CO-EDGE-6: Restart while cooling off: cooloff_until + streak persist in DB; gate honors them; expired-on-restart cooloff_until is treated as inactive (no negative remaining shown).
- CO-EDGE-7: Config edited mid-cool-off: an in-flight scan's executor already built from old config; the account-wide block is read live from DB; changing a duration applies to FUTURE cool-offs only; the active cooloff_until is unchanged.
- CO-EDGE-8: Disabling the trigger whose cool-off is currently active does NOT auto-lift it (D13); only Resume-now ends it early.
- CO-EDGE-9: Manual clear during an active cool-off resumes auto-trading immediately; streak counters unchanged.
- CO-EDGE-10: Cool-off cannot interfere with closing existing positions or with any existing close rule — regression test proves close-rule evaluation runs identically regardless of cool-off state.
- CO-EDGE-11: Exactly-flat net_pnl == 0 => neutral (no cool-off, no streak change).
- CO-EDGE-12: A cycle that opens trades which all fail to fill / immediately cancel (no realized pnl, never went non-flat) is not a completed cycle => no outcome.

## Testing [TEST]

- CO-TEST-1: Unit tests for the shared classifier + streak state machine: success/failure/neutral, opposite-resets-to-1, double-overrides-single, post-double reset-to-0, first-cycle, transparent-neutral, clamp.
- CO-TEST-2: Live gate tests: blocks at init_balances + post_scan_recheck; runs before state-reset; lazy expiry; fail-open on error/corrupt; PAUSE+cooloff compose (OR).
- CO-TEST-3: Atomicity/idempotency tests: same cycle processed once under retry/reconciler-rerun; concurrent completions don't lose streak updates; max re-arm never shortens.
- CO-TEST-4: Outcome-detection tests: flat transition across reconciler + rule + manual close paths; partial close not premature; manual-only flatness ignored; multi-event single pass = one outcome.
- CO-TEST-5: Backtest tests: enforcement skips entries in sim window; skipped scan no outcome/streak; cool-off OFF byte-identical golden; determinism (run twice identical); skipped-signal stat; band emission+clamp+merge.
- CO-TEST-6: Schema validation tests: enabled-requires-duration; bounds; extra=forbid; backward-compat (absent fields => OFF) on both manual + scheduled paths.
- CO-TEST-7: Frontend tests: CoolOffFields renders+binds in AutoTradeSection (both pages); unit conversion round-trip; validation blocks save; badge/countdown; Resume-now mutation+invalidations; backtest bands+stat.
- CO-TEST-8: API tests: status endpoint shape+authz; clear endpoint (no streak reset, idempotent, audited).
- CO-TEST-9: Security/isolation: cool-off only gates entries (close path unaffected); backtest never touches live table; per-account isolation; one user can't read/clear another's cool-off.

## Out of Scope (v1)

- Configurable streak threshold (>2). Hard-coded at 2.
- Per-schedule (non-account-wide) cool-off scope.
- Cool-off based on the close-rule that ended the cycle (rejected: inert for most configs — see CF1 in progress-tracker).
- AI Manager cool-off integration.
- Cycle-engine / source='cycle' cool-off gating AND arming. The manual TradingCycleEngine places trades directly and honors no entry gate today (not even PAUSE_TRADING); cool-off covers the SCAN auto-trade surface (scheduled + manual scan) only, consistent with the existing PAUSE limitation. (D35/D47, CO-DET-12)

> **NOTE on the [DETECT2]/[BACKTEST2] sections below:** these were written during requirements
> round 3 and describe an EARLIER `cooloff_cycle_seq` grouping + in-close-txn hook. The
> architecture review (Step 3) SUPERSEDED that mechanism. The AUTHORITATIVE design is
> `specs/cool-off-time-architecture.md` (deferred CooloffClassifier, closed_at composite
> high-water key, no trades-table column, source='scanner'-only arming/gating). Where the
> sections below conflict with the architecture doc, the architecture doc wins. The intent of
> each CO-DET-*/CO-BT-* requirement still holds; only the implementation mechanism changed.

## Round 3 Additions — Net-P&L-at-Flat Correctness [DETECT2]

- CO-DET-8: Cycle grouping uses a stamped per-account episode sequence `cooloff_cycle_seq BIGINT` on the trades table, set at open = the account's current seq; the seq increments atomically only on a flat->non-flat transition (first open while flat). Cycle outcome = SUM(net_pnl) WHERE account_id=$1 AND cooloff_cycle_seq=$2 AND source IN ('scanner','cycle'). This is robust to fill_to_max_trades, post_scan_recheck, multiple schedules, and partial-close children (which inherit the parent seq). last_processed_cycle_key (CO-LIVE-7) = the seq.
- CO-DET-9: There is a THIRD live close chokepoint beyond _close_full and reconcile_close: close_positions_service.close_all_for_rule -> _close_single_position -> trade_service.close_trade_record_only. This is the PRIMARY cycle-end path (TP/SL/drawdown/trailing/breakeven/max-duration all fire through close rules). Flat-detection must hook ALL THREE paths (preferably one shared _repo-level post-close hook) + the _handle_close_failure "genuinely gone -> record closed" branch.
- CO-DET-10: The cycle net_pnl sum MUST include partial-close child rows (parent_trade_id IS NOT NULL). Do NOT copy the stats convention `parent_trade_id IS NULL` (it would drop partial portions and can flip a win/loss). Grouping by cooloff_cycle_seq (children inherit parent seq) handles this correctly.
- CO-DET-11: Cross-path flat-detection race: two different close paths committing in separate transactions (e.g. reconciler closing symbol A while a close-rule closes symbol B) must not both miss or both fire the flat transition. The "close-write + open-count read + classify/arm" must serialize per account via pg_advisory_xact_lock(hashtext(account_id)) (or SELECT ... FOR UPDATE). The cooloff_cycle_seq idempotency backstops a double-fire.
- CO-DET-12: Cycle-engine (source='cycle') trades can transiently go flat BETWEEN legs of an in-flight engine cycle; arming a cool-off there would wrongly block the engine's own next leg. Resolution (pin in Architecture): EITHER exclude source='cycle' from flat-based arming and let TradingCycleEngine signal completion via the trading_cycles terminal state, OR gate arming on the trading_cycle_id being finalized (not merely zero-open). v1 scope note: the user's feature targets scan auto-trade; cycle-engine integration must at minimum NOT corrupt engine cycles.

## Round 3 Additions — Backtest Flat Model [BACKTEST2]

- CO-BT-14: SUPERSEDES CO-BT-2's "per-scan cohort." Backtest cohort = all trades closed since the previous flat checkpoint (account-flat model matching live CO-DET-1), NOT per-scan. In sim, open_positions IS the entire auto book (no manual trades) so flat = (len(open_positions)==0). Document the "sim has no manual source" assumption. This keeps the one-algorithm-two-backends guarantee (CO-BT-4): live merges overlapping scans' trades into one flat-episode outcome, and so must the backtest.
- CO-BT-15: Flat-detection hook lives at exactly ONE authoritative site in the engine: inside _close_position, immediately after open_positions.remove — `if cooloff_enabled and was_nonempty and not state.open_positions:` classify cohort, arm, advance checkpoint, anchor cooloff_until = exit_time + duration. Covers all close paths (rules/live-selection/end force-close) and fires once per flat. Do NOT also hook after _evaluate_window (double-fire).
- CO-BT-16: Cohort grouping in sim uses an integer high-water-mark: store last_flat_idx = len(state.closed_trades) at each flat transition; cohort = closed_trades[last_flat_idx:]. Advance the index on EVERY flat transition including neutral (net==0), else the next cohort double-counts neutral trades and can flip sign. (Timestamp-based grouping is non-deterministic when multiple symbols close on the same candle.)
- CO-BT-17: Cool-off gate is a SEPARATE branch BEFORE the L448-486 entry block (it must skip even on a flat book, unlike skip_if_positions_open). Compute the prospective entry instant first (post_recheck_time for the recheck branch, else selection_time), gate on cooloff_active(entry_instant), increment signals_skipped_cooloff, still _evaluate_window open positions, then continue — and explicitly DO NOT touch cycle_start_equity / rule clocks (carried positions keep the last non-skipped anchor, exactly like the skip_if_positions_open path). Cool-off checked before skip_if_positions_open for stat/band attribution.
- CO-BT-18: The entire cool-off hook + gate + new state mutations are gated behind cooloff_enabled = any(tier enabled), computed once. When OFF: zero new mutations, no new filter_stats/band keys, _close_position and the main loop run the exact prior code path (preserves CO-BT-5 byte-identical golden). New SimulationState fields must be defaulted and never read when OFF. (Note: cycle_active/cycle_start_time at engine L174/176 are dead fields — do not repurpose them in a way that affects OFF output.)
- CO-BT-19: Terminal end-of-sim force-close flattens the book and would classify an inert cohort (arms a cooloff_until with no future scan to block, mutates terminal streak/stat). Either skip the hook for the terminal force-close, or document it as classified-but-inert so CO-OBS-5 stats reconcile. Pin in Architecture.
