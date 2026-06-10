# Selective-Trade Backtest Parity — Diagnostic Harness & Engine Fixes

**Date:** 2026-06-10
**Author:** basiltt (with Claude)
**Status:** Design — approved, pending spec review
**Type:** Bug investigation + targeted engine fixes (one-off diagnostic harness)

---

## 1. Problem

The backtesting engine's output does not match the results produced by the live
demo trading accounts on Bybit. For a money-handling system, this gap makes the
backtester untrustworthy for evaluating configurations. The user requires the
backtest to reproduce live results to **~99% accuracy on final compounded equity**.

### 1.1 Root cause #1 — trade selection is unrecoverable from scan data (primary)

Live batch execution (`auto_trade_service.execute_batch`) ranks the scan's
candidate signals by:

```python
key=lambda r: (abs(r.get("score", 0)), r.get("completed_at", "")), reverse=True
```

then takes the top `max_trades` (3 for the validation account). Because `score`
is an **integer**, ties at the top are common. The tiebreaker is `completed_at`
— the wall-clock time each symbol's AI analysis finished.

The backtest engine (`backtest_engine._process_batch_signals`) re-selects from
`scan_results` and ranks by:

```python
unique_signals.sort(key=lambda s: abs(s.get("score", 0)), reverse=True)
```

`abs(score)` only — ties fall back to DB row order.

**`scan_results` does not persist `completed_at`** (columns: `id, scan_id,
ticker, run_id, status, direction, confidence, score, decision_summary,
signal_source, analysis_price`). The live tiebreaker value is therefore *gone* by
the time a backtest runs. When the tie pool exceeds `max_trades`, the two systems
pick a **different subset of symbols** → different entry prices, PnL, drawdown,
and (because capital compounds per cycle) a divergent equity curve for every
subsequent cycle.

This matches the user's report: "sometimes it randomly selects trades." It is
**not** fixable by changing the sort key — the discriminating information was
never stored.

#### Evidence (validation account, Jun 5–9)

| Scan (prefix) | Eligible pool | Live traded | Tiebreaker decided the set? |
|---------------|---------------|-------------|-----------------------------|
| `53b5b8fa` | 4 at \|score\|=8 | 3 of the 4 | **Yes** (4 tied for 3 slots) |
| `a6e5338d` | 3 at \|8\|, 14 at \|7\| | the 3 at \|8\| | No (clean top-3) |
| `4711fe59` | **11 at \|7\|** | 3 of 11 | **Yes** (pure tiebreaker) |
| `61152a82` | 2 at \|8\|, 9 at \|7\| | 2×\|8\| + 1×\|7\| | **Yes** (3rd slot) |

### 1.2 Root cause #2 — close-side modeling differences (secondary)

About 25% of the live closed trades carry `close_reason='external'` (closed by
the exchange/reconciler, with fees already netted into `net_pnl`), which the
engine models as rule-based closes computed from candles. In addition, the
breakeven close-rule fixes committed on 2026-06-09/10 (`7c66050`, `420b9b4`)
hardened the **live** `close_rule_evaluator` (fail-closed on zero-notional
books); the engine has its own breakeven implementation in
`_evaluate_time_rules`. These produce smaller per-trade drift on top of the
selection problem.

### 1.3 Key enabler — authoritative live-selection oracle exists

Two prod tables fully record what live actually did, so selection can be pinned
from ground truth (no tiebreaker reconstruction):

- **`scans.auto_trade_results`** (jsonb) — per scan, the exact
  `{symbol, side, status, order_id, account_id}` each account traded.
- **`trades`** — the realized fills: `entry_price`, `avg_fill_price`,
  `exit_price`, `close_reason`, `realized_pnl`, `net_pnl`, `fees`,
  `base_capital` (the compounding capital basis), `scan_result_id`,
  `opened_at`, `closed_at`.

---

## 2. Goal & Success Criteria

**Goal:** Demonstrate the engine reproduces live results to ~99% by removing the
unrecoverable selection variable, then fix the engine bugs the comparison exposes.

**Pass condition (primary):** Backtest final compounded equity within **±1%** of
the live account's actual final equity over the validation window.

