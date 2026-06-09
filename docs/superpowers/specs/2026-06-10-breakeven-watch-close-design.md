# Breakeven Watch-and-Close-All — Design

**Date:** 2026-06-10
**Status:** Approved (pending spec review)
**Area:** Close-rule subsystem (live `close_rule_evaluator.py` + `backtest_engine.py`)

## Problem

The `BREAKEVEN_TIMEOUT` close rule is a **one-shot**: when
`breakeven_timeout_hours` elapses, it fires once, sets each open position's
take-profit to that position's own breakeven price (~1% leveraged PnL to cover
fees), and transitions the rule to `executed`. It never watches again. If price
does not subsequently touch that TP, nothing closes until the separate
`MAX_DURATION` (force-close) rule fires.

The desired behavior is a **windowed, account-level watch**: once the breakeven
*time* has passed, the system should keep watching, and **any time** afterward
that the account returns to breakeven (total open unrealised PnL recovers to ~flat
after fees), it should **close all positions** in the account. The force-close
(`max_trade_duration_hours`) remains the hard stop that closes everything
regardless.

This applies to both live trading (`close_rule_evaluator.py`) and the backtest
engine (`backtest_engine.py`), keeping the documented <1% live/backtest deviation.

## Current Behavior (baseline)

- **Rule creation** (`auto_trade_service.py` ~L453 and ~L945, the recheck path):
  - `BREAKEVEN_TIMEOUT`: `threshold_value = breakeven_timeout_hours`,
    `reference_value = now()` (cycle start).
  - `MAX_DURATION`: `threshold_value = max_trade_duration_hours`,
    `reference_value = now()`.
  - Both are **account-level** rules (no `symbol`).
- **Live evaluation** (`close_rule_evaluator.py`):
  - `_TIME_TRIGGERS = {BREAKEVEN_TIMEOUT, MAX_DURATION}` evaluated via
    `_check_time_elapsed` (elapsed ≥ threshold hours).
  - `BREAKEVEN_TIMEOUT` is in `_NON_EQUITY_TRIGGERS` → excluded from the
    equity-debounce sweep; evaluated on the poll path.
  - On fire, `BREAKEVEN_TIMEOUT` takes a **special branch** (L293–310):
    `_handle_breakeven_timeout` sets each position's TP to breakeven, then
    `status="executed"`. A "skip if actively trailing" courtesy resets the rule
    to `active`.
  - `MAX_DURATION` on fire falls through to the generic `close_all_for_rule`
    (closes all, deactivates siblings) — already correct.
- **Backtest** (`backtest_engine._evaluate_time_rules`, ~L1869):
  - `MAX_DURATION`: force-close each position at latest price (closes all).
  - `BREAKEVEN_TIMEOUT`: per-position `pos.tp_price = compute_breakeven_price(...)`
    (does NOT close); skipped if `pos.trailing_active`.

## Decisions (from brainstorming)

1. **Breakeven reference:** account-level — watch total **open unrealised PnL**,
   not per-position entry prices. One all-or-nothing close.
2. **Threshold:** total open uPnL ≥ a **fee buffer** (so the mass close nets ~flat
   after taker fees, not a small loss).
3. **Fee buffer formula:** `Σ (qty × mark_price × taker_rate/100) × 1.5` over open
   positions, where `taker_rate` = the config `fee_rate_pct` (default 0.055%). The
   `×1.5` cushions slippage on the market close-all.
4. **Old TP-set action:** **removed** — fully replaced by the watch. No per-position
   TP nudge at breakeven time anymore.
5. **Scope:** both live and backtest.

## Live Implementation (`close_rule_evaluator.py`)

### Trigger classification

- Keep `BREAKEVEN_TIMEOUT` in `_TIME_TRIGGERS` (time still gates it).
- **Remove** `BREAKEVEN_TIMEOUT` from `_NON_EQUITY_TRIGGERS` so it participates in
  the equity sweep path — it now needs live PnL (`totalPerpUPL`), which that path
  already fetches and passes as `pnl`. (It stays out of `_DRAWDOWN_TRIGGERS` and
  `_ZERO_EQUITY_TRIGGERS`.)
- Keep it out of `_POLL_EXCLUDED_TRIGGERS` (poll fallback still evaluates it).

### Condition (`_check_condition`)

Replace the `_TIME_TRIGGERS → _check_time_elapsed` shortcut for the breakeven case
with a compound check:

```
if trigger_type == "MAX_DURATION":
    return self._check_time_elapsed(rule)            # unchanged

if trigger_type == "BREAKEVEN_TIMEOUT":
    if not self._check_time_elapsed(rule):           # still before breakeven time
        return False
    # past breakeven time → watch account-level open PnL vs fee buffer
    buffer = self._breakeven_fee_buffer(positions)   # Σ qty·mark·rate·1.5
    return pnl >= buffer
```

`_check_condition` currently takes `(rule, equity, pnl, balance)`. It needs the
account's open **positions** to size the buffer. Two options:

- **Chosen:** compute the buffer in the *caller*
  (`_evaluate_account_rules_with_data`) — it already has `account_id` and can fetch
  positions once, then pass a precomputed `breakeven_buffer: Optional[Decimal]` into
  `_check_condition`. Avoids a fetch inside the pure condition function and avoids
  re-fetching per rule. Positions are fetched only when a `BREAKEVEN_TIMEOUT` rule
  is present AND past its time (lazy), so non-breakeven accounts pay nothing.

