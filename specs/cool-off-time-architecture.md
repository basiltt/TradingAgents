# Architecture: Cool Off Time

**Status:** Draft → under review
**Date:** 2026-06-11
**Related:** specs/cool-off-time-requirements.md (120 reqs), plans/cool-off-time/progress-tracker.md
**Decision model:** D15 — outcome = net realized P&L at account flat.

## 1. Problem & Forces

Add an optional, per-account pause ("cool off") after an auto-trade **cycle** completes,
keyed on the cycle's win/loss (and 2-in-a-row streaks). Must work identically in live and
backtest, must never touch the close/position path, must be byte-identical to today when
OFF, and must be correct under concurrency, retries, partial closes, and restart — because
it gates real money.

Key forces discovered in code:
- The scan auto-trade path creates account-level equity rules WITHOUT cycle_id, so the
  cycle-engine `_cycle_callback` does NOT fire for it → cannot hook there.
- Most cycles end via per-position TP/SL (no account-level rule) → outcome must be derived
  from realized P&L, not from "which rule ended it".
- Three close paths exist, but they all funnel through TWO repository methods inside a DB
  transaction (see §3) → a single atomic chokepoint is available.

## 2. Component Overview

```
                         ┌─────────────────────────────────────────┐
                         │ cooloff_core.py  (PURE, no I/O)          │
                         │  - classify_outcome(net_pnl) -> outcome  │
                         │  - next_state(state, outcome, cfg, now)  │
                         │    -> (new_streaks, arm?(until,reason))  │
                         │  Shared by LIVE + BACKTEST (one algo)    │
                         └─────────────────────────────────────────┘
              live state-store ▲                         ▲ in-memory sim state
                               │                         │
   ┌───────────────────────────┴──────┐      ┌───────────┴───────────────────────┐
   │ LIVE                              │      │ BACKTEST                           │
   │ account_cooloff_state table       │      │ SimulationState fields             │
   │ CooloffRepository (asyncpg)        │      │ (cooloff_until, streaks, last_idx) │
   │                                    │      │                                    │
   │ ARM: post-close hook inside        │      │ ARM: _close_position flat hook     │
   │  TradeRepository.close_trade/      │      │  (after open_positions.remove)     │
   │  reconcile_close txn (advisory     │      │                                    │
   │  lock per account) → on flat,      │      │ GATE: branch before entry block    │
   │  sum cycle pnl, call core, persist │      │  in run() loop (sim time)          │
   │                                    │      │                                    │
   │ GATE: AutoTradeExecutor.           │      │ REPORT: skipped counter + bands    │
   │  _account_in_cooloff() at the 2    │      │                                    │
   │  PAUSE sites                        │      │                                    │
   │ CLEAR API: POST .../cooloff/clear   │      │                                    │
   └────────────────────────────────────┘      └────────────────────────────────────┘
```

## 3. Decision A2 (REVISED after R1) — Deferred Classifier, NEVER in the close txn

**R1 CRITICAL (D16):** The original design ran classify+arm INSIDE the close transaction.
A cool-off bug (deadlock, CHECK violation, None) would then roll back the REAL position
close → DB/exchange divergence. Forbidden on a money path. Also net_pnl is NOT final at
close-commit time — the reconciler backfills it asynchronously via a direct UPDATE (D17).

**Decision:** Classification/arming is **fully decoupled from the close path**. The
repository close methods (`close_trade`, `reconcile_close`) and the close TRANSACTION are
**unmodified**. The only close-side change is `trade_service` scheduling a post-commit,
fire-and-forget trigger STRICTLY AFTER its `conn.transaction()` block exits (D40). A
dedicated, idempotent **CooloffClassifier** runs in its OWN transaction, driven THREE ways:
- **(a) Post-commit trigger (latency):** after a close txn commits, `trade_service` does
  `try: t = asyncio.create_task(classifier.maybe_classify(account_id)); _bg.add(t);
  t.add_done_callback(_bg.discard) except Exception: log` — the SCHEDULING is wrapped so it
  can never raise out of a committed close (D40); the task ref is held so it isn't GC'd.
