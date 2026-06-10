# Backtest Engine Live-Fidelity Improvements + Replay Mode

**Date:** 2026-06-10
**Author:** basiltt (with Claude)
**Status:** Design — pending review
**Type:** Production engine changes (backtest) + new product feature
**Predecessor:** `2026-06-10-selective-backtest-parity-design.md` (the diagnostic that
located these issues; this spec acts on its findings)

---

## 1. Background

A diagnostic harness pinned account "Dad - Demo"'s 51 actual live trades (Jun 5–10)
and replayed them through `BacktestEngine`. It established that the engine's
**simulation** (fills, close rules, PnL, compounding) is faithful — 0.994 per-cycle
PnL correlation with live, 17/17 directional agreement, ~92% of live's compounded
equity (conservative). The residual ~8% was proven to be live's order-execution
latency (non-deterministic, must not be modeled).

That diagnostic was analysis-only — it changed **no production code**. This spec
implements the three production changes the diagnostic justified, in ascending risk
order:

1. **Drift-gate fidelity** (small) — the engine's price-drift gate rejects trades on
   a transient 5m bar-open spike that live's real-time mark never saw.
2. **Selection tiebreaker fidelity** (medium) — the engine breaks score-ties in a
   different order than live, so it picks a different subset of tied signals.
3. **Replay (validation) mode** (large) — expose the harness as a first-class
   backtest type so any account can be validated live-vs-backtest, anytime.

**Non-goal / explicitly out:** breakeven. The diagnostic initially flagged breakeven,
but reconciliation showed the engine's breakeven (`_evaluate_time_rules`) and live's
(`close_rule_evaluator._check_condition`) are **already correct and aligned** after
the Jun-10 watch-and-close-all fix (`639e0ec`, `c083b79`). The historical Jun 5–9
trades predate that fix, so they are not a valid breakeven oracle; no breakeven
change is made here.

---

## 2. Change 1 — Drift-gate uses 1m price when available (fidelity)

### Problem
Live (`auto_trade_service._try_trade`, ~line 1413) checks price drift against the
real-time exchange mark: `current_price = get_mark_price(account_id, symbol)`.
The engine (`backtest_engine._apply_filter_chain`, ~line 796) approximates this with
the **5m next-bar-open** (first candle with `open_time >= current_time`). On a
transient spike that single 5m point can drift past `max_price_drift_pct` while
live's continuous mark never did — so the engine rejects a trade live took.

Observed: BLESSUSDT, scan `2fb43553`. analysis_price 0.00855; 5m next-bar-open 0.009015
(+5.4% > 3% cap) → engine rejects. Live filled at 0.008754 (below analysis, no drift)
and traded it.

### Fix
When 1-minute drill-down candles exist for the signal's entry bar
(`self._fine_klines[ticker]`), evaluate drift against the **1m open at/just-after the
signal instant** — far closer to live's real-time mark — instead of the 5m
next-bar-open. Fall back to the existing 5m behaviour when no 1m window is present.

This is a pure tightening of an existing approximation: it only changes the price the
drift *check* reads, never the entry fill price (still next-bar-open) or any other
path. When `fine_klines` is absent (the default backtest), behaviour is byte-identical
— the golden suite stays green.

### Interface / boundary
- Touch only the drift block in `_apply_filter_chain`. Add a small helper
  `_drift_reference_price(ticker, current_time, klines)` that returns the 1m open at
  the signal instant when a fine window covers it, else the 5m next-bar-open.
- No new config field; no change to `max_price_drift_pct` semantics.

### Test
- New unit: a signal whose 5m next-bar-open trips the gate but whose 1m open at the
  signal instant does NOT → admitted when fine_klines present, rejected when absent.
- Golden suite (no fine_klines) unchanged.

---

## 3. Change 2 — Selection tiebreaker matches live exactly (fidelity)

### Problem
`score` is an integer, so a scan routinely has more eligible signals tied at the top
score than `max_trades` slots. Which tied signals get traded is decided by the
tiebreaker — and the two systems disagree:

