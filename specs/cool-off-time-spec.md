# Specification: Cool Off Time

## A. Title and Metadata
- **Feature:** Cool Off Time — account-specific auto-trade pause after cycle outcomes
- **Date:** 2026-06-11
- **Author:** /new-feature workflow
- **Status:** Draft → Spec Review (Step 5)
- **Related modules:** auto_trade_service, trade_service/trade_repository, position_reconciler, backtest_engine, scan_scheduler_service, accounts router, frontend AutoTradeSection
- **Related files:** see Discovery (§B)
- **Inputs:** specs/cool-off-time-requirements.md (120 reqs), specs/cool-off-time-architecture.md (converged R6), plans/cool-off-time/progress-tracker.md (Decided Log D1-D54)
- **Version:** 1.0

## B. Discovery Summary
- **Live auto-trade:** `backend/services/auto_trade_service.py` — `AutoTradeExecutor` built fresh per scan; gate precedent `_is_account_paused` (L346) called at `init_balances` (L483) + `post_scan_recheck` (L1006); per-account `_AccountState`.
- **Close lifecycle:** `backend/services/trade_repository.py` `close_trade` (L253) / `reconcile_close` (L318); `trade_service.py` `_close_full`/`reconcile_close`/`close_trade_record_only` all wrap repo calls in `conn.transaction()`. `position_reconciler.py` per-account loop (L99) detects exchange closes, backfills `net_pnl` via direct UPDATE (24h window, L116-120).
- **Win/loss truth:** universal `is_win = net_pnl > 0` (signal_performance_service.py:152); Bybit `net_pnl = closedPnl − fees` is funding-excluded.
- **trades table** (async_persistence.py:50): `account_id, net_pnl, closed_at, status, source('manual'|'cycle'|'scanner'), exit_price`; `idx_trades_active` defines open; `idx_trades_account_closed (account_id, closed_at DESC, id DESC)`.
- **Backtest:** `backtest_engine.py` `run()` (L221) main loop (L395) over scans in sim time; `_close_position` (L1954) single `open_positions.remove` (L2049) records `pnl`(funding-incl)+`funding_paid`; `SimulationState` (L165) `cycle_start_equity`, `closed_trades`; flat-gate precedent `skip_if_positions_open` (L458). `BacktestCreateRequest` (backtest_schemas.py:40) = flat mirror of AutoTradeConfig.
- **Config:** `AutoTradeConfig` (schemas/__init__.py:444, `extra="forbid"`), TS `AutoTradeConfig` (client.ts:326), shared `AutoTradeSection.tsx` (used by ScannerPage + ScheduledScansPage).
- **Migrations:** `_MIGRATIONS` list (async_persistence.py:1027), current v60, applied on startup.
- **Constraint:** real money — the close/position path must remain untouched and byte-identical; backtest OFF must be byte-identical to current.

## C. Feature Overview
Four optional, account-specific cool-off triggers (all default OFF) that pause auto-trading
for a configurable duration after an auto-trade cycle completes win/loss:
1. Success cool off, 2. Failure cool off, 3. Double-success (2 consecutive wins),
4. Double-failure (2 consecutive losses). Configured per-account in both the manual Market
Scan and Scheduled Market Scan auto-trade settings; enforced in live trading and backtesting.

## D. Business Goal
Let operators impose disciplined pacing on automated strategies — cooling down after wins
(lock gains, avoid over-trading) or losses (stop tilt/chasing) — reducing risk on a
real-money system. Success = the pause arms correctly on the right outcome, blocks new
auto-entries for the configured time, never interferes with closing positions, and behaves
identically (within <1%) in backtest so operators can validate before going live.

## E. Current System Behavior
- Auto-trade runs every scan with no outcome-based pacing; the only account-wide halt is the
  AI `PAUSE_TRADING` rule (checked by `_is_account_paused`).
- A cycle's trades close via TP/SL/equity-rules/duration; `net_pnl` is finalized on close
  (rule/manual path) or backfilled async by the reconciler (exchange path).
- Backtest replays scans and never models any cool-off.