- **(b) Periodic sweep (authoritative safety net):** a per-account loop modeled on
  `PositionReconciler` (60s), started/shutdown in main.py.
- **(c) Gate-time best-effort (closes the resume window, D31):** the live GATE
  (`_account_in_cooloff`, called at scan start BEFORE any entry) first calls
  `maybe_classify(account_id)` synchronously, THEN reads cooloff_until. So a rule-driven loss
  that just settled is classified+armed before the same scan can open new trades.

All three are idempotent (§4/§10); running them together is safe. A cool-off failure can only
delay/skip a PAUSE (fail-open) — it can NEVER affect a close.

**CooloffClassifier.maybe_classify(account_id) — own txn:**
```
if no account_cooloff_state row with any tier enabled: return            # D20
if not pg_try_advisory_xact_lock(CLASSID, hashtext(account_id)): return  # D29 non-blocking
open_auto = COUNT(trades WHERE account_id AND source='scanner'           # D19/D35 scanner-only
              AND status IN ('pending','open','partially_filled','closing','partially_closed'))  # D23
if open_auto > 0: return                                                 # episode in progress (CO-DET-5)
# episode = source='scanner' closed trades after the composite high-water mark (D38), split
# at flat boundaries (D39); take the EARLIEST complete episode:
candidates = SELECT ... WHERE source='scanner' AND status='closed'
             AND (closed_at, id) > (COALESCE($mark_at,'-infinity'), COALESCE($mark_id,...))
             ORDER BY closed_at, id        # plain read, NO FOR UPDATE (D42)
if candidates empty: return
episode = earliest flat-bounded run within candidates (D39)
if ANY episode trade NOT settled — settled ⇔ status='closed' AND (exit_price<>0 OR net_pnl<>0):  # D43
    if episode.max_closed_at < now() - STALE_MIN:   # D51: STALE_MIN ≈ 26h (= reconciler 24h horizon + interval + max paging), strictly > horizon
        advance mark past it as NEUTRAL + ERROR alert + metric (D32)   # only a genuinely-abandoned trade
    return                                  # else wait; sweep/trigger/gate retries
net = SUM(net_pnl) over episode             # D33: net_pnl already funding-excluded; incl children (D41)
outcome = classify_outcome(net); decision = cooloff_core.decide(streaks, outcome, settings)
UPDATE account_cooloff_state SET
   consecutive_wins/losses = decision.streaks,
   last_processed_close_at = episode.max_closed_at, last_processed_close_id = episode.max_id,  # D38
   cooloff_until = decision.arm ? max(existing, episode.max_closed_at + decision.minutes) : existing,  # D26/DS28: anchor on FLAT instant, not now()
   cooloff_reason = ..., updated_at = now()
loop to next episode until caught up (mark strictly advances each iter → terminates)
log cooloff_armed / cooloff_outcome=neutral
```
- Own connection/txn; an exception rolls back ONLY this bookkeeping (fail-open).
- Composite `(closed_at, id)` high-water mark (D38) is the episode boundary AND monotonic
  idempotency token — served by existing `idx_trades_account_closed (account_id, closed_at
  DESC, id DESC)`; no `trades`-table change, no new index. Tie-safe (no skip/double-count).
- Settlement signal (D43): "settled" ⇔ `status='closed' AND (exit_price<>0 OR net_pnl<>0)`.
  The failure-close placeholder writes BOTH exit_price=0 AND net_pnl=0.0 (caught as unsettled);
  a reconciler-backfilled row with real net_pnl but a missing avgExitPrice is still caught by
  net_pnl<>0. The reconciler backfill is a direct UPDATE that does NOT touch closed_at
  (write-once). Staleness escape (D32/D43) fires ONLY when episode.max_closed_at is older than
  RECONCILER_BACKFILL_HORIZON (= the reconciler's 24h give-up window,
  position_reconciler.py:119) PLUS a safety margin for the reconciler's SELECT→COMMIT lag
  (D51): the reconciler selects rows eligible at `closed_at > now−24h` but commits the
  backfill UPDATE seconds-to-minutes later, so STALE_MIN = 24h + reconciler_interval +
  max_paging_time (≈26h), strictly GREATER than the horizon — NOT equal. This guarantees the
  classifier only escapes after any in-flight backfill the reconciler could have selected has
  provably committed, so a recoverable backfill is never pre-empted; only a genuinely-abandoned
  trade is advanced-as-neutral with an ERROR alert.