**Definition of "live final equity" (unambiguous):** computed from the `trades`
oracle as the **last completed cycle's `base_capital` + that cycle's summed
`net_pnl`** (equivalently: first cycle's `base_capital` + Σ `net_pnl` over all
closed trades, since `base_capital` compounds prior cycles' realized PnL). The
backtest's comparable figure is its final wallet equity after the same cycles.

**Open-position handling:** the account has **one still-open live position**
(MEGAUSDT, opened 2026-06-09 16:20, no `closed_at`/`net_pnl`). It is **excluded**
from both sides of the comparison; parity is measured over the **51 closed
trades** only, ending at the last live close. The harness pins only cycles whose
trades are fully closed.

**Secondary diagnostics (reported, not gating):** per-cycle net-PnL deltas and
the side-by-side compounded curve, so residual drift is visible and attributable.

**Validation target:** account "Dad - Demo"
(`75aecaa7-0f10-400b-a562-1ddd7ae6cf94`), window **2026-06-05 → 2026-06-10**
(when its config was last updated). This account has `ai_manager_enabled: false`,
making it the correct parity target since the backtester excludes the AI Manager.

**Config under test (from the live `scheduled_scans.scan_config`):**
`leverage 10, capital_pct 20, max_trades 3, take_profit_pct 150,
stop_loss_pct 100, max_drawdown_pct 12 (smart_drawdown_close on),
trailing_profit_pct 2, breakeven_timeout_hours 12, max_trade_duration_hours 24,
min_score 7, confidence_filter moderate, signal_sides both, execution_mode batch,
fill_to_max_trades on, skip_if_positions_open on, adaptive_blacklist on,
target_goal_type profit_pct / value 15, max_price_drift_pct 3,
max_same_sector 2, max_same_direction 3`.
Starting capital: the first cycle's `base_capital` ≈ **200.43** (to be read
exactly from the earliest trade, not hard-coded).

---

## 3. Approach

A standalone **diagnostic harness** (script + tests) that replays the validation
account's *actual live selection* through the existing `BacktestEngine`, then
compares cycle-by-cycle against the live `trades` oracle. The harness is not a
product feature; the lasting changes are the **engine fixes** the comparison
drives out, each landed with a regression test.

### 3.1 Why a harness, not a new ScanSource mode

The existing `ScanSource` modes (`schedule`, `date_range`, `explicit`) all feed
*whole scans* to the engine, which then re-selects — reproducing the very bug we
are isolating. A new product mode would be larger scope than needed to find and
fix the engine gaps. (If parity proves valuable as a recurring capability, a
productized replay mode can be a follow-up; out of scope here.)

### 3.2 Data residency

Per decision, hydrate the **local** DB from prod first (via the `copy-prod-scans`
skill / equivalent SQL copy), then run the harness entirely against local data
and the local `BacktestEngine`. Prod is read-only throughout; nothing is written
back to prod.

---

## 4. Components

Each unit has one purpose, a defined interface, and is testable in isolation.

### 4.1 Data hydration
- **Does:** copies the validation account's scans, `scan_results`,
  `auto_trade_results`, `trades`, and the covering `kline_cache` candles from
  prod into local DB for the window.
- **Interface:** `(account_id, start, end) -> local rows present`.
- **Depends on:** prod DB (read), local DB (write), kline coverage check.
- **Guard:** verify every pinned trade's `[opened_at, closed_at]` window is
  covered by cached candles for its symbol; report any gap (a gap would silently
  under-fill and corrupt the comparison).

### 4.2 Live-selection extractor (the oracle)
- **Does:** builds, per scan (cycle), the pinned set of `(symbol, side)` the
  account actually traded, plus the per-cycle ground-truth: `base_capital`,
  each trade's `net_pnl`, `close_reason`, `entry_price`, `exit_price`.
- **Interface:** `(account_id, window) -> [Cycle{scan_id, signal_time,
  pinned:[(symbol, side)], live_trades:[...], base_capital}]`.
- **Source:** `scans.auto_trade_results` filtered to `account_id`, cross-checked
  against `trades.scan_result_id` for integrity (both must agree on the set).
- **Depends on:** local DB only.

### 4.3 Selection shim
- **Does:** restricts each scan's `scan_results` signal list to the pinned
  `(ticker, side)` set before the engine's dedup/rank/filter runs, so the engine
  opens exactly the live symbols — but still simulates fills, close-rule
  evaluation, exit prices, PnL, and compounding from candles.
- **Interface:** `(scan_signals, pinned_set) -> filtered_signals`.
- **Design note:** implemented as input filtering / a thin engine seam, NOT by
  forking the engine's simulation logic. The engine's price/close/compound math
  must remain the code under test. The shim only controls *which* signals enter.
- **Depends on:** engine input contract (signal dicts keyed by `ticker`,
  `direction`/side, `score`, `signal_time`).

### 4.4 Parity reporter
- **Does:** runs the engine over the pinned cycles and emits a comparison table:
  per cycle -> live net PnL vs backtest net PnL, live `base_capital` vs backtest
  cycle-start equity, running compounded equity for both, and per-cycle delta %.
  Headline line: final-equity delta %. Flags any cycle with > 1% drift.
- **Interface:** `(live_cycles, engine_result) -> report + pass/fail`.
- **Depends on:** extractor output + engine output.