## F. Expected New Behavior
- When an account's scanner cycle completes (returns to zero open scanner positions) with
  net realized P&L > 0 (success) / < 0 (failure) / == 0 (neutral, no-op), update the streak
  and, if the matching enabled tier fires, arm a cool-off until `completion_time + duration`.
- While a cool-off is active, the auto-trade gate blocks all new scanner auto-entries for the
  account (manual + scheduled), additively with the existing PAUSE gate; open positions and
  their close rules are unaffected.
- The UI shows the 4 settings per account and a live "cooling off until / reason" badge with
  a Resume-now control; the backtest honors cool-off in sim time and reports skipped-signal
  stats + equity-curve bands.

## G. Scope
### In Scope
- 8 config fields (4 enabled flags + 4 minutes) on AutoTradeConfig, BacktestCreateRequest, TS type.
- `account_cooloff_state` table (migration v61); `CooloffRepository` + `cooloff_core` + `CooloffClassifier` + 60s sweep.
- Live gate `_account_in_cooloff`; status API + clear endpoint.
- Backtest enforcement + reporting (stat + bands).
- Frontend `CoolOffFields` (shared) + live badge/Resume-now + backtest UI.

### Out of Scope
- Configurable streak threshold (fixed at 2); per-schedule scope; close-rule-based outcome;
  AI Manager integration; cycle-engine (`source='cycle'`) gating/arming.

### Future Scope
- Cycle-engine cool-off; configurable streak length; per-strategy-cohort cool-off.

## H. Functional Requirements

