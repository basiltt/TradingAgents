# 1-Minute Portfolio-Equity Evaluation — Design & Progress

**Created:** 2026-06-08
**Goal:** Make portfolio-equity close rules (EQUITY_DROP_PCT, _SMART, EQUITY_RISE_PCT,
close_on_profit) fire at the correct *minute* during a holding period instead of
snapping to the 5m bar boundary — removing the `skip_if_positions_open` cascade
divergence found in multi-config fidelity (75aecaa7: 9 bt vs 15 prod).

This is NOT the full `/new-feature` pipeline (user opted out). Lean TDD + harness
validation. Golden guarantee and sweep immunity are preserved.

---

## Root cause (CONFIRMED by diagnostics, not assumed)

`.tmp_fidelity/diag_phantom_wick.py` + `diag_cascade_trace.py` proved:

1. **Drawdown stamped early.** The 5m engine fires `equity_drop_smart` at the bar
   OPEN (22:10) but values each position at that bar's *adverse extreme* (a ~22:14
   price). The true 1-minute simultaneous equity path doesn't cross the −12% threshold
   until **22:13** — which is *exactly* when production closed ENA/FIGHT/CRCL. The
   breach is REAL (verdict: "WOULD STILL FIRE"), just mis-stamped ~3–4 min early.

2. **Synchronized-wick risk.** The 5m drawdown sums each position's OWN-bar adverse
   extreme, implicitly assuming all positions hit their worst at the same instant.
   At 1m those extremes fall on different minutes, so the true simultaneous equity is
   shallower. Production (live ticks) only sees the simultaneous path. The 5m
   synchronized-worst can therefore fire on a drawdown that never simultaneously
   happened (a phantom). [Not observed firing falsely in 75aecaa7, but structurally
   possible and the 1m walk removes it.]

3. **Cascade.** A mass-close mis-stamped early/late flips which positions are open at
   the next scan boundary → `skip_if_positions_open` skips (or admits) a scan it
   shouldn't → trade count diverges (the 6 "missing" trades).

NOTE: the apparent "2-hour offset" in the cascade trace was **timezone** (prod
`opened_at` is +02; backtest is UTC). Scans ARE aligned. No scan-anchor bug.

---

## Design — "1m portfolio-equity walk", gated, fail-soft

The engine already iterates a unified 5m timeline in `_evaluate_candles_until` and
calls `_evaluate_equity_rules(...)` per bar. The change:

**When a 5m bar's `_evaluate_equity_rules` WOULD fire a portfolio rule AND full-book
1m windows exist for that bar AND the bar is within the holding window, replace that
one 5m evaluation with a minute-by-minute walk** over the bar's 1m candles:
- At each minute, mark every open position at that minute's 1m close (and, for the
  drawdown adverse test, that minute's 1m high/low) and recompute *simultaneous*
  account equity.
- Fire the portfolio rule at the FIRST minute it truly crosses; close at that minute's
  timestamp and that minute's price.
- If NO minute crosses → no close this bar (phantom rejected).

### Gating (preserves golden + sweep immunity)
- Branches solely on PRESENCE of 1m windows in `self._fine_klines` for ALL open
  symbols on this bar — never on a config flag. No fine data ⇒ today's 5m path,
  byte-identical (golden).
- Optimizer/sweep calls `engine.run()` with no `fine_klines` ⇒ structurally immune.
- **Full-book requirement:** the walk needs EVERY open symbol's 1m window for this bar
  (equity is a sum across the book). If ANY open symbol lacks a 1m window for this bar
  → fall back to the 5m evaluation for this bar (fail-soft, never wrong, never crash).

### Correctness invariant (why the 5m gate is safe)
For a drawdown, 5m sums each position's own-bar adverse extreme:
`5m_worst = Σ_i uPnL(adverse_i)` ≤ `min_minute Σ_i uPnL(price_i,minute)` = worst true
simultaneous equity. So **5m-no-breach ⟹ 1m-no-breach** → using the existing 5m
evaluation as the gate can never MISS a real 1m breach; the walk only ever refines a
breach the 5m run already flagged (timing) or cancels a phantom (suppression).

### Selection-invariance interaction
The existing entry-drill invariance (equity rules use `equity_ref_entry`, the stable
5m fill) is UNCHANGED — the walk still values uPnL off `equity_ref_entry`. The walk
changes WHEN/WHETHER a portfolio rule fires based on real 1m *market* prices (which
are config-independent), not based on the drilled entry. So toggling entry-drill still
can't move the cascade; the walk moves it toward PRODUCTION using market data only.

---

## Service side: full-book 1m coverage for holding windows