### 4.5 Engine fixes (the durable deliverable)
- **Does:** for each gap the reporter surfaces, a root-cause fix in the engine
  (or a documented modeling caveat where reality is unreproducible), landed TDD:
  failing test first, then fix, then green + golden-parity suite still passing.
- **Interface:** standard engine code + `tests/backend/` regression tests.
- **Depends on:** `backtest_engine.py`, `backtest_metrics.py`, possibly
  `close_rule_evaluator.py` for breakeven-netting parity.

---

## 5. Data Flow

```
prod DB --(copy-prod-scans, read-only)--> local DB
                                             |
        +------------------------------------+----------------------+
        v                                    v                      v
 scans.auto_trade_results            scan_results              kline_cache
 + trades  (oracle)                  (signal pool)             (candles)
        |                                    |                      |
        +--> live-selection extractor        |                      |
                    |  pinned (symbol,side)   |                      |
                    +--------> selection shim -+                     |
                                     | filtered signals             |
                                     +--------> BacktestEngine <-----+
                                                     | per-cycle sim results
                          live trades --> parity reporter --> final-equity delta % + pass/fail
```

---

## 6. Investigation Plan (systematic-debugging Phases 3-4)

The harness is the instrument; fixes are hypothesis-driven, one variable at a
time. Anticipated gaps to test (in priority order):

1. **Selection pinned -> measure residual.** With selection removed as a
   variable, re-run and record the remaining final-equity delta. This isolates
   how much error was selection (expected: large) vs. engine (expected: small).
2. **`external` closes (~25% of trades).** Decide per-trade handling: let the
   engine close them via its own rules (max_duration/breakeven/drawdown) and
   measure, vs. pin their exit from live as a documented exception. Quantify
   their contribution to residual drift; do not hide it.
3. **Breakeven netting parity.** Compare the engine's `_evaluate_time_rules`
   breakeven mass-close against the live evaluator's post-fix semantics
   (fail-closed zero-notional, fee-buffer = sum(notional) x rate x 1.5).
4. **Entry-fill basis.** Verify the engine's next-bar-open fill + slippage vs
   live `avg_fill_price`; confirm `base_capital`/compounding basis matches the
   account-available-balance basis live uses.
5. **Per-cycle close timing.** Confirm account-level cycle close (all cycle
   positions close together) is modeled, matching the live `closed_at` clustering.

Each confirmed gap -> failing test -> minimal root-cause fix -> re-run reporter.
Stop when final-equity delta <= 1% and no new gap appears on re-run.

---

## 7. Scope

**In scope**
- Diagnostic harness (script) + its unit tests.
- Local hydration of validation data via copy-prod-scans.
- Engine fixes with regression tests for every confirmed gap.
- A short findings note appended to this spec (residual breakdown).

**Out of scope (YAGNI)**
- A productized replay/selective `ScanSource` mode, any UI, or API surface.
- AI-Manager-enabled accounts (validation account has it off).
- Other accounts / windows (method generalizes; validation is Dad-Demo Jun 5-10).
- Re-deriving the live `completed_at` tiebreaker (unrecoverable by design;
  pinning sidesteps it).

---

## 8. Testing Strategy

- **Harness units:** extractor (pinned set matches `trades`), shim (engine opens
  exactly the pinned symbols), reporter (delta math correct on a fixture).
- **Engine fixes:** each fix ships a failing-first regression test reproducing the
  per-cycle divergence it addresses.
- **No regressions:** the existing golden-master parity suite
  (`tests/backend/golden/`, `test_golden_fingerprint.py`,
  `test_backtest_golden.py`) must stay green — fixes must not break byte-identical
  guarantees for the default path.
- **Acceptance:** harness reports final-equity delta <= 1% vs live; secondary
  per-cycle table attached to the findings note.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `external` closes are inherently unreproducible from candles | Quantify their share of residual; document as a bounded caveat; final-equity tolerance absorbs small per-trade noise. |
| Kline coverage gaps in local cache | Explicit coverage check in hydration; warm/copy missing candles before running; fail loudly, never silently under-fill. |
| A fix improves Dad-Demo but breaks the golden suite | Golden suite is a hard gate for every fix; investigate any divergence before landing. |
| Engine seam for the shim leaks into production code paths | Shim is test/harness-only input filtering; no change to the default selection path; golden suite proves the default path is untouched. |
| Residual never reaches 1% due to compounding amplifying tiny early drift | Report per-cycle so the earliest material drift is fixed first; compounding makes early-cycle parity the priority. |

---

## 10. Findings (to be appended after the harness runs)

_Residual breakdown, per-cycle table, and the list of engine fixes landed will be
recorded here once the investigation completes._