**Edge — multiple episodes since last sweep:** if the account opened→flat→opened→flat
twice between sweeps, the "closed since high-water" set spans BOTH and would merge them.
Mitigation: the classifier processes ONE episode per call by splitting the closed-since set
at flat boundaries (a gap where cumulative open-count returned to 0), advancing the
high-water mark to the end of the FIRST unprocessed episode and looping until caught up.
This preserves correct per-episode streak counting. (Detail pinned in §4.)

**Config source (D21):** `account_cooloff_state` holds an ACCOUNT-GLOBAL settings snapshot,
written by a COLUMN-SCOPED upsert (settings columns + updated_at ONLY — never touches
cooloff_until/streaks/high-water). See §11 for the authoritative TWO-writer model (config-save
for scheduled scans + an un-gated `init_balances` pre-pass for manual scans + freshness). The
classifier reads settings from this row.

## 4. Decision A1 (REVISED) — Episode Grouping by closed_at High-Water Mark

No `cooloff_cycle_seq` column (removed — it required open-path writes/locks the close
decoupling makes unnecessary). An **episode** = a maximal run of `source='scanner'` trades
bracketed by account-flat points (open scanner-trade count 0 → >0 → 0). Grouping:
- The classifier tracks `last_processed_close_at` per account.
- Candidate trades = `source='scanner' AND status='closed' AND closed_at > last_processed_close_at`, ordered by closed_at.
- An episode boundary is where, replaying opens/closes in time order, the open scanner
  count returns to 0. The classifier processes the earliest complete, fully-settled episode,
  sets the high-water mark to that episode's max(closed_at), and repeats.
- Episode net = `SUM(realized_pnl - fees)` over the episode's trades (D18). Includes partial
  child rows via their own closed_at (D30); never filters `parent_trade_id IS NULL`.

Why closed_at-window over a stamped seq: it needs ZERO changes to the open/insert path and
to `create_child_trade`, keeps the close path untouched, and the high-water mark is a
natural monotonic idempotency token. The only new column is on the cool-off state table.

## 5. Decision A5 (REVISED, D19) — Exclude source='cycle' in v1

The TradingCycleEngine (source='cycle') has NO `final_pnl` and manages multi-leg cycles
whose inter-leg flats must not arm a cool-off (R1 AR-F2: the doc's `final_pnl` hook was
unimplementable). The user's feature targets SCAN auto-trade.

**Decision:** Cool-off classification keys on `source='scanner'` ONLY. Cycle-engine trades
never contribute to an episode, never arm cool-off, and their inter-leg flats are invisible
to the classifier. **Scope (REVISED D35):** the cool-off GATE reaches exactly the surface the
existing PAUSE_TRADING gate reaches — the `AutoTradeExecutor` path, i.e. scheduled + manual
SCAN auto-trade. The manual `TradingCycleEngine` (source='cycle') places trades directly via
`accounts.place_trade` and honors NO gate today (not even PAUSE), so it is NOT gated by
cool-off in v1 — consistent with the existing PAUSE limitation. "Whole-account" (D3) means
all SCAN auto-trade for that account. This resolves AR-F2/F4/F5 and AR-R2-F1, and makes
CO-LIVE-9 (forced cycle terminations) a non-issue. Cycle-engine cool-off is out of scope
(documented in requirements Out-of-Scope).

## 6. Decision A6 — Shared Pure Core (cooloff_core.py)