- FR-001: AutoTradeConfig and BacktestCreateRequest each expose 8 fields: cooloff_on_success_enabled/_minutes, cooloff_on_failure_enabled/_minutes, cooloff_on_double_success_enabled/_minutes, cooloff_on_double_failure_enabled/_minutes. Enabled defaults false; minutes Optional[int] ge=1 le=43200; extra="forbid". (CO-CFG-1..4)
- FR-002: If any *_enabled is true, its *_minutes is required (model_validator); else minutes ignored. Absent fields deserialize to all-OFF. (CO-CFG-4/5)
- FR-003: A scanner cycle completes when the account returns to zero open scanner positions/trades (non-terminal status; source='scanner'); outcome = sign of SUM(net_pnl) of that flat episode. >0 success, <0 failure, ==0 neutral. (CO-CORE-2, CO-DET-1)
- FR-004: Episode grouping = source='scanner' closed trades after the composite (closed_at,id) high-water mark, split at flat boundaries; includes partial-close children. (arch §4)
- FR-005: classify_outcome(net) is pure: None/non-finite -> neutral; >0 success; <0 failure; ==0 neutral. (arch §6)
- FR-006: cooloff_core.decide(streaks, outcome, settings) -> ArmDecision: success -> wins+1,losses=0; failure -> losses+1,wins=0; neutral -> unchanged; double fires when the just-incremented side >=2 and the double tier enabled (then reset that side to 0); else single tier if enabled; double overrides single; streaks clamped at 2. (CO-STREAK-2..7, CO-CORE-4/6)
- FR-007: Arming sets cooloff_until = completion_time + duration_minutes (max(existing,new), never shortens) and cooloff_reason. **completion_time = the flat instant = max(closed_at) of the settled episode (NOT detection wall-clock)**, so live arm-time and backtest arm-time are identical for the same episode (DS4). (CO-CORE-5, CO-LIVE-8)
- FR-008: The CooloffClassifier runs in its OWN transaction, never inside any close transaction; driven by (a) a post-commit fire-and-forget trigger fired from ALL THREE live close chokepoints (trade_service _close_full, reconcile_close, close_trade_record_only) AND the _handle_close_failure "genuinely gone" branch, (b) a 60s per-account sweep, (c) a gate-time synchronous call before reading cooloff_until. All idempotent via the monotonic high-water mark. (CO-LIVE-5/6/7, CO-DET-9, arch §3, D16, DS9)
- FR-009: An episode is classified only when every episode trade is settled (status='closed' AND (exit_price<>0 OR net_pnl<>0)); else deferred. If episode max(closed_at) is older than STALE_MIN = 1560 minutes (26h = reconciler 24h horizon + 2h margin), advance past it as neutral + ERROR alert. (CO-DET-7, D31/D43/D51, DS23)
- FR-010: Live gate AutoTradeExecutor._account_in_cooloff(account_id) is called at init_balances (~L483) and post_scan_recheck (~L1006, before the state-reset block); sets state.stopped + stopped_reason="cooloff_active". Composes additively with _is_account_paused (OR). (CO-LIVE-2/3, CO-CORE-9)
- FR-011: Lazy expiry is a guarded conditional UPDATE that nulls cooloff_until/reason only when the read value is still active and <= now. (CO-LIVE-4, D26)
- FR-012: Cool-off gates only NEW scanner auto-entries; it never opens/closes positions, never modifies close rules, does not gate the cycle-engine (source='cycle') or user manual trades. (CO-CORE-8/11, D35)
- FR-013: Settings snapshot persisted to account_cooloff_state by TWO column-scoped writers: (1) config-save for scheduled scans (authoritative); (2) an un-gated init_balances pre-pass (before the stopped-check) for manual scans + freshness. CLOBBER GUARD (DS19): writer-2 upserts cool-off settings ONLY when the in-hand config has >=1 tier enabled (explicit opt-in); an all-OFF manual config (default-OFF from localStorage) must NOT overwrite an account's enabled scheduled settings. Disabling cool-off is done via the scheduled config or Resume-now, never as a side-effect of launching an all-OFF manual scan. Never touches state columns. (D21/D46, DS19)
- FR-014: GET account cool-off status returns cooloff_until, cooloff_reason, consecutive_wins, consecutive_losses, cooloff_remaining_seconds; same per-account authz as other account reads. (CO-API-1, D28)
- FR-015: POST /accounts/{id}/cooloff/clear nulls cooloff_until/reason (guarded UPDATE); does NOT reset streak unless reset_streak=true; same per-account authz; audited; idempotent. (CO-API-2, D28)
- FR-016: Backtest enforces cool-off in sim time: ARM hook at the single _close_position flat site (close_reason != "backtest_end"); cohort net = sum(pnl + funding_paid) (funding-excluded, fees-included); same cooloff_core. (CO-BT-2/15, D33/D44)
- FR-017: Backtest GATE at THREE mandatory sites (selection_time, post_recheck_time, live_selection) before opening; skipped scan opens nothing, is not a cycle, does not advance streak; carried positions still evaluated over the non-cooled branch window. (CO-BT-17, D24/D39)
- FR-018: Episode-boundary rule identical live+backtest: a close at T and open at T leave the account flat at T -> SPLIT (not merge); live orders by (closed_at,id) treating close before same-instant open. (D45)
- FR-019: Backtest reports signals_skipped_cooloff (by reason) and cool-off bands {start,end,reason} clamped to [report_start,report_end] with overlaps merged; carried in the summary dict and emitted ONLY when cooloff_enabled. (CO-BT-8/10, D25/D34)
- FR-020: With all 4 tiers OFF, backtest output is byte-identical to current (no new keys/fields/mutations); gated by SimulationState.cooloff_enabled = any(tier). (CO-BT-5/18, D52)
- FR-021: Frontend CoolOffFields component (mirrors RegimeStrategyFields) mounts in the shared AutoTradeSection -> both manual + scheduled; per setting: NeuSwitch + numeric Input + Min/Hr unit selector; minutes stored, Hr conversion via Math.round(value*60). (CO-FE-1..6)
- FR-022: A live "cooling off" badge (reason + countdown + resume time) renders only when config.account_id present (separate from CoolOffFields, which the backtest form reuses); a Resume-now button calls the clear endpoint (confirm dialog, server-confirmed). Badge data reads from the GET status endpoint (FR-014); countdown authority = server cooloff_remaining_seconds (client ticks locally). Polling/bootstrap (DS25): when >=1 account on the page has cool-off tiers ENABLED, run a baseline status poll (30-60s) + a window-focus refetch so a cool-off armed by a background scan/scheduled run surfaces even from the not-cooling state; additionally invalidate cooloff-status on scan-complete / scheduled-run settle and on Resume-now success (invalidate cooloff-status + ["accounts"] + dashboard). See FR-022(expanded) in §K2 for mount points + states. (CO-FE-8/9/10/11, DS25)
- FR-023: The 8 fields are added to the TS AutoTradeConfig interface + DEFAULT_CONFIG (all OFF/null); localStorage hydration guards missing keys to OFF. (CO-FE-6)