- **Live** (`auto_trade_service.execute_batch`, line 580):
  `sorted(key=lambda r: (abs(r["score"]), r.get("completed_at","")), reverse=True)`.
- **Engine** (`backtest_engine._process_batch_signals`, line 464):
  `unique_signals.sort(key=lambda s: abs(s.get("score",0)), reverse=True)` — `abs(score)`
  only; ties fall back to whatever order the list happened to be in.

Evidence: scan `4711fe59` had 11 signals tied at |score|=7 for 3 slots; scan
`53b5b8fa` had 4 tied at |8| for 3. The tiebreaker alone decided which symbols traded.

The service's `_load_signals` already SELECTs `ar.completed_at AS analysis_completed_at`
(joining `analysis_runs`) and orders by it, but the engine's in-memory re-sort
discards that order.

### Fix
Make the engine's batch selection sort key
`(abs(score) DESC, analysis_completed_at DESC, id ASC)` — byte-identical to live's
`(abs(score), completed_at) DESC` with `id` as the final deterministic tiebreak.
The signal dicts already carry `analysis_completed_at` and `id` from `_load_signals`.

Apply the same key to the `fill_to_max_trades` relaxed pass (line 479) and the
immediate-mode fill (line 519) so every ranking site agrees.

### Boundary / risk
- This changes which signals a NORMAL (non-pinned) backtest selects from tied pools —
  intended, and the whole point. It WILL change golden snapshots that contain
  score-ties. **The golden snapshots must be regenerated and manually verified** as
  part of this change (a snapshot diff that only reorders tied-score entries is the
  expected, correct effect; any non-tie change is a red flag to investigate).
- `analysis_completed_at` may be NULL for legacy rows → sort NULLs last (matches the
  SQL `NULLS LAST`), so a missing value never jumps a signal ahead of a timestamped one.

### Test
- New unit: a scan with 4 signals tied at the same |score|, distinct
  `analysis_completed_at`; assert the engine enters the 3 with the LATEST
  completed_at (matching live's DESC), not the first-in-list 3.
- NULL `analysis_completed_at` sorts last.
- Regenerate + eyeball golden snapshots; confirm only tie-order changes.

---

## 4. Change 3 — Replay (validation) ScanSource mode (product feature)

### Goal
Expose the diagnostic harness as a first-class backtest type: pick an account + date
range, the backend pins that account's ACTUAL live trades, replays them through the
engine, and the results dashboard shows live-vs-backtest per cycle. This makes engine
fidelity continuously verifiable against any account — not a one-off script.

### Selection semantics (decided)
Replay mode **pins the account's actual traded symbols** (from
`scans.auto_trade_results` + `trades`) and bypasses the engine's re-selection. It is a
pure SIMULATION-validation tool: "given exactly what live traded, does our sim
reproduce the PnL?" This isolates simulation fidelity from selection (the mode that
achieved 0.994 correlation). It does NOT test selection — Change 2 covers that on the
normal path.

### Architecture
Reuse the proven harness units (`backend/diagnostics/parity/`) as the engine of the
mode rather than reimplementing:

- **Schema:** extend `ScanSource.mode` with `"replay"`; add `replay_account_id`
  + the existing `date_range_start/end`. Validation: `replay_account_id` required when
  `mode="replay"`.
- **Service:** in `BacktestService`, when `mode=="replay"`:
  1. Build the live-selection oracle (extractor) for the account+window.
  2. Pin signals to the live trades (shim) and load 5m klines + per-cycle 1m
     drill-down (data_access) — exactly the harness pipeline.
  3. Run per-cycle isolation (reporter.run_cycles_isolated) and persist the standard
     backtest result PLUS a per-cycle live-vs-backtest comparison.