A pure module with NO I/O, imported by both live and backtest:
```python
# outcome: "success" | "failure" | "neutral"
def classify_outcome(net_pnl: float) -> str:
    if net_pnl is None or not isfinite(net_pnl): return "neutral"   # CO-DET-7
    if net_pnl > 0: return "success"
    if net_pnl < 0: return "failure"
    return "neutral"

@dataclass(frozen=True)
class CooloffSettings:        # 4 (enabled, minutes) pairs
    success_enabled: bool; success_minutes: int | None
    failure_enabled: bool; failure_minutes: int | None
    double_success_enabled: bool; double_success_minutes: int | None
    double_failure_enabled: bool; double_failure_minutes: int | None

@dataclass(frozen=True)
class StreakState:
    consecutive_wins: int
    consecutive_losses: int

@dataclass(frozen=True)
class ArmDecision:
    streaks: StreakState
    arm: bool
    duration_minutes: int | None   # None when arm is False
    reason: str | None             # success|failure|double_success|double_failure

def decide(state: StreakState, outcome: str, cfg: CooloffSettings) -> ArmDecision:
    # neutral: transparent (CO-STREAK-3) → no streak change, no arm
    # success: wins+1, losses->0; double if wins'>=2 and double_success_enabled (reset wins->0),
    #          elif success_enabled arm single; clamp wins at 2 (CO-STREAK-7)
    # failure: symmetric
    # returns ArmDecision; caller computes cooloff_until = now + duration and applies max-rearm
```
The caller (live repo hook / backtest hook) owns: reading current state, persisting new
state, computing `cooloff_until = now + duration`, and applying `max(existing, new)`
(CO-LIVE-8). `now` is injected (UTC in live, sim time in backtest) so the core is
deterministic and clock-agnostic (CO-BT-4/6).

Unit tests target `decide()` exhaustively (CO-TEST-1) with zero infrastructure.

## 7. Decision A7 (REVISED after R1) — Backtest Integration

State (SimulationState, only meaningful when cooloff_enabled):
- `cooloff_enabled: bool = False` — set once in run() at SimulationState construction =
  `any(4 tiers enabled in config)`. Read by `_close_position` (D52) to gate the
  `trade_record["funding_paid"]` persist and by the run() loop to gate the ARM hook + GATE
  branches. The SOLE switch that keeps the OFF path byte-identical.
- `cooloff_until: datetime | None`, `cooloff_reason: str | None`
- `consecutive_wins: int = 0`, `consecutive_losses: int = 0`
- `cooloff_last_flat_idx: int = 0`  (high-water mark into closed_trades)
- `cooloff_bands: list[dict]`, `signals_skipped_cooloff: int` + per-reason counts

ARM hook (CO-BT-15/16): inside `_close_position`, AFTER the single `open_positions.remove`
site (~L2049), guarded by `cooloff_enabled` and `close_reason != "backtest_end"` (D25/QR-F6):
```
if cooloff_enabled and not state.open_positions and close_reason != "backtest_end":
    cohort = state.closed_trades[state.cooloff_last_flat_idx:]
    net = sum(t["pnl"] + t["funding_paid"] for t in cohort)   # D33: backtest pnl is funding-INCL; +funding_paid → funding-EXCL, fees-incl
    outcome = classify_outcome(net)
    dec = decide(StreakState(wins, losses), outcome, cfg)
    state.consecutive_wins, state.consecutive_losses = dec.streaks
    state.cooloff_last_flat_idx = len(state.closed_trades)   # advance on EVERY flat (incl neutral)
    if dec.arm:
        until = exit_time + timedelta(minutes=dec.duration_minutes)
        state.cooloff_until = max(state.cooloff_until or until, until)   # max re-arm (D26 parity)
        state.cooloff_reason = dec.reason
        record band {start: exit_time, end: until, reason}
```
- D33 parity: the backtest recorded `pnl` is funding-INCLUSIVE (`price_pnl − entry_fee −
  exit_fee − funding_paid`), so the cohort net adds `funding_paid` back →
  `price_pnl − fees`, funding-EXCLUDED. LIVE classifies on `SUM(net_pnl)` where Bybit
  `net_pnl = closedPnl − fees` is ALSO funding-excluded. Both = realized P&L net of trading
  fees, funding excluded → identical sign (QR-R2-F1 fix). **`funding_paid` must be persisted
  onto `trade_record` on EVERY backtest close** (`trade_record["funding_paid"] =
  position.funding_paid`), added ONLY when `cooloff_enabled` (OFF ⇒ key absent ⇒
  byte-identical golden, D44). The "compute from the live position at close" alternative is
  REJECTED (D44/YR-R3-F1): the cohort spans many trades but only the last has a live
  `Position`, so it would undercount funding for earlier cohort trades.