`_build_fine_klines` currently fetches only entry+exit bars (±1) per trade. The walk
needs 1m for **every 5m bar a portfolio rule could fire on while the book is open**.
Approach: for each Phase-A trade that closed via a portfolio rule (equity_drop/_smart/
rise/close_on_profit), fetch 1m for that trade's exit bar AND the concurrent bars of
every OTHER position open at that time. Simplest correct superset: fetch 1m for the
union of [each portfolio-close trade's exit bar] across ALL symbols open in that bar.
Bounded by trade count; still only the bars that matter. Fail-soft per the gate.

(Refine during implementation: may be cheaper to fetch the holding-window bars only
for scans that actually had a portfolio close in Phase A.)

---

## TDD plan (tests first)

Engine (`tests/backend/test_backtest_engine.py`, new class `TestPortfolioEquityOneMinuteWalk`):
1. `test_drawdown_fires_at_true_one_minute_crossing_not_bar_open` — multi-symbol short
   book; 5m bar adverse flags a breach at bar open, but 1m path crosses at minute 3 →
   close stamped at minute-3 timestamp & price.
2. `test_phantom_synchronized_wick_does_not_fire` — two shorts whose 1m adverse
   extremes are on DIFFERENT minutes so simultaneous equity never crosses, but the 5m
   own-bar-worst sum DOES → 5m would fire, 1m walk must NOT close.
3. `test_equity_rise_fires_at_true_one_minute_crossing` — rise rule refined to the
   minute it truly crosses (currently close-only at 5m).
4. `test_partial_book_coverage_falls_back_to_5m` — one open symbol lacks a 1m window →
   bar uses 5m evaluation unchanged.
5. `test_no_fine_data_byte_identical` — golden: walk never engages without 1m data.
6. `test_walk_respects_end_time_bound` — never evaluates past the next scan boundary.

Golden (`test_backtest_golden.py`): extend `TestDrilldownByteIdentical` to assert a
multi-symbol equity-rule run is byte-identical with `fine_klines=None`.

Service (`test_backtest_service.py`): `_build_fine_klines` now also returns windows for
portfolio-close holding bars (assert the extra bars are requested for a synthetic
Phase-A trade set).

Sweep immunity (`tests/backend/mcp/test_run_one_adapter.py`): unchanged — still asserts
run_one passes no fine data.

---

## Progress

| # | Activity | Status |
|---|----------|--------|
| 1 | Root-cause via diagnostics | DONE (phantom_wick + cascade_trace + rise + trailing + entry_fill) |
| 2 | Design (this doc) | DONE |
| 3 | Read existing tests | DONE |
| 4 | Write failing tests | DONE (6 engine + 1 service; RED confirmed) |
| 5 | Implement engine walk + service fetch | DONE |
| 6 | Full suite green (golden + invariance reconciled) | DONE (89 backtest tests) |
| 7 | 5-config harness: timing improved, no count regression | DONE |

## Outcome (measured on real production data)

Scope landed: refine the close MINUTE + PRICE of portfolio-equity rules to the true
1-minute crossing. NOT a count fix (counts are entry-fill-ceiling-bound — verified).

5-config harness, before → after the walk:
- exit ≤1%: **61/83 → 70/83** (+9)
- pnl(spot) ≤0.3: **22/83 → 28/83** (+6)
- counts / side / entry: **unchanged** (no regression; entry-fill ceiling untouched)

Decisive per-event proof (account 5d40b78e, ENA/FIGHT/CRCL `equity_drop_smart`):
- before: stamped **22:10** @ 0.0918 (≈3 min early, 2.1% price gap)
- after:  stamped **22:12** @ 0.0891 — production closed **22:13:16 UTC** @ 0.0899
- → backtest now lands within ~1 minute / ~1% of production's live reconcile tick
  (the fidelity floor: production evaluates equity on a ~30–60s cadence).

## Diagnostic chain (why the scope is exactly this, no more)

1. Portfolio drawdown closes are REAL but stamped ~3 min early (5m bar-open + own-bar
   adverse extreme = effective look-ahead). → FIXED by the 1m walk.
2. 5m synchronized-wick can fabricate a phantom drawdown (each leg's worst on a
   different minute). → REMOVED by the 1m walk (true simultaneous path).
3. 75aecaa7 9-vs-15 count gap is driven by BEAT's trailing arming early, which is
   ENTRY-FILL-sensitive (bt entry 2.540 vs prod 2.572), NOT close-timing. The 1m walk
   correctly does not change it.
4. Entry-fill convention is already unbiased (+0.01% signed bias across 83 trades) and
   near-optimal vs 4 alternatives — the residual per-trade gap is the irreducible
   candle-vs-tick floor. NOT a correctable bias.

## Files changed
- `backend/services/backtest_engine.py`: `_evaluate_equity_rules` split into a
  dispatcher + `_evaluate_equity_rules_fine` (1m walk) + `_eval_equity_core` (the
  unchanged 5m kernel, reused per-minute) + `_full_book_fine_window` gate.
- `backend/services/backtest_service.py`: `_build_fine_klines` adds full-book 1m
  coverage for the firing bar of every portfolio-equity close.
- `tests/backend/test_backtest_engine.py`: `TestPortfolioEquityOneMinuteWalk` (6).
- `tests/backend/test_backtest_service.py`: full-book coverage test (1).