- **Results payload:** the normal backtest result fields, plus a `replay_comparison`
  block: per-cycle `{scan_id, live_net_pnl, backtest_net_pnl, live_equity,
  backtest_equity, delta_pct}` and headline `final_equity_delta_pct`,
  `pnl_correlation`, `directional_agreement`.
- **UI:** the existing `BacktestResultsPage` gains a "Replay vs Live" section
  (rendered only when `replay_comparison` is present) — a per-cycle table + the
  headline fidelity stats. The config form gains a "Replay account" picker when the
  Replay source is chosen.

### Boundary / safety
- Replay is **read + simulate only** — it reads historical trades/scans/klines and
  runs the pure engine. It never places orders or writes live config. Same money-safety
  guarantees as a normal backtest.
- The harness code moves from `backend/diagnostics/parity/` into the service's reach
  (either imported from there or relocated under `backend/services/backtest/replay/`).
  Decide placement in the plan; keep the units small + independently tested.

### Reused vs new
- **Reused (already tested):** extractor, shim, reporter, data_access, models.
- **New:** ScanSource schema extension + validation; service `replay` branch +
  comparison persistence; results payload field; UI section + account picker;
  end-to-end test.

---

## 5. Implementation Order (risk-ascending)

1. **Change 1 (drift)** — smallest, golden-safe (no-op without fine_klines). Land first.
2. **Change 2 (tiebreaker)** — changes the hot selection path; requires golden
   regeneration + manual verification. Land second, in isolation, so the golden diff
   is attributable to ONLY this change.
3. **Change 3 (replay mode)** — largest; builds on the now-faithful engine. Land last.

Each change is its own commit (or small commit series) with the golden suite run
between them. Change 2 is the only one that legitimately alters golden snapshots;
1 and 3 must leave them untouched.

## 6. Testing Strategy

- **Per change:** failing-first unit tests as described in each section.
- **Golden master is the hard gate:**
  - Changes 1 & 3: `tests/backend/golden`, `test_golden_fingerprint`,
    `test_backtest_golden` must stay byte-identical.
  - Change 2: snapshots regenerated; the diff reviewed to confirm it ONLY reorders
    tied-score selections. Commit the regenerated snapshots with an explicit note.
- **Replay E2E:** a test that drives `mode="replay"` for the validation account over
  a small window and asserts the comparison block is populated and the headline
  correlation is high (sanity bound, e.g. > 0.9), guarding against regressions in the
  pinned pipeline.
- **Existing suites:** `test_backtest_engine`, `test_engine_advanced_rules`,
  `test_close_rule_evaluator*`, `test_backtest_schemas` all stay green.

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Tiebreaker change silently alters non-tie selections | Land it alone; review the full golden diff; assert only equal-|score| entries reorder. |
| `analysis_completed_at` NULL/missing for some scans | Sort NULLs last (matches SQL); unit-test the NULL case. |
| Drift 1m lookup introduces look-ahead | Use only the 1m candle AT/AFTER the signal instant within the entry bar (same no-look-ahead rule the engine already enforces); covered by a test. |
| Replay mode drifts from the harness as code evolves | Reuse the SAME units (don't fork); the harness unit tests become the mode's unit tests. |
| Replay UI shows misleading "FAIL" for the inherent ~8% | UI frames the headline as fidelity stats (correlation, directional agreement, % captured) with a "conservative by ~X%" note, not a pass/fail against an unrealistic ±1%. |
| Moving harness code breaks the standalone CLI | If relocating, keep a thin shim or update the CLI import; run the diagnostics tests after the move. |

## 8. Scope

**In:** the three changes above, their tests, golden regeneration for Change 2, the
replay results UI section + account picker.

**Out (YAGNI):** modeling live execution latency (proven non-deterministic);
re-selection comparison in replay mode (pinned only); breakeven changes (already
correct); tick-level exits in the product (the tick infra stays a diagnostics-only
tool); replay for AI-Manager-influenced accounts (the engine excludes the AI Manager —
replay is most meaningful for ai_manager_enabled=false accounts; surface a note when
the chosen account had it on).