- **Episode-boundary rule (D45/YR-R3-F2 — parity-critical, IDENTICAL in both engines):** the
  account is flat (an episode boundary) the instant the open scanner-position count reaches 0.
  A close at time T and a new open at the same time T leave the account flat at T ⇒ **SPLIT**
  (two episodes), NOT merge. Live orders closes by `(closed_at, id)` and treats a close as
  taking effect before a same-instant open; backtest naturally splits because the carried
  position closes in the next scan's pre-open `_evaluate_window` before the open. Tested with
  an equal-timestamp fixture in BOTH engines.
- `was_nonempty` dropped (QR-F7): `_close_position` is always entered with ≥1 open position,
  so the sole flat trigger is the post-remove empty check.
- Terminal suppression scoped strictly to `close_reason == "backtest_end"` (QR-F6) — NOT all
  forced closes; `live_selection_sync` / `_force_close_for_live_selection` flats are REAL
  cycle completions live would classify, so they must still arm.

GATE (CO-BT-17, D24/D39 — THREE sites mirroring live, all MANDATORY): cool-off is re-checked
at the REAL open instant for each branch — NONE optional (QR-R2-F3):
- `selection_time` branch: gate immediately before `_open_scan_signals(..., selection_time)`.
- `post_scan_recheck` branch: gate immediately before the post-recheck open at
  `post_recheck_time` (AFTER the L454-455 recheck window may have flattened+armed).
- `live_selection` branch (L423): gate at its own open instant — MANDATORY (live's
  `_account_in_cooloff` fires for every scan execution, so this branch must skip too).
```
if cooloff_enabled and state.cooloff_until and open_instant < state.cooloff_until:
    state.signals_skipped_cooloff += len(scan_signals); per-reason += ...
    # evaluate carried positions over the SAME window the NON-cooled branch uses for THIS
    # branch — for post_scan_recheck that is [evaluate_from_time(=post_recheck_time), next]
    # (the [scan_started_at, post_recheck_time] window already ran at L454-455; do NOT redo it, QR-R2-F4)
    if state.open_positions: _evaluate_window(scan_config, <non-cooled-branch-window>, next_scan_start)
    continue        # do NOT touch cycle_start_equity / rule clocks
```
Gate ordering: cool-off is checked BEFORE skip_if_positions_open so a cooled scan's signals
land in the cool-off skip bucket (one bucket, CO-BT-9).

OFF-path isolation (CO-BT-18, D25): `cooloff_enabled = any(4 tiers enabled)` computed once at
run() start. When False: ARM hook, GATE branches, and all new-field mutations are skipped; no
new keys in filter_stats/metrics/result → byte-identical golden (CO-BT-5). Band + skip stats
are carried inside the existing `summary` dict and added ONLY when cooloff_enabled (QR-F5) —
no new defaulted top-level field on `BacktestResultsResponse`. Bands clamped to
[report_start, report_end] and overlapping bands merged before emit.

close_reason→outcome is NOT needed: outcome is by P&L SIGN of the cohort, sidestepping the
terminator-mapping problem (CF3).

## 8. Decision A8 (REVISED) — Data Model (migration v61)