## I. Non-Functional Requirements

- NFR-001: A cool-off failure (classifier exception, lock contention, corrupt value) MUST NEVER roll back or delay a position close, nor abort a scan. Fail-open everywhere on the cool-off path. (D16, CO-EDGE-1/2)
- NFR-002: The trade-close transaction and the repository close methods are unmodified; the only close-side addition is a post-commit fire-and-forget trigger whose scheduling is wrapped so it cannot raise out of a committed close. (D16/D40)
- NFR-003: Migration v61 is additive, idempotent, no trades-table change, no backfill, backward compatible with a rolled-back app. (CO-MIG-1..4)
- NFR-004: Classifier DB reads are plain (no FOR UPDATE); per-account serialization via non-blocking pg_try_advisory_xact_lock(classid, hashtext(account_id)); the gate is never mid-txn when invoking the classifier (no pool starvation). (D42/D50)
- NFR-005: live and backtest produce the same outcome sign for the same economic episode (funding-excluded fees-included net); <1% deviation goal preserved. (D18/D33)
- NFR-006: Hot path: the close path is unchanged; the classifier adds one indexed COUNT (open scanner trades for the account, status IN ('pending','open','partially_filled','closing','partially_closed') — served by idx_trades_account_status_created since idx_trades_active's partial predicate excludes 'pending') + a windowed SELECT (closed scanner trades, served by idx_trades_account_closed) + one UPDATE per episode, only for feature-enabled accounts. Flatness uses the pending-inclusive count so an unfilled limit/MR pre-submit order does not look flat; a place-then-cancel order ends as status='cancelled' (terminal, non-'closed'), so the episode's closed-trade set is empty and no outcome is fabricated — the no-episode result comes from "no closed trade", not from the account staying flat (consistent with FR-028). (SBR-R2-F2, DS27)
- NFR-007: All cool-off timing is UTC (live) / sim time (backtest); cooloff_until stored as timestamptz; DST-immune.
- NFR-008: Every transition logged (cooloff_armed/blocked_scan/expired/cleared/outcome) with structured extra; WARNING for transient fail-open, ERROR for corruption reset/staleness escape. (CO-OBS-1..5)

## K. API Requirements

- GET /accounts/{account_id}/cooloff (or extend the accounts status payload):
  Response { cooloff_until: ISO8601|null, cooloff_reason: enum|null, consecutive_wins:int, consecutive_losses:int, cooloff_remaining_seconds:int }. 200; 403 non-owner; 404 unknown. Auth: same per-account ownership as other account reads.
- POST /accounts/{account_id}/cooloff/clear?reset_streak=false:
  guarded UPDATE nulling cooloff_until/reason; streak untouched unless reset_streak=true. Response 200 { cleared:bool, cooloff_until:null }. 403 non-owner; 404 unknown. Idempotent. Audited.
- Existing scan endpoints (POST /scanner/scan, POST /scanner/{id}/auto-trade, scheduled-scans POST/PATCH) accept the 8 new fields transparently (already typed list[AutoTradeConfig]); backward compatible.

## N. Database/Data Requirements

- New table account_cooloff_state (migration v61) per arch §8: account_id PK REFERENCES trading_accounts(id) (NO ACTION); cooloff_until timestamptz; cooloff_reason text CHECK enum; consecutive_wins/losses smallint NOT NULL DEFAULT 0 CHECK >=0; last_processed_close_at timestamptz; last_processed_close_id uuid; 8 settings columns (bools default false; *_minutes int CHECK NULL OR 1..43200); updated_at timestamptz; CHECK ((cooloff_until IS NULL)=(cooloff_reason IS NULL)).
- No change to the trades table. Queries served by existing idx_trades_account_status_created (pending-inclusive open count) + idx_trades_account_closed (windowed closed SELECT). (See NFR-006.)
- Rollback: drop the table (or leave inert); no data migration to reverse.

## S. Edge Cases
- Unparseable/corrupt cooloff_until -> fail-open, ERROR, reset (read-side clamp > 31d). (CO-EDGE-1/3)
- Transient DB error in gate/classifier -> fail-open, WARNING. (CO-EDGE-2)
- Streak read fails at arm -> arm enabled SINGLE tier, skip DOUBLE. (CO-EDGE-4)
- Partial close: parent stays open -> not flat; children summed via closed_at window. (CO-DET-10, D41)
- Manual-only flatness (no scanner cycle) -> no outcome. (CO-DET-4)
- Restart mid-cooloff -> cooloff_until + streak persisted -> honored. (CO-EDGE-6)
- Config edit mid-cooloff -> active pause unchanged (future-only); disabling a tier does not lift an active pause (only Resume-now does). (CO-EDGE-7/8, D13)
- Permanently-stuck trade -> staleness escape advances as neutral + alert; cannot starve future cool-offs. (D32/D43/D51)
- Duration shorter than scan cadence / sim interval -> may block zero scans; documented no-op. (CO-BT-13)

## T. Testing Requirements
Per CO-TEST-1..9: pure-core unit tests (state machine), live gate tests, atomicity/idempotency, outcome-detection across all close paths, backtest enforcement + OFF-golden + determinism + bands, schema validation + backward-compat, API shape/authz, security/isolation. 90%+ coverage on new modules.

## U. Acceptance Criteria
- AC-001: Given failure cool off enabled (60m) and a scanner cycle that goes flat with summed net_pnl<0, when the cycle settles, then cooloff_until = completion+60m and the next scan for that account is blocked (stopped_reason=cooloff_active) until expiry. (FR-003/006/007/010)
- AC-002: Given double-failure enabled and two consecutive losing cycles, when the second settles, then the double-failure duration is armed (not the single), and that streak resets to 0. (FR-006)
- AC-003: Given a neutral cycle (net_pnl==0), when it settles, then no cool-off arms and streaks are unchanged. (FR-005/006)
- AC-004: Given a cool-off arming bug that raises, when a position closes, then the close still commits and the position is recorded closed (no rollback). (NFR-001/002)
- AC-005: Given all 4 tiers OFF, when a backtest runs on a fixed dataset, then output is byte-identical to a golden SimulationResult captured from master on that dataset and checked in: assert exact equality of json.dumps(result, sort_keys=True) with zero float tolerance (relies on the cooloff_enabled-gated unchanged code path). (FR-020, DS22)
- AC-006: Given identical config (cool-off ON) + data, when a backtest runs twice, then results are identical (determinism). (NFR-005)
- AC-007: Given the same economic episode, when run live vs backtest, then the classified outcome sign matches. (NFR-005)
- AC-008: Given an active cool-off, when the user clicks Resume-now, then cooloff_until is nulled, auto-trade resumes, and streak counters are unchanged. (FR-015)
- AC-009: Given cool-off settings entered in the manual scan UI for account A, when viewing the scheduled scan UI for account A, then the same values appear (shared component) and persist. (FR-021)
- AC-010: Given a partial-then-full close of a cycle, when it settles, then the episode net sums both the child and parent net_pnl. (FR-004, CO-DET-10)

## V. Risks
- R1 (Critical, mitigated): cool-off interfering with closes -> decoupled classifier, NFR-001/002, AC-004 + regression test.
- R2 (High, mitigated): live/backtest divergence near zero -> funding-excluded canonical net (D18/D33), AC-007.
- R3 (High, mitigated): classifying on provisional P&L -> settlement guard + staleness escape (FR-009).
- R4 (Medium, mitigated): OFF-path regression in backtest -> cooloff_enabled gate + byte-identical golden test (AC-005).
- R5 (Medium, mitigated): missed/late arm on reconciler-closed losses -> gate-time sync classify + sweep; documented inherent close-detection latency.

## W. Assumptions
- A-001: scanner cycles are the target surface; cycle-engine cool-off is out of scope (Low risk; documented).
- A-002: account-global cool-off settings (no per-schedule divergence); last-saved wins (Low).
- A-003: net_pnl on closed scanner trades is the authoritative funding-excluded realized P&L (Low; verified in reconciler + close paths).

## Y. Traceability (summary; full matrix in plan)
Every FR maps to at least one requirement (CO-*), at least one phase task (plan Step 6), at least one test (CO-TEST-*), and at least one AC. Architecture decisions D1-D54 are the rationale layer.

## Z. Definition of Ready
Scope clear; requirements testable; edge cases enumerated; codebase impact mapped to exact files/lines; architecture converged (R6); risks mitigated; ACs measurable; no unresolved Critical/High.

## H2. Functional Requirements — Spec-Review Additions (DS1/DS2/DS13/DS15/DS16)

- FR-024: Backtest results FRONTEND rendering: a "Signals skipped (cool-off)" stat (by trigger) in MetricsGrid, and shaded ReferenceArea cool-off bands on EquityCurveChart (new cooloffBands prop) with a legend entry and a show/hide toggle (default ON); sourced from run.results; rendered only when cool-off data is present (OFF run => absent). (CO-FE-13, DS1)
- FR-025: Frontend validation: when a tier is enabled its duration is required and bounded (unit-aware [1,43200] min / [1,720] hr); show an inline neumorphic error; BLOCK Save (scheduled) / Launch (manual) while any enabled tier is invalid/blank; identify the offending account + tier. (CO-FE-7, DS2)
- FR-026: ScannerPage handleStart pre-launch check: if a selected account is currently cooling off, warn/confirm before firing the manual scan (manual surface only; scheduled persists config without immediate launch). (CO-FE-12, DS13)
- FR-027: Render the cooloff_active stopped_reason in the scan/lifecycle UI, visually distinct from ai_paused_trading, so a no-trade outcome is explained. (CO-OBS-4, DS13)
- FR-028: A scan whose trades all cancel / never fill produces no settled scanner episode — a cancelled/never-filled order ends terminal but non-'closed', so the episode's closed-trade set is empty, hence no outcome and no streak move (the guarantee comes from "no closed trade", NOT from flat-transition tracking). (Note: scanner auto-trade has no engine shutdown-force-close path — that is cycle-engine only; scanner positions left open across a restart are reconciled as REAL exchange closes and legitimately count.) (CO-EDGE-12, DS17/DS20, SBR-R5-F1)
- FR-029: The gate-blocking predicate is a PURE time comparison: an account is blocked iff cooloff_until IS NOT NULL AND now < cooloff_until. Lazy-expiry (FR-011) is cleanup only — a failed expiry UPDATE never extends a block. (DS12, SSR-F5)
- FR-030: MCP accounts/config payloads expose the 8 cool-off fields (timestamps/counters need no money-redaction). (CO-API-3, DS16)

## I2. Non-Functional Requirements — Spec-Review Additions

- NFR-009: An active cool-off MUST NOT delay or skip close-rule evaluation, TP/SL, max-duration, equity, or trailing closes for open positions. The cool-off stopped flag gates ONLY new-entry selection. Structural basis: position closes are driven by close_rule_evaluator + position_reconciler, which do NOT read AutoTradeExecutor.stopped; the gate only suppresses new-entry selection in the executor. (DS3, SSR-F1)
- NFR-010: Cool-off UI accessibility: switch role + aria-checked on toggles; Min/Hr as a keyboard radiogroup with aria-label; inputs aria-describedby their validation text; countdown badge aria-live=polite throttled to ~1/min; respect prefers-reduced-motion; reason + time conveyed as text, not color alone. (CO-FE-14, DS13)
- NFR-011: Cool-off UI responsive + theming: rows reflow (input+unit stack below toggle) on narrow widths; touch targets >=44px; badge truncates to icon+time with full text in tooltip; full dark/light parity. (CO-FE-15, DS13)
- NFR-012: API authz — the status (FR-014) and clear (FR-015) endpoints MUST enforce the same per-account ownership control as existing account mutations (the concrete primitive is named in the plan; if the deployment is a networked cookie-auth app, the clear POST requires CSRF protection). Threat model: primarily a single-operator localhost tool; the control must be a real enforced check, not an inherited no-op. (DS8, SSR-F3)

## K2. Frontend detail clarifications (fold into FR-021/022)
- FR-021 (expanded): grouped layout "Single trade" (Success, Failure) + "Win/Loss streak" (Double-success, Double-failure); applying per-tier defaults on enable (success 30m, failure 60m, double-success 60m, double-failure 120m) and PRESERVING the last value on disable (local state); minutes stored canonically (Hr entry -> Math.round(value*60)). UNIT SELECTOR is STICKY per-card edit state (DS24): defaults to Min, or Hr if the stored minutes %60==0 and >=60 on FIRST load only; thereafter the user's selection persists (not re-derived each render). Validation bounds against the SELECTED unit; 1-decimal hours allowed on input but minutes is the source of truth. Hr-display precision (DS24/SFR-R3-F1): when the selected unit is Hr and stored minutes is not a clean 1-decimal-hour multiple (e.g. 45m -> 0.75h), display the full-precision value and leave stored minutes UNCHANGED until the user actually edits the field (never silently re-round the canonical minutes on render/save). Each account card holds independent cool-off config + edit state. (CO-FE-2/4/5, DS13/DS24)
- FR-022 (expanded): the live badge reads from the GET status endpoint (FR-014); mounts on the account card, the ScannerPage account selector, and the ScheduledScansPage per-account row; styled distinctly from the AI PAUSE badge. Countdown authority = server cooloff_remaining_seconds as the anchor (client ticks locally; document skew). Two-tier polling (DS25): a baseline poll (30-60s) + window-focus refetch whenever >=1 account on the page has cool-off tiers ENABLED (so a background-armed cool-off surfaces from the not-cooling state), and a faster cadence (~15s) while an account is actively cooling off; on countdown reaching 0, refetch/invalidate to flip the badge; also invalidate on scan-complete / scheduled-run settle. Resume-now: confirm dialog, server-confirmed (not optimistic); on success invalidate the cooloff-status query + ["accounts"] + dashboard query. Render loading / error / empty / account-removed(404) and Resume-now in-flight states. (CO-FE-8/9/10/11, DS13/DS25)

## S2. Edge Cases — Spec-Review Additions
- Scanner positions left open across a server restart are reconciled as REAL exchange closes and legitimately count toward an episode (NOT a non-trading termination — scanner has no engine shutdown-force-close path). (FR-028)
- A scan whose trades all cancel / never fill -> the episode's closed-trade set is empty (cancelled = terminal, non-'closed') -> no outcome. (CO-EDGE-12)
- Duration 0/negative reaching the engine (defense-in-depth past validation) -> cooloff_until in the past -> no block; logged. (CO-EDGE-5)
- Corruption clamp threshold = 31d (margin over the 30d=43200min max), consistent in spec + arch; a legitimately-armed 43200min cool-off is NOT flagged corrupt. (DS10)
- Cross-path "both-miss" flat race (reconciler closes A while a close-rule closes B): per-account advisory lock ensures exactly one classification at the true flat transition (neither missed nor doubled). (CO-DET-11)

## U2. Acceptance Criteria — Spec-Review Additions
- AC-011: Given a backtest run with >=1 cool-off tier ON, when results render, then MetricsGrid shows the skipped-by-cool-off count and EquityCurveChart shows cool-off bands with a legend + toggle; given an OFF run, neither appears. (FR-024)
- AC-012: Given an active cool-off and an open scanner position that reaches TP/SL/max-duration, when the close rule fires, then the position still closes on schedule (cool-off never delays a close). (NFR-009)
- AC-013: Given a cool-off arming/classifier failure (exception, lock contention, corrupt value), when it occurs, then (a) any in-flight close still commits, (b) the post-commit trigger is scheduled strictly OUTSIDE the close transaction, and (c) the scan is not aborted — all fail-open. (NFR-001/002)
- AC-014: Given single-failure (60m) AND double-failure (120m) both enabled, when the 2nd consecutive loss settles, then cooloff_reason=double_failure and duration=120m (not 60, not 180). (FR-006, DS11)
- AC-015: Given an episode whose last close and the next open share timestamp T, when classified, then the closing trade groups into the earlier episode (SPLIT at T) — identically in live and backtest. (FR-018, DS7)
- AC-016: Given a past-due cooloff_until whose lazy-expiry UPDATE fails, when the gate runs, then it does NOT block (now>=cooloff_until); and a scan at exactly t==cooloff_until is allowed while t==cooloff_until-1s is blocked, identically live + backtest. (FR-029, DS12)
- AC-017: Given the status or clear endpoint called by a non-owner, then 403; for an unknown account, 404 — for BOTH endpoints. Clear is audited (actor, account_id, reset_streak, streak+cooloff before/after). (NFR-012, FR-015, DS8)
- AC-018: Given a trade stuck unsettled longer than STALE_MIN (~26h), when the sweep runs, then it advances the episode as neutral, emits an ERROR alert, and the next cycle can classify normally. (FR-009, DS18)
- AC-019: Given an episode evaluated with IDENTICAL inputs (fills, fees, funding incl. negative funding, close prices), then the live canonical net (SUM(net_pnl) = realized_pnl − fees, funding-excluded) and the backtest net (sum(pnl + funding_paid)) are equal and classify to the SAME exact sign — no epsilon dead-band (FR-005 keeps ==0 as the sole neutral). NFR-005's <1% deviation is a separate AGGREGATE real-world goal (different fee/slippage models), not a per-episode AC. (DS6/DS21)
- AC-020: Given a cooling-off account whose cool-off settings changed, when the next scan runs init_balances, then the settings snapshot is refreshed (pre-pass runs BEFORE the stopped-check) even though the account is gated. (FR-013, DS18)

## W2. Assumptions — Spec-Review Additions
- A-004: Streak counters are tracked only while >=1 cool-off tier is enabled for the account; enabling a tier mid-streak starts from 0 (supersedes the literal CO-STREAK-7). (DS14)
- A-005: The streak is account-scoped and SHARED across scheduled + manual scans and trend/MR cohorts (a trend loss + an MR loss = account-wide consecutive losses). (CO-STREAK-9, DS14)
- A-006: Cool-off settings are account-global; entering different values in the manual vs scheduled UI for the same account is last-saved-wins, surfaced in the UI so it is not surprising. (DS14)
- A-007: funding_paid is a signed cost on the sim trade; backtest funding-excluded net = pnl + funding_paid for both positive and negative funding. (DS6)

## U3. Acceptance Criteria — Spec-Review R2 Additions (DS30)
- AC-021: Given an enabled cool-off tier with a blank/invalid duration, when the user attempts Save (scheduled) or Launch (manual), then the action is blocked and the offending account+tier is identified with an inline error. (FR-025)
- AC-022: Given an account currently cooling off, when the user starts a manual scan selecting it, then a warn/confirm appears before the scan launches. (FR-026)
- AC-023: Given an account gated by cool-off, when scan results render, then the no-trade reason shows as "cooling off" (visually distinct from the AI PAUSE reason). (FR-027)
- AC-024: Given a scan whose trades all cancel / never fill, when it resolves, then the episode's closed-trade set is empty (cancelled orders are terminal but non-'closed'), so no outcome is classified and streaks are unchanged. (FR-028)
- AC-025: Given the MCP accounts/config payload, then the 8 cool-off fields are present (no money-redaction needed). (FR-030)
- AC-026: Given a manual scan launched with all cool-off tiers OFF for an account that has enabled cool-off settings from a scheduled scan, when init_balances runs, then the account's enabled settings are NOT overwritten to OFF (clobber guard). (FR-013, DS19)

## K3. Status Endpoint Clarification (DS29)
- GET /accounts/{id}/cooloff: a KNOWN account with NO account_cooloff_state row returns 200 with cooloff_until=null, consecutive_wins=0, consecutive_losses=0 (NOT 404). 404 is only for an unknown account. cooloff_remaining_seconds = max(0, cooloff_until - now); when now >= cooloff_until the account is reported not-cooling regardless of whether lazy-expiry has run (consistent with FR-029 pure-time predicate).

## V3. Risk — Spec-Review R2 Addition
- R6 (Low, accepted+documented): single monotonic high-water mark processes episodes in order; a permanently-stuck earlier episode can delay arming of later settled episodes up to STALE_MIN (26h). Rare (requires a stuck/unsettled trade), bounded by the staleness escape, and the gate-time synchronous classify handles the common just-completed-cycle path immediately. (DS26, SBR-R2-F4)