`taker_rate` source: live wallet/positions don't carry a config `fee_rate_pct`, so
use a module constant `BREAKEVEN_TAKER_RATE_PCT = 0.055` (Bybit USDT-perp taker) ×
`BREAKEVEN_FEE_SLIPPAGE_MULT = 1.5`. Documented as a conservative fixed estimate;
exact realized fees vary by VIP tier but the buffer only needs to clear typical
round-trip cost.

### Firing path

When the compound condition is True:

- Remove the special `BREAKEVEN_TIMEOUT` branch (current L293–310) including
  `_handle_breakeven_timeout` and the "skip if trailing" reset.
- Let `BREAKEVEN_TIMEOUT` flow through the **same generic close path** as
  `MAX_DURATION`: `atomic_trigger_rule` → `close_all_for_rule(account_id, rule_id)`
  → on success `status="executed"` + `deactivate_rules_for_account(exclude=self)` +
  `break`. This closes ALL positions and tears down siblings (incl. the now-moot
  `MAX_DURATION`), exactly like force-close.

`_handle_breakeven_timeout` and `compute_breakeven_price`'s live caller become dead
code and are deleted (keep `compute_breakeven_price` itself — still used by
backtest until that path changes; after this change verify no live caller remains).

### Mark price for the buffer

Buffer needs each position's `mark_price × qty` (notional). Positions from
`accounts_service.get_positions` carry `markPrice`/`size`/`positionValue`. Prefer
`positionValue` when present (exchange-computed notional); else `size × markPrice`.
Fee = `notional × 0.055/100 × 1.5`, summed across positions.

## Backtest Implementation (`backtest_engine.py`)

In `_evaluate_time_rules`, replace the per-position breakeven TP block:

```
# BREAKEVEN_TIMEOUT: account-level watch after breakeven time
if breakeven_hours and not breakeven_closed_this_eval:
    past_time = any(elapsed(pos) >= breakeven_hours for pos in open_positions)
    if past_time:
        total_upnl = Σ compute_unrealized_pnl(ref, mark, qty, side)
        buffer     = Σ (qty × mark × fee_rate/100) × 1.5
        if total_upnl >= buffer:
            mark ALL open positions to close, reason "breakeven"
```

Notes:

- "past breakeven time" is account-level: the rule is created at cycle start, so use
  the **oldest** open position's elapsed time (equivalently `candle_time −
  cycle_start`). Simplest faithful proxy: `max(elapsed over open positions) ≥
  breakeven_hours`. (All positions opened in the same scan share ~the same entry
  time; using the max is the conservative, correct "the cycle has aged past
  breakeven" test.)
- `fee_rate` = `config.get("fee_rate_pct", 0.055)` (already in scope in this method's
  caller chain).
- MAX_DURATION (force-close) block stays first/unchanged — if a position is already
  past max_duration it force-closes regardless of breakeven PnL.
- Reason string `"breakeven"` for the closed trades (new close reason; verify it’s
  accepted by metrics/trade serialization, else reuse an existing reason label).

## Edge Cases

1. **No open positions when breakeven fires:** live `close_all_for_rule` closes
   nothing; mark rule `executed` (nothing to watch). Backtest: empty open set → no-op.
2. **Equity/PnL unreadable:** live path already skips on missing/zero equity
   (`totalEquity` guard) — breakeven simply isn't evaluated that tick; retried next
   tick. No mass close on a bad frame.
3. **Both breakeven & force-close eligible same tick:** force-close (MAX_DURATION)
   and breakeven both close ALL; whichever the loop hits first closes everything and
   `break`s. Equivalent outcome. Backtest evaluates MAX_DURATION first (force wins).
4. **Negative buffer impossible:** buffer ≥ 0 always (notional ≥ 0). If all positions
   somehow have 0 notional, buffer = 0 → closes when uPnL ≥ 0.
5. **Actively trailing symbol:** the old per-symbol "skip if trailing" no longer
   applies (account-level rule). Trailing-profit rules still run independently and may
   close their own symbol earlier; breakeven closes whatever remains once account uPnL
   clears the buffer. Accepted.
6. **Config validation:** `breakeven_timeout_hours < max_trade_duration_hours` is
   already enforced (`backtest_schemas.py` L180). Unchanged.

## Testing

### Live (`tests/backend/test_engine_close_rules.py` / close-evaluator unit tests)

- Before breakeven time: rule does NOT fire even if uPnL ≥ buffer (time gates it).
- After breakeven time, uPnL < buffer: does NOT close (still underwater).
- After breakeven time, uPnL ≥ buffer: closes ALL via `close_all_for_rule`, rule
  `executed`, siblings deactivated.
- After breakeven time, uPnL exactly at buffer boundary: closes (≥).
- No positions at fire: rule `executed`, no close attempted/no crash.
- Force-close (MAX_DURATION) still closes all at its time regardless of breakeven.
- Buffer math: Σ notional × 0.055% × 1.5 for a known book.

### Backtest (`tests/backend/test_engine_close_rules.py` or engine time-rule tests)

- Position recovers to ≥ buffer after breakeven time → closed with reason
  `breakeven` at that candle; not before breakeven time.
- Never recovers → force-closed at max_duration (existing behavior preserved).
- Parity: a scenario run through both engines yields the same close decision
  (within the existing tolerance).

### Regression

- Existing MAX_DURATION / time-rule / trailing tests stay green.
- No live caller of `_handle_breakeven_timeout` remains (grep).

## Out of Scope

- No UI copy change in this work item (the "Move to breakeven after" helper text in
  `AutoTradeSection.tsx` now describes watch-and-close rather than TP-set; flagged as
  a follow-up copy tweak, not blocking).
- No change to `MAX_DURATION`, trailing, drawdown, or profit rules.
- The pre-existing raw-dict config-validation gap (separate issue) is untouched.