```sql
-- migration v61 (next after v60). Additive, idempotent. NO change to the trades table.
CREATE TABLE IF NOT EXISTS account_cooloff_state (
    account_id TEXT PRIMARY KEY REFERENCES trading_accounts(id),   -- NO ACTION (match ai_manager_state, D29)
    -- active cool-off
    cooloff_until        TIMESTAMPTZ,
    cooloff_reason       TEXT CHECK (cooloff_reason IN
                           ('success','failure','double_success','double_failure')),
    -- streak (app clamps 0..2)
    consecutive_wins     SMALLINT NOT NULL DEFAULT 0 CHECK (consecutive_wins  >= 0),
    consecutive_losses   SMALLINT NOT NULL DEFAULT 0 CHECK (consecutive_losses >= 0),
    -- episode idempotency / boundary (D22/D38): composite high-water mark of processed scanner closes
    last_processed_close_at TIMESTAMPTZ,
    last_processed_close_id UUID,
    -- account-global settings snapshot (column-scoped upsert; D21)
    success_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    success_minutes INT CHECK (success_minutes IS NULL OR success_minutes BETWEEN 1 AND 43200),
    failure_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    failure_minutes INT CHECK (failure_minutes IS NULL OR failure_minutes BETWEEN 1 AND 43200),
    double_success_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    double_success_minutes INT CHECK (double_success_minutes IS NULL OR double_success_minutes BETWEEN 1 AND 43200),
    double_failure_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    double_failure_minutes INT CHECK (double_failure_minutes IS NULL OR double_failure_minutes BETWEEN 1 AND 43200),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- paired-null guard (D29): an active cool-off has both until+reason or neither
    CONSTRAINT chk_cooloff_pair CHECK ((cooloff_until IS NULL) = (cooloff_reason IS NULL))
);
```
- One row/account, PK = O(1) gate read. No backfill (CO-MIG-2): absent row ⇒ feature off,
  streak 0. NO ON DELETE clause (accounts are soft-deleted; matches `ai_manager_state`, D29).
- **No `trades` table change** — episode grouping is by `closed_at` high-water mark (§4), so
  the open path, `create_trade`, and `create_child_trade` are untouched; no new `trades` index.
- Hot-path COUNT (open scanner trades for an account) is served by existing `idx_trades_active`
  (partial on status, keyed by account_id) — `source='scanner'` is a cheap residual filter
  over the tiny per-account open set (DR-F6: no new index).
- Every state UPDATE sets `updated_at = NOW()` explicitly (no trigger added; DR-F7).

## 9. Decision A3 (REVISED) — Partial-Close Summation
Episode net = `SUM(realized_pnl - fees)` over `source='scanner' AND status='closed' AND
closed_at` within the episode window (§4), with NO `parent_trade_id IS NULL` filter.
Partial-close children (`create_child_trade`) carry their own `closed_at`, `realized_pnl`,
and `fees`, so they fall into the episode window naturally and contribute their portion;
the parent's residual close contributes separately. This matches CO-DET-10 (include children)
without needing any column on `trades`. Funding is EXCLUDED from the sum (D18) so the sign
matches the backtest's fees-only episode net. Regression test CO-TEST-4 asserts a
partial-then-full close sums both portions.

## 10. Decision A4 (REVISED) — Concurrency / Idempotency / Fail-Safety
- The classifier holds a **non-blocking** `pg_try_advisory_xact_lock(CLASSID, hashtext(account_id))`
  (two-arg form isolates from the migration lock, D29). If not acquired, another
  trigger/sweep owns the account this moment → return (the sweep retries next cycle). This
  NEVER blocks and is in its OWN txn, so it cannot stall or roll back a close (D16/SR-F2).
- Idempotency is the monotonic `last_processed_close_at` high-water mark (D22): an episode
  whose max(closed_at) ≤ the stored mark is already processed → skipped. Retries, the
  post-commit trigger racing the sweep, and reconciler re-runs all converge to one
  classification per episode.
- Deferred-settlement guard (D17/D43/DS28): the classifier refuses to classify an episode until every
  trade in it is fully settled (`status='closed' AND (exit_price<>0 OR net_pnl<>0)`).
  The placeholder-0 close (`_handle_close_failure`) + async reconciler backfill therefore
  cannot cause classification on provisional P&L; the sweep simply retries until settled.
- All state mutation is one UPDATE; a classifier exception rolls back only its own txn and is
  logged (fail-open: a missed/late arm just allows trading, never blocks a close).
- Lazy-expiry of an active cool-off (gate side) is a GUARDED conditional UPDATE (D26):
  `SET cooloff_until=NULL, cooloff_reason=NULL WHERE account_id=$1 AND cooloff_until=$read AND cooloff_until<=now()`
  so it cannot clobber a freshly-armed future value.

## 11. Decision A9 (REVISED) — Live Wiring, Gate + API
- **Classifier wiring (D48):** main.py constructs a `CooloffRepository(db)` + a singleton
  `CooloffClassifier` and stashes them on `app.state.cooloff_repo` /
  `app.state.cooloff_classifier`. (The repo is a stateless pool wrapper — it may be
  re-constructed per call site; only the classifier is a shared singleton. Idempotency lives
  in the DB high-water mark, not in repo instance state.)
  `trade_service.set_cooloff_classifier(classifier)` (deferred setter, mirrors set_trade_service)
  is wired after both are built (no constructor cycle, D37). The classifier imports only
  CooloffRepository — never trade_service/trade_repository — so no circular import.
- **Settings snapshot — TWO column-scoped writers (D46, settings cols + updated_at ONLY,
  never state cols):**
  (1) **config-save path for SCHEDULED scans** (POST/PATCH /scheduled-scans → update/insert
      scheduled_scan): persists settings immediately on save, survives even if the scan never
      runs, and handles toggle-off.
  (2) **un-gated PRE-PASS in `AutoTradeExecutor.init_balances`** over `self._state.values()`
      placed BEFORE the L461 stopped-check (mirroring the existing close_on_profit pre-pass at
      L403-410): captures MANUAL-scan settings (which have no persisted config-save — config is
      ephemeral per launch) AND keeps the row fresh even when the account is cooling
      off/paused/positions-open. MUST be un-gated or a perpetually-positions-open account would
      never get a settings row.
- **Gate:** `AutoTradeExecutor._account_in_cooloff(account_id) -> bool`, sibling to
  `_is_account_paused`, called at init_balances (~L483) and post_scan_recheck (~L1006, BEFORE
  the state-reset block, D-tracker). Reads account_cooloff_state; guarded lazy-expiry (D26);
  sets state.stopped_reason="cooloff_active". Fail-OPEN on error/corrupt with read-side clamp
  threshold > max legal duration (31d, D27) — deliberately opposite to PAUSE's fail-closed
  (documented inline). Composes with PAUSE via OR (CO-CORE-9).
- **Status:** extend accounts status/dashboard (or `GET /accounts/{id}/cooloff`) with
  cooloff_until, cooloff_reason, consecutive_wins, consecutive_losses, cooloff_remaining_seconds.
  Same per-account ownership authz as other account reads (D28).
- **Clear:** `POST /accounts/{id}/cooloff/clear` → guarded UPDATE NULLing cooloff_until/reason;
  does NOT reset streak unless `reset_streak=true`; SAME per-account ownership authz as other
  account mutations (D28); audited (actor, account_id, reset_streak, before/after cooloff_until);
  idempotent. Takes the same advisory lock as the classifier to order vs a concurrent arm (SR-F10).
- **DI threading (D54):** `AutoTradeExecutor.__init__` gains `cooloff_repo` + `cooloff_classifier`
  kwargs (None-guarded like `_close_svc`; the backtest builds neither, staying inert). The 3
  live build sites obtain them differently:
  - scanner.py router (`/auto-trade` + scan launch): pass from `request.app.state.cooloff_repo` /
    `app.state.cooloff_classifier`.
  - scanner_service builds (L564 scheduled, L894 resume): scanner_service has `self._db` (ctor
    L319) but no app handle, so it self-constructs `CooloffRepository(self._db)` and reads the
    classifier from an attribute main.py stamps onto it (mirroring the existing
    `app.state.scanner_service._ai_manager_service = ...` pattern at main.py L449).
  - main.py adds the cool-off wiring (none today): build repo+classifier, stash on app.state,
    stamp `app.state.scanner_service._cooloff_classifier`, and call
    `trade_service.set_cooloff_classifier(...)`.

## 12. Rollback & Safety
- Feature is additive + default-off; rollback = stop writing settings (rows stay, all flags
  false ⇒ inert). The v61 migration is forward-only but harmless to a rolled-back app
  (extra table ignored — CO-MIG-3). No `trades` table change to roll back.
- Cool-off NEVER calls place/close and is NEVER in a close transaction (D16). The classifier
  only reads trades + writes account_cooloff_state in its own txn. Structural guarantee +
  CO-TEST-9 / CO-EDGE-10 regression test that the close path + close-rule evaluation are
  byte-identical regardless of cool-off state.
- Hot-path cost: the close path is UNCHANGED. The classifier adds one indexed COUNT + a small
  windowed SELECT + one UPDATE, in its own txn, only for accounts with the feature enabled,
  at most once per close (trigger) plus once per 60s (sweep).

## 13. Self-Review Checklist
- [x] Arming is OUTSIDE the close txn — a cool-off error can never roll back/delay a close (D16).
- [x] Never classify on unsettled/placeholder P&L (D17 settlement guard).
- [x] Live & backtest episode-net both fees-incl / funding-excl (D18) — sign parity.
- [x] source='cycle' excluded from arming; gate covers all SCAN auto-trade for the account;
      cycle-engine ungated, matching the existing PAUSE limitation (D35/D49).
- [x] Byte-identical when OFF (live: no settings row ⇒ classifier early-returns, gate no-ops;
      backtest: cooloff_enabled gate, stats only in summary dict when ON).
- [x] One shared pure core (cooloff_core.decide), `now` injected → deterministic.
- [x] Idempotent (monotonic high-water), non-blocking try-lock, guarded expiry.
- [x] Partial children summed via closed_at window (no trades-table change).
- [x] Backtest single-site hook (backtest_end excluded) + two gate sites + band clamp/merge.
- [x] No layering inversion: close path untouched; classifier is a separate service reading
      via repo, not called from TradeRepository (resolves AR-F7).

## 14. Open Questions — RESOLVED in R1
- OQ1 (streak-when-OFF) → **D20**: streak tracking begins when cool-off is first enabled for
  the account; no hidden state for default-off accounts. The classifier early-returns when no
  settings row has any tier enabled.
- OQ2 (cycle vs scanner) → **D19/D35**: exclude source='cycle' from arming AND gating in v1;
  the cool-off gate covers the AutoTradeExecutor scan surface (scheduled + manual scan), same
  as the existing PAUSE gate. Cycle-engine cool-off is out of scope (see requirements Out-of-Scope, CO-DET-12).
- OQ3 (backtest source) → **D-confirmed**: sim has only scanner-equivalent entries; the
  backtest treats all sim trades as the (single) cool-off cohort source. Documented in CO-BT-14.

## 15. Residual notes for the Plan (R1 lows folded in)
- create_child_trade / open path: NO change required (closed_at-window grouping, D30).
- account_cooloff_state CHECK constraints + NO-ACTION FK + two-arg advisory classid (D29).
- BacktestCreateRequest must restate ge=1/le=43200 + extra="forbid" on the 8 fields (SR-F9);
  DB CHECKs on *_minutes as defense-in-depth (already in §8 DDL).
- Reconciler-flat + concurrent rule-close: covered by try-lock + monotonic high-water; add a
  regression test (BR-F7).
