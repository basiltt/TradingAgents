# Backtest Engine Fidelity + Replay Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production backtest engine select and price trades closer to live (drift-gate uses 1m price; tie-breaking matches live's order), and add a first-class `replay` backtest mode that validates the engine against an account's actual live trades.

**Architecture:** Three risk-ordered changes to `backend/services/backtest_engine.py` and the backtest service/schemas/UI. Changes 1 & 3 are golden-safe (byte-identical default path). Change 2 deliberately alters tie-ordering and requires golden-snapshot regeneration. Replay reuses the already-tested harness units in `backend/diagnostics/parity/`.

**Tech Stack:** Python 3.12, asyncio, asyncpg, pytest; React + TypeScript (Vite, TanStack Query) for the replay UI.

---

## Reference Facts (verified against the code, 2026-06-10)

- **Engine entry:** `BacktestEngine.run(config, signals, klines, cancel_event=None, on_progress=None, instrument_info=None, scan_contexts=None, fine_klines=None)`.
- **Engine signal dict keys** (from `BacktestService._load_signals`): `id, ticker, direction, confidence, score, signal_time, analysis_completed_at, scan_id, signal_source, analysis_price`. So `analysis_completed_at` and `id` are ALREADY present on every signal dict — Change 2 just needs to use them in the sort.
- **Live tiebreaker** (`auto_trade_service.execute_batch:580`): `sorted(key=lambda r: (abs(r.get("score",0)), r.get("completed_at","")), reverse=True)`.
- **Engine batch sort sites** (all `abs(score)`-only today): `_process_batch_signals:464` (strict), `:479` (fill_to_max relaxed), `_process_immediate_signals:519` (immediate fill).
- **Engine drift block:** `_apply_filter_chain` lines 788–809. Reads `current_price` = first 5m candle with `open_time >= current_time` (the next-bar-open).
- **1m drill-down access:** `self._fine_klines: {symbol: {bar_open_epoch_int: [1m candles asc]}}`; helper `_fine_window(symbol, bar_open_time)` returns the 1m list for the 5m bar opening at `bar_open_time`, or None. `_fine_klines` is `{}` in a default backtest (golden path) → any 1m branch is skipped.
- **`fine_klines` is built only in Phase B** of `_execute_backtest` (service line ~833) for entry/exit bars of Phase-A trades; the drift check runs during Phase A (no fine_klines) AND Phase B (fine_klines present). The drift fix only changes behaviour in Phase B, on bars that have a 1m window.
- **ScanSource schema:** `backend/schemas/backtest_schemas.py:12` — `mode: Literal["schedule","date_range","explicit"]` + `schedule_id`, `scan_ids`, with a `validate_mode_fields` model-validator.
- **Service dispatch:** `_execute_backtest` (line 675) does `_load_signals(scan_source, date_range)` → warm → `_load_klines` → `_build_scan_contexts` → two-phase `engine.run` → `_persist_results`.
- **Harness units (reuse for replay):** `backend/diagnostics/parity/` — `extractor.build_cycles/live_final_equity`, `shim.pin_signals`, `reporter.run_cycles_isolated/build_report`, `data_access.ParityDataAccess` (+ `build_fine_klines`), `models`.
- **Validation account (replay E2E):** `Dad - Demo` = `75aecaa7-0f10-400b-a562-1ddd7ae6cf94`, window `2026-06-04T22:00:00Z`..`2026-06-10T06:00:00Z`, 51 closed trades, 17 cycles, expected delta ≈ -8%, correlation ≈ 0.994.
- **Golden suite (the hard gate):** `tests/backend/golden/`, `tests/backend/test_golden_fingerprint.py`, `tests/backend/test_backtest_golden.py`. Snapshot generator: see `tests/backend/golden/__init__.py`.

## File Structure

**Change 1 (drift):**
- Modify: `backend/services/backtest_engine.py` — drift block in `_apply_filter_chain` + new helper `_drift_reference_price`.
- Test: `tests/backend/test_engine_drift_1m.py` (new).

**Change 2 (tiebreaker):**
- Modify: `backend/services/backtest_engine.py` — the 3 sort sites (`:464`, `:479`, `:519`) via a shared `_rank_key` helper.
- Test: `tests/backend/test_engine_tiebreaker.py` (new).
- Regenerate: `tests/backend/golden/snapshots/*.json` (only tie-affected ones).

**Change 3 (replay mode):**
- Modify: `backend/schemas/backtest_schemas.py` — `ScanSource` gains `"replay"` + `replay_account_id`.
- Modify: `backend/services/backtest_service.py` — `replay` branch in `_execute_backtest` (inside the `try`); nest comparison into the existing `summary` JSONB in `_persist_results`; surface it in `_build_results`.
- Create: `backend/services/backtest/__init__.py`, `backend/services/backtest/replay_runner.py` — thin orchestrator over the harness units.
- Frontend (verified): `types.ts` (ScanSource mode union + `BacktestResults.replay_comparison`), `configSchema.ts` (zod enum + refine — **easy to miss**), `BacktestConfigForm.tsx` (option + picker + `accounts` prop), `BacktestNewForm.tsx` (parent fetches accounts via `accountsApi.getDashboard()`), `BacktestResultsPage.tsx` (replay card at `run.results.replay_comparison`).
- Test: `tests/backend/test_replay_mode.py` (schema + runner unit), `tests/backend/test_replay_e2e.py` (DB-gated, skipped without `PARITY_DB_SMOKE`).

---

## Task 1: Drift gate reads 1m price when a drill-down window exists

**Files:**
- Modify: `backend/services/backtest_engine.py` (drift block ~788–809; add `_drift_reference_price` helper near `_fine_window` ~813)
- Test: `tests/backend/test_engine_drift_1m.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_engine_drift_1m.py
from datetime import datetime, timezone
from backend.services.backtest_engine import BacktestEngine

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _signal(ticker, direction, score, analysis_price, t):
    return {"ticker": ticker, "direction": direction, "score": score,
            "analysis_price": analysis_price, "signal_time": t, "scan_id": "s1",
            "id": 1, "confidence": "high", "analysis_completed_at": None}

def _5m(t, o): return {"open_time": t, "open": o, "high": o, "low": o, "close": o, "volume": 1.0}
def _1m(t, o): return {"open_time": t, "open": o, "high": o, "low": o, "close": o, "volume": 1.0}

def test_drift_uses_5m_open_when_no_fine_window():
    """Sell, analysis 0.00855; 5m next-bar-open 0.009015 = +5.4% (price rose, move
    NOT consumed for a sell, so admitted). Establishes the 5m baseline path."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    eng._fine_klines = {}                      # NO drilldown
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # bar-aligned to a 1m boundary
    sig = _signal("BLESSUSDT", "sell", -7, 0.00855, t)
    # Entry-bar 5m candle (00:05) so _drift_reference_price can resolve bar_open;
    # next-bar-open (00:10) is the 5m reference price the gate reads.
    klines = {"BLESSUSDT": [_5m(_dt("2026-06-08T00:05:00"), 0.00860),
                            _5m(_dt("2026-06-08T00:10:00"), 0.009015)]}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    # A sell with price UP is admitted by the gate (drift_pct +5.4% is not < -3)
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is True

def test_drift_uses_1m_open_when_fine_window_present():
    """A BUY whose 5m next-bar-open trips the cap (+5.4% > 3) yet whose 1m open AT the
    signal instant (+1.0%) does NOT. With a fine window the 1m price is used → admitted.

    NOTE: `_drift_reference_price` returns the 1m candle with open_time >= current_time,
    so the signal instant MUST be a 1m boundary (00:08:00) for the 101.0 candle (its
    open_time == current_time) to be the one selected."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # 1m-aligned signal instant
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")       # the 5m bar covering 00:08:00
    # Entry-bar 5m candle (so bar_open resolves) + next-bar-open at +5.4%.
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:05:00"), 100.0),
                          _5m(_dt("2026-06-08T00:10:00"), 105.4)]}
    # 1m window for the entry bar: the 00:08:00 candle (== current_time) opens at 101.0.
    eng._fine_klines = {"FOOUSDT": {int(bar_open.timestamp()): [
        _1m(_dt("2026-06-08T00:05:00"), 100.5),
        _1m(_dt("2026-06-08T00:08:00"), 101.0),   # open_time == current_time → selected
        _1m(_dt("2026-06-08T00:09:00"), 101.2),
    ]}}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    # 5m path would REJECT (+5.4% > 3); 1m path ADMITS (+1.0% <= 3)
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is True

def test_drift_1m_still_rejects_genuine_drift():
    """If even the 1m price at the signal instant is past the cap, still reject."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # 1m-aligned signal instant
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:05:00"), 100.0),
                          _5m(_dt("2026-06-08T00:10:00"), 105.4)]}
    eng._fine_klines = {"FOOUSDT": {int(bar_open.timestamp()): [
        _1m(_dt("2026-06-08T00:08:00"), 104.0),   # +4.0% > 3 cap
    ]}}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is False
```

- [ ] **Step 2: Run to verify the new 1m tests FAIL (5m baseline passes)**

Run: `python -m pytest tests/backend/test_engine_drift_1m.py -v`
Expected: `test_drift_uses_5m_open_when_no_fine_window` PASS; the two 1m tests FAIL (engine still uses 5m, so the +5.4% BUY is rejected even with a fine window).

- [ ] **Step 3: Add the `_drift_reference_price` helper**

Insert immediately after `_fine_window` (~line 827) in `backend/services/backtest_engine.py`:

```python
    def _drift_reference_price(
        self, ticker: str, current_time: datetime,
        klines: dict[str, list[dict[str, Any]]],
    ) -> Optional[float]:
        """Price to drift-check a signal against — as close to live's real-time mark
        as the available data allows.

        Live checks drift vs get_mark_price() (a continuous tick mark). The 5m
        next-bar-open is a coarse proxy that a transient bar-open spike can push past
        the cap when the live mark never moved. When a 1m drill-down window covers the
        signal's entry bar, use the 1m OPEN at/just-after the signal instant instead —
        far closer to the live mark, no look-ahead (only candles with open_time >=
        current_time within the entry bar). Falls back to the 5m next-bar-open.
        """
        symbol_klines = klines.get(ticker, [])
        # The 5m bar that COVERS current_time (its own open is <= current_time < next).
        bar_open = None
        for k in symbol_klines:
            ot = k["open_time"]
            if ot <= current_time:
                bar_open = ot
            else:
                break
        if bar_open is not None:
            window = self._fine_window(ticker, bar_open)
            if window:
                for m in window:
                    if m["open_time"] >= current_time:
                        return m["open"]
        # Fallback: 5m next-bar-open (the original basis).
        for k in symbol_klines:
            if k["open_time"] >= current_time:
                return k["open"]
        return None
```

- [ ] **Step 4: Use the helper in the drift block**

Replace the `current_price` lookup (lines ~796–801) so the block reads:

```python
        max_drift = config.get("max_price_drift_pct")
        if max_drift is not None and not is_mr:
            analysis_price = signal.get("analysis_price")
            if analysis_price and analysis_price > 0:
                # Drift vs the closest-to-live-mark price: the 1m open at the signal
                # instant when a drill-down window exists, else the 5m next-bar-open.
                current_price = self._drift_reference_price(ticker, current_time, klines)
                if current_price is not None:
                    drift_pct = (current_price - analysis_price) / analysis_price * 100
                    if direction in ("buy", "long") and drift_pct > max_drift:
                        state.signals_filtered += 1
                        return False
                    if direction in ("sell", "short") and drift_pct < -max_drift:
                        state.signals_filtered += 1
                        return False
```

- [ ] **Step 5: Run the new tests — all pass**

Run: `python -m pytest tests/backend/test_engine_drift_1m.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Golden suite stays byte-identical (no fine_klines in default path)**

Run: `python -m pytest tests/backend/golden tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py tests/backend/test_backtest_engine.py -q`
Expected: all PASS, no snapshot changes.

- [ ] **Step 7: Commit**

```bash
git add backend/services/backtest_engine.py tests/backend/test_engine_drift_1m.py
git commit -m "fix(backtest-engine): drift gate uses 1m price at signal instant when drilldown present"
```

---

## Task 2: Selection tiebreaker matches live's order

**Files:**
- Modify: `backend/services/backtest_engine.py` (sort sites `:464`, `:479`, `:519`; add `_rank_key` staticmethod)
- Test: `tests/backend/test_engine_tiebreaker.py`
- Regenerate: golden snapshots that contain score-ties

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_engine_tiebreaker.py
from datetime import datetime, timezone
from backend.services.backtest_engine import BacktestEngine

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _sig(ticker, score, completed_at, _id):
    return {"ticker": ticker, "score": score, "analysis_completed_at": completed_at,
            "id": _id, "direction": "sell"}

def test_rank_key_orders_by_score_then_completed_at_desc_then_id():
    # Four signals tied at |score|=7; live picks the LATEST completed_at first.
    sigs = [
        _sig("A", -7, _dt("2026-06-05T01:00:00"), 10),
        _sig("B", -7, _dt("2026-06-05T03:00:00"), 11),   # latest -> ranks first
        _sig("C", -7, _dt("2026-06-05T02:00:00"), 12),
        _sig("D", -8, _dt("2026-06-05T00:30:00"), 13),   # higher |score| -> absolute first
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["D", "B", "C", "A"]

def test_rank_key_nulls_sort_last_within_a_score_tie():
    sigs = [
        _sig("A", -7, None, 10),                          # NULL completed_at -> last
        _sig("B", -7, _dt("2026-06-05T01:00:00"), 11),
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["B", "A"]
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/backend/test_engine_tiebreaker.py -v`
Expected: FAIL — `BacktestEngine` has no `_rank_key`.

- [ ] **Step 3: Add the `_rank_key` staticmethod**

Add to `BacktestEngine` (near `_process_batch_signals`, ~line 446):

```python
    @staticmethod
    def _rank_key(s: dict[str, Any]) -> tuple:
        """Selection rank that matches live's auto_trade_service.execute_batch ORDER:
        (abs(score), analysis_completed_at, id), all DESC under reverse=True.

        analysis_completed_at breaks score-ties (latest-analyzed first, matching live's
        `completed_at` DESC). A NULL completed_at must sort LAST within a tie (live's SQL
        uses NULLS LAST), so under reverse=True it needs the SMALLEST sort value — use a
        (has_ts, ts_epoch) pair where has_ts=0 for NULL. `id` is the final deterministic
        tiebreak.

        CAVEAT (not byte-identical to live, but the closest the engine can get):
        - Live ranks on `result["completed_at"]` from the scan-result payload; the engine
          ranks on `analysis_runs.completed_at` (per-ticker analysis finish). These are
          usually the same instant but may differ — see _load_signals' docstring.
        - Live compares ISO strings lexicographically; this compares epoch floats. They
          agree for uniform UTC ISO timestamps.
        - Live has no final `id` tiebreak (relies on stable dedup order); the engine adds
          `id` DESC for full determinism. On the two fill-pass sites (relaxed/immediate)
          live sorts by abs(score) ONLY — applying _rank_key there is harmless
          determinism hardening (signals already arrive pre-sorted from _load_signals'
          `ORDER BY ABS(score) DESC, ar.completed_at DESC NULLS LAST, sr.id`).
        """
        ca = s.get("analysis_completed_at")
        has_ts = 1 if ca is not None else 0
        ts = ca.timestamp() if ca is not None else 0.0
        return (abs(s.get("score", 0)), has_ts, ts, s.get("id", 0))
```

- [ ] **Step 4: Use `_rank_key` at all three sort sites**

Replace each of the three `sort(key=lambda s: abs(s.get("score", 0)), reverse=True)` /
`sorted(...)` calls (lines ~464, ~479, ~519) with:

```python
        unique_signals.sort(key=self._rank_key, reverse=True)
```
(line 464; and the corresponding `remaining.sort(key=self._rank_key, reverse=True)` at
479 and 519).

- [ ] **Step 5: Run the new tests — pass**

Run: `python -m pytest tests/backend/test_engine_tiebreaker.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Regenerate golden snapshots and verify the diff is tie-only**

Run the golden suite to see which snapshots changed:
```bash
python -m pytest tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py tests/backend/golden -q
```
Regeneration mechanism (`tests/backend/golden/__init__.py:assert_matches_snapshot`):
a snapshot is re-captured when its file is ABSENT. So for each FAILING snapshot `NAME`,
delete `tests/backend/golden/snapshots/NAME.json`, then re-run the suite once to
recapture it. Then **manually inspect** the git diff:
```bash
git diff tests/backend/golden/snapshots/
```

**Expected: exactly ONE snapshot changes — `p0_multi_symbol_batch.json`.** It is the
only golden fixture with an in-scan score-tie + more eligible signals than trade slots
(BTC id=1, ETH id=2, both score 8, same scan). The new `_rank_key` orders them by
`id` DESC (the golden `_signal()` builder omits `analysis_completed_at`, so `id` is the
only tiebreaker), swapping ETH ahead of BTC. **No other fixture has an in-scan tie**
(the rest are single-signal-per-scan, distinct scores, or separate scans).

**How to verify the diff is the correct reorder — NOT a regression:** the fingerprint
is ORDER-SENSITIVE (`golden/__init__.py` builds `trades` positionally + an
order-dependent `equity_curve`). So a tie-reorder legitimately shows POSITIONAL money
diffs (e.g. `trades[0].symbol BTC→ETH`, `trades[0].entry_price`, `.qty`, `.pnl` all
change, and possibly one intermediate `equity_curve` point). That is the reorder, not a
bug. Confirm correctness by checking the INVARIANTS that must hold:
- The trade MULTISET keyed by `symbol` is unchanged (same symbols traded, same count).
- Aggregate metrics are IDENTICAL: `net_profit`, `total_trades`, `winners`/`losers`,
  `final_equity`, `max_drawdown`.
If those invariants hold, the diff is the intended selection reorder. **A change in the
SET of symbols traded, the trade COUNT, or any aggregate metric IS a red flag — stop and
investigate.** (Run `git diff` and read the `summary`/`metrics` block of the snapshot to
confirm aggregates match.)

- [ ] **Step 7: Re-run golden suite green with regenerated snapshots**

Run: `python -m pytest tests/backend/golden tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit (snapshots in the SAME commit, with a note)**

```bash
git add backend/services/backtest_engine.py tests/backend/test_engine_tiebreaker.py tests/backend/golden/snapshots/
git commit -m "fix(backtest-engine): break score-ties by (completed_at, id) to match live selection

Regenerated golden: only p0_multi_symbol_batch changes (id-desc swap of two
score-8 trades). Trade multiset by symbol + all aggregate metrics unchanged;
positional diffs are the intended selection reorder, not a regression."
```

---

## Task 3a: ScanSource gains `replay` mode (schema)

**Files:**
- Modify: `backend/schemas/backtest_schemas.py` (ScanSource, ~line 12)
- Test: `tests/backend/test_replay_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_replay_mode.py
import pytest
from pydantic import ValidationError
from backend.schemas.backtest_schemas import ScanSource

def test_replay_mode_requires_account_id():
    with pytest.raises(ValidationError):
        ScanSource(mode="replay")            # no replay_account_id

def test_replay_mode_valid():
    s = ScanSource(mode="replay", replay_account_id="75aecaa7-0f10-400b-a562-1ddd7ae6cf94")
    assert s.mode == "replay"
    assert s.replay_account_id == "75aecaa7-0f10-400b-a562-1ddd7ae6cf94"

def test_existing_modes_unaffected():
    assert ScanSource(mode="schedule", schedule_id="x").mode == "schedule"
    assert ScanSource(mode="explicit", scan_ids=["a"]).mode == "explicit"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/backend/test_replay_mode.py -v`
Expected: FAIL — `"replay"` not a valid mode / no `replay_account_id` field.

- [ ] **Step 3: Extend ScanSource**

In `backend/schemas/backtest_schemas.py`, change the `mode` Literal and add the field +
validation:

```python
class ScanSource(BaseModel):
    """Defines which historical scan results to use for backtesting."""

    mode: Literal["schedule", "date_range", "explicit", "replay"]
    schedule_id: Optional[str] = None
    scan_ids: Optional[list[str]] = None
    # Replay mode: validate the engine against this account's ACTUAL live trades over
    # the request's date range (selection pinned from ground truth; simulation only).
    replay_account_id: Optional[str] = None

    @field_validator("scan_ids")
    @classmethod
    def validate_scan_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) > 500:
            raise ValueError("Maximum 500 scan_ids allowed")
        return v

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "ScanSource":
        if self.mode == "schedule" and not self.schedule_id:
            raise ValueError("schedule_id is required when mode='schedule'")
        if self.mode == "explicit" and not self.scan_ids:
            raise ValueError("scan_ids is required when mode='explicit'")
        if self.mode == "replay" and not self.replay_account_id:
            raise ValueError("replay_account_id is required when mode='replay'")
        return self
```

- [ ] **Step 4: Run — pass**

Run: `python -m pytest tests/backend/test_replay_mode.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/backtest_schemas.py tests/backend/test_replay_mode.py
git commit -m "feat(backtest): add 'replay' ScanSource mode (account-pinned validation)"
```

---

## Task 3b: Replay runner (backend orchestration over the harness units)

**Files:**
- Create: `backend/services/backtest/__init__.py` (empty), `backend/services/backtest/replay_runner.py`
- Test: extend `tests/backend/test_replay_mode.py`

The runner is a thin async orchestrator: it takes the DB + kline cache + an account +
window, drives the harness pipeline (extractor → shim → per-cycle isolation with
drill-down), and returns `(SimulationResult-like dict, replay_comparison)`. It does NOT
re-implement the engine — it calls `BacktestEngine` via `reporter.run_cycles_isolated`.

- [ ] **Step 1: Write the failing test (pure unit with a fake data-access)**

```python
# append to tests/backend/test_replay_mode.py
import pytest

@pytest.mark.asyncio
async def test_replay_runner_builds_comparison_from_fakes():
    from datetime import datetime, timezone
    from backend.services.backtest.replay_runner import run_replay

    def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    # Fake data-access returning one cycle of 2 pinned trades + their signals + klines.
    class FakeDA:
        async def fetch_live_trades(self, account_id, start, end):
            return [
                dict(symbol="A", side="Sell", net_pnl=10.0, close_reason="rule_triggered",
                     entry_price=100.0, exit_price=99.0, scan_result_id=1, status="closed",
                     base_capital=200.0, scan_id="s1", signal_time=_dt("2026-06-05T01:00:00"),
                     opened_at=_dt("2026-06-05T01:01:00"), closed_at=_dt("2026-06-05T02:00:00")),
                dict(symbol="B", side="Sell", net_pnl=12.0, close_reason="rule_triggered",
                     entry_price=50.0, exit_price=49.0, scan_result_id=2, status="closed",
                     base_capital=200.0, scan_id="s1", signal_time=_dt("2026-06-05T01:00:00"),
                     opened_at=_dt("2026-06-05T01:01:10"), closed_at=_dt("2026-06-05T02:00:00")),
            ]
        async def fetch_signals(self, scan_ids):
            t = _dt("2026-06-05T01:00:00")
            return [
                {"scan_id": "s1", "ticker": "A", "direction": "sell", "score": -8,
                 "signal_time": t, "id": 1, "analysis_completed_at": None, "analysis_price": 100.0},
                {"scan_id": "s1", "ticker": "B", "direction": "sell", "score": -8,
                 "signal_time": t, "id": 2, "analysis_completed_at": None, "analysis_price": 50.0},
            ]
        async def fetch_klines(self, kline_cache, symbols, start, end, interval="5m"):
            # Flat candles so the engine holds to backtest_end; PnL ~ entry vs last close.
            t0 = _dt("2026-06-05T01:05:00")
            from datetime import timedelta
            def series(p): return [{"open_time": t0 + timedelta(minutes=5*i),
                                    "open": p, "high": p, "low": p, "close": p, "volume": 1.0}
                                   for i in range(40)]
            return {"A": series(99.0), "B": series(49.0)}
        async def build_fine_klines(self, *a, **k): return {}

    config = {"leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
              "stop_loss_pct": 100, "max_drawdown_pct": 100, "execution_mode": "batch",
              "fill_to_max_trades": True, "skip_if_positions_open": True, "min_score": 7,
              "confidence_filter": "any", "signal_sides": "both", "direction": "straight",
              "fee_rate_pct": 0.055, "slippage_bps": 0, "simulation_interval": "5m",
              "max_price_drift_pct": None, "breakeven_timeout_hours": None}

    result, comparison = await run_replay(
        FakeDA(), kline_cache=None, account_id="acct",
        start=_dt("2026-06-04T22:00:00Z"), end=_dt("2026-06-10T06:00:00Z"),
        base_config=config)

    assert comparison["n_cycles"] == 1
    assert comparison["pinned_trades"] == 2
    assert len(comparison["cycles"]) == 1
    c0 = comparison["cycles"][0]
    assert c0["scan_id"] == "s1"
    assert "live_net_pnl" in c0 and "backtest_net_pnl" in c0 and "delta_pct" in c0
    assert "final_equity_delta_pct" in comparison
    # result carries engine trades for the normal results dashboard
    assert "trades" in result
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/backend/test_replay_mode.py::test_replay_runner_builds_comparison_from_fakes -v`
Expected: FAIL — module `backend.services.backtest.replay_runner` missing.

- [ ] **Step 3: Implement the runner**

```python
# backend/services/backtest/replay_runner.py
"""Replay-mode runner: validate the engine against an account's ACTUAL live trades.

Pins the account's real traded symbols (selection from ground truth) and replays them
through BacktestEngine per cycle, then builds a live-vs-backtest comparison. Reuses the
parity harness units — does NOT re-implement the engine.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import run_cycles_isolated, build_report


def _correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)


async def run_replay(
    data_access: Any, kline_cache: Any, account_id: str,
    start: datetime, end: datetime, base_config: dict[str, Any],
    drilldown: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (result_dict, replay_comparison).

    result_dict mimics SimulationResult enough for persistence: {trades, equity_curve}.
    replay_comparison: per-cycle live-vs-backtest + headline fidelity stats.
    """
    trade_rows = await data_access.fetch_live_trades(account_id, start, end)
    cycles = build_cycles(trade_rows)
    if not cycles:
        return ({"trades": [], "equity_curve": [], "starting_capital": 0.0},
                {"n_cycles": 0, "pinned_trades": 0, "cycles": [],
                 "final_equity_delta_pct": 0.0, "pnl_correlation": 0.0,
                 "directional_agreement": 0, "note": "no closed cycles in range"})

    signals = await data_access.fetch_signals([c.scan_id for c in cycles])
    pinned, _missing = pin_signals(signals, cycles, return_missing=True)

    signals_by_scan: dict[str, list] = {}
    for s in pinned:
        signals_by_scan.setdefault(s["scan_id"], []).append(s)

    klines = await data_access.fetch_klines(
        kline_cache, sorted({s["ticker"] for s in pinned}), start, end, "5m")

    cfg = dict(base_config)
    cfg.update({"date_range_start": start, "date_range_end": end})

    fine_by_scan: dict[str, Any] | None = None
    if drilldown and kline_cache is not None:
        fine_by_scan = {}
        for c in cycles:
            csyms = sorted({s["ticker"] for s in signals_by_scan.get(c.scan_id, [])})
            closes = [t.closed_at for t in c.live_trades if t.closed_at]
            if not csyms or not closes:
                continue
            fine_by_scan[c.scan_id] = await data_access.build_fine_klines(
                kline_cache, csyms, c.signal_time - timedelta(hours=1),
                max(closes) + timedelta(hours=1), sim_interval_seconds=300)

    engine_trades = run_cycles_isolated(
        BacktestEngine(), cycles, signals_by_scan, klines, cfg,
        fine_klines_by_scan=fine_by_scan)

    starting_capital = cycles[0].base_capital
    report = build_report(cycles, engine_trades, starting_capital, tolerance_pct=1.0)

    live_pnls = [cc.live_net_pnl for cc in report.cycles]
    bt_pnls = [cc.backtest_net_pnl for cc in report.cycles]
    comparison = {
        "n_cycles": len(report.cycles),
        "pinned_trades": len(pinned),
        "live_final_equity": report.live_final_equity,
        "backtest_final_equity": report.backtest_final_equity,
        "final_equity_delta_pct": report.final_equity_delta_pct,
        "pnl_correlation": _correlation(live_pnls, bt_pnls),
        "directional_agreement": sum(
            1 for a, b in zip(live_pnls, bt_pnls) if (a >= 0) == (b >= 0)),
        "cycles": [
            {"scan_id": cc.scan_id, "signal_time": cc.signal_time,
             "live_net_pnl": cc.live_net_pnl, "backtest_net_pnl": cc.backtest_net_pnl,
             "live_equity_after": cc.live_equity_after,
             "backtest_equity_after": cc.backtest_equity_after,
             "delta_pct": cc.delta_pct}
            for cc in report.cycles
        ],
    }
    # equity_curve for the normal dashboard: compounded backtest equity per cycle.
    # Emit drawdown_pct so the shape matches the engine's points (the service's
    # _downsample_equity reads .get("drawdown_pct") — present here for clarity/parity).
    _peak = float("-inf")
    equity_curve = []
    for cc in report.cycles:
        eq = cc.backtest_equity_after
        _peak = max(_peak, eq)
        dd = round(((eq - _peak) / _peak) * 100.0, 4) if _peak > 0 else 0.0
        equity_curve.append({"ts": cc.signal_time, "equity": eq, "drawdown_pct": dd})
    result = {"trades": engine_trades, "equity_curve": equity_curve,
              "starting_capital": starting_capital}
    return result, comparison
```

- [ ] **Step 4: Run — pass**

Run: `python -m pytest tests/backend/test_replay_mode.py -v`
Expected: all PASS (schema 3 + runner 1).

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/__init__.py backend/services/backtest/replay_runner.py tests/backend/test_replay_mode.py
git commit -m "feat(backtest): replay runner orchestrating the parity harness over the engine"
```

---

## Task 3c: Service wiring — `_execute_backtest` replay branch + persistence

**Files:**
- Modify: `backend/services/backtest_service.py` (`_execute_backtest` ~675; result get ~360–470; `_persist_results` ~1462)
- Test: `tests/backend/test_replay_e2e.py` (DB-gated)

- [ ] **Step 1: Write the DB-gated E2E test (skipped without the flag)**

```python
# tests/backend/test_replay_e2e.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PARITY_DB_SMOKE"),
    reason="set PARITY_DB_SMOKE=1 to run replay E2E against local hydrated DB")

@pytest.mark.asyncio
async def test_replay_mode_end_to_end_dad_demo():
    from datetime import datetime, timezone
    from backend.async_persistence import AsyncAnalysisDB
    from backend.services.kline_cache_service import KlineCacheService
    from backend.diagnostics.parity.data_access import ParityDataAccess
    from backend.services.backtest.replay_runner import run_replay

    db = AsyncAnalysisDB(os.environ["DATABASE_URL"]); await db.connect()
    try:
        cfg = {"leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
               "stop_loss_pct": 100, "max_drawdown_pct": 12, "smart_drawdown_close": True,
               "trailing_profit_pct": 2, "breakeven_timeout_hours": None,
               "max_trade_duration_hours": 24, "min_score": 7, "confidence_filter": "moderate",
               "signal_sides": "both", "execution_mode": "batch", "fill_to_max_trades": True,
               "skip_if_positions_open": True, "adaptive_blacklist_enabled": True,
               "adaptive_blacklist_min_trades": 5, "adaptive_blacklist_max_win_rate": 30,
               "adaptive_blacklist_lookback_hours": 48, "target_goal_type": "profit_pct",
               "target_goal_value": 15, "max_price_drift_pct": None, "max_same_sector": 2,
               "max_same_direction": 3, "direction": "straight", "fee_rate_pct": 0.055,
               "slippage_bps": 2, "simulation_interval": "5m"}
        result, comp = await run_replay(
            ParityDataAccess(db), KlineCacheService(db),
            "75aecaa7-0f10-400b-a562-1ddd7ae6cf94",
            datetime(2026, 6, 4, 22, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 6, tzinfo=timezone.utc), cfg)
        assert comp["n_cycles"] == 17
        assert comp["pinned_trades"] == 51
        assert comp["pnl_correlation"] > 0.9            # high fidelity guard
        assert comp["directional_agreement"] >= 15
    finally:
        await db.close()
```

- [ ] **Step 2: Run — verify SKIPPED (import path resolves)**

Run: `python -m pytest tests/backend/test_replay_e2e.py -v`
Expected: SKIPPED (1).

- [ ] **Step 3: Add the replay branch in `_execute_backtest`**

In `backend/services/backtest_service.py`, near the top of `_execute_backtest` after
`_mark_status(run_id, "running", started=True)` (~line 702), branch BEFORE the normal
`_load_signals` path. **The branch MUST stay INSIDE the method's `try` block** so the
existing `finally` (which pops `_cancel_events` and decrements `_active_slots`) still
runs — do not place it before the `try`.

```python
            scan_source = config.get("scan_source", {})
            if scan_source.get("mode") == "replay":
                from backend.diagnostics.parity.data_access import ParityDataAccess
                from backend.services.backtest.replay_runner import run_replay
                account_id = scan_source.get("replay_account_id")
                result_dict, comparison = await run_replay(
                    ParityDataAccess(self._db), self._kline_cache, account_id,
                    config["date_range_start"], config["date_range_end"], config)
                # Anchor metrics to the SAME compounding basis the replay used (the
                # account's first-cycle base_capital), NOT the user's starting_capital
                # field — otherwise net_profit_pct/cagr degenerate. run_replay returns it.
                from backend.services.backtest_metrics import compute_all_metrics
                metrics_config = {**config,
                                  "starting_capital": result_dict.get("starting_capital")
                                  or config.get("starting_capital") or 0.0}
                metrics = compute_all_metrics(
                    result_dict["trades"], result_dict["equity_curve"], metrics_config)
                from backend.schemas.backtest_schemas import SimulationResult
                sim = SimulationResult(
                    trades=result_dict["trades"], equity_curve=result_dict["equity_curve"],
                    metrics=metrics, warnings=[f"replay_mode_account_{account_id}"],
                    filter_stats={"signals_total": comparison["pinned_trades"],
                                  "signals_entered": len(result_dict["trades"]),
                                  "signals_filtered": 0, "signals_no_kline": 0})
                await self._persist_results(run_id, sim, replay_comparison=comparison)
                return
```

(`run_replay` must return `starting_capital` in `result_dict` — add `"starting_capital":
starting_capital` to the runner's returned `result` dict in Task 3b, and emit
`"drawdown_pct": 0.0` on each equity point so the curve shape matches the engine's.)

**Known limitation (acceptable for v1):** the replay branch returns before the normal
path's `threading.Timer` wall-clock timeout (`_TIMEOUT_SECONDS`) and `cancel_event`
wiring, so a replay run is not cancellable and has no hard timeout. Cleanup is still
safe — the branch is inside the method `try`, so the existing `finally` pops
`_cancel_events` and releases the `_active_slots` slot, and `_persist_results` flips
status→completed in its own transaction (no slot leak, no stuck 'running'). A replay
over a bounded window (one account, days) completes in seconds, so this is acceptable;
note it as a follow-up if replay is ever opened to long ranges.

- [ ] **Step 4: Thread `replay_comparison` through `_persist_results` by NESTING in `summary`**

⚠️ **CRITICAL — `summary` is ALREADY used.** `_persist_results` currently writes
`summary = result.filter_stats or {}` (`backtest_service.py:1506`) into the
`backtest_results.summary` JSONB (`INSERT ... summary ...` at `:1526`), and
`_build_results` reads it back (`:486 "summary": self._coerce_json(row["summary"]) or {}`).
So we must **NEST** the comparison inside `summary`, never overwrite it — overwriting
would clobber filter_stats on every run.

Modify `_persist_results` (~line 1462):

```python
    async def _persist_results(self, run_id: str, result: Any,
                               replay_comparison: Optional[dict[str, Any]] = None) -> None:
```
Find the existing `summary = result.filter_stats or {}` line (~1506) and make it carry
the comparison when present (normal path: `replay_comparison=None` → unchanged dict):

```python
        summary = dict(result.filter_stats or {})
        if replay_comparison is not None:
            summary["replay_comparison"] = replay_comparison
```
The existing `json.dumps(_json_safe(summary), default=str)` at the INSERT (~1535) then
serializes it correctly — no other change to the INSERT needed.

- [ ] **Step 5: Surface `replay_comparison` from the nested `summary` in the GET payload**

`_build_results` already selects + returns `summary` (`:276`, `:486`). Add the nested
key alongside it so the UI can read it directly:

```python
        summary_obj = self._coerce_json(row["summary"]) or {}
        return {
            "metrics": ...,                      # unchanged
            "equity_curve": self._downsample_equity(equity),
            "summary": summary_obj,              # unchanged (still carries filter_stats)
            "replay_comparison": summary_obj.get("replay_comparison"),  # None for normal runs
            "warnings": ...,
        }
```
(Match the exact existing return-dict shape in `_build_results` ~line 477–488; just add
the one `replay_comparison` key reading from the already-fetched `summary_obj`.)

- [ ] **Step 6: Run the E2E with the DB flag**

Run: `PARITY_DB_SMOKE=1 python -m pytest tests/backend/test_replay_e2e.py -v`
Expected: PASS — 17 cycles, 51 pinned, correlation > 0.9. (Requires the local DB
hydrated per the parity baseline note; if it fails on data, re-hydrate.)

- [ ] **Step 7: Golden + engine suites still green**

Run: `python -m pytest tests/backend/golden tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py tests/backend/test_backtest_engine.py tests/backend/test_backtest_schemas.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/services/backtest_service.py tests/backend/test_replay_e2e.py
git commit -m "feat(backtest): wire replay mode into the service + persist live-vs-backtest comparison"
```

---

## Task 3d: Frontend — replay account picker + comparison section

**Files (verified names/paths):**
- Modify: `frontend/src/components/backtest/types.ts` — `ScanSource` (line 35, inline mode union) + `BacktestResults` (line 208).
- Modify: `frontend/src/components/backtest/configSchema.ts` — `scanSourceSchema` (line 17, `z.enum` at 19). **The plan previously missed this file — without it RHF/zod strips `replay_account_id` and rejects `mode:"replay"`.**
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx` — scan-source `SelectField` options (line ~449) + `scanMode` conditional (line ~361/458) + `BacktestConfigFormProps` (line 301).
- Modify: `frontend/src/components/backtest/BacktestNewForm.tsx` (line 42) — the PARENT that renders the form; add the accounts query here and pass it as a prop (the form is presentational — it takes `schedules` as a prop, no query inside).
- Modify: `frontend/src/components/backtest/BacktestResultsPage.tsx` — replay card; result is `run.results` (`BacktestRun.results`, types.ts:226), NOT a `result` var.

- [ ] **Step 1: Add types (types.ts)**

Extend the inline `ScanSource.mode` union (line 36) and add the comparison shape +
result field:

```typescript
// types.ts — change ScanSource (line 35):
export interface ScanSource {
  mode: "schedule" | "date_range" | "explicit" | "replay";
  schedule_id?: string | null;
  scan_ids?: string[] | null;
  replay_account_id?: string | null;   // NEW
}

export interface ReplayCycle {
  scan_id: string;
  signal_time: string;
  live_net_pnl: number;
  backtest_net_pnl: number;
  live_equity_after: number;
  backtest_equity_after: number;
  delta_pct: number;
}

export interface ReplayComparison {
  n_cycles: number;
  pinned_trades: number;
  live_final_equity: number;
  backtest_final_equity: number;
  final_equity_delta_pct: number;
  pnl_correlation: number;
  directional_agreement: number;
  cycles: ReplayCycle[];
}
```
Add `replay_comparison?: ReplayComparison | null;` to the **`BacktestResults`** interface
(line 208) — that's the object at `run.results` the page reads.

- [ ] **Step 2: Extend the zod schema (configSchema.ts) — REQUIRED**

In `configSchema.ts`, change `scanSourceSchema` (line 17–): add `"replay"` to the enum,
add the optional field, and a refine requiring it in replay mode (mirrors backend
`backtest_schemas.py` validator):

```typescript
export const scanSourceSchema = z
  .object({
    mode: z.enum(["schedule", "date_range", "explicit", "replay"]),
    schedule_id: z.string().nullish(),
    scan_ids: z.array(z.string()).nullish(),
    replay_account_id: z.string().nullish(),   // NEW
  })
  // ...keep existing schedule/explicit refines...
  .refine((s) => s.mode !== "replay" || !!s.replay_account_id, {
    message: "Select an account to replay",
    path: ["replay_account_id"],
  });
```

- [ ] **Step 3: Parent fetches accounts (BacktestNewForm.tsx)**

The form is presentational (takes `schedules` as a prop). In `BacktestNewForm.tsx`, fetch
accounts the way the rest of the app does and pass them down. Use
`accountsApi.getDashboard()` (queryKey `["accounts","dashboard"]` per
`AccountsDashboard.tsx:126`) because its `DashboardCard` carries `id`, `label`, AND
`ai_manager_state` (client.ts:841) — needed for the warning note. (`accountsApi.list()`
returns `TradingAccount`, which does NOT include any AI-manager field, so it can't drive
the note.)

```typescript
const { data: accounts = [] } = useQuery({
  queryKey: ["accounts", "dashboard"],
  queryFn: () => accountsApi.getDashboard(),
});
// ...
<BacktestConfigForm /* existing props */ accounts={accounts} />
```
Add `accounts?: DashboardCard[]` to `BacktestConfigFormProps` (BacktestConfigForm.tsx:301)
and default `accounts = []` in the destructure (line ~314).

- [ ] **Step 4: Config form — Replay option + account picker (BacktestConfigForm.tsx)**

Add a third option to the scan-source `SelectField` (line ~449): `{ value: "replay",
label: "Replay (validate vs live)" }`. Add a `scanMode === "replay"` branch next to the
existing `scanMode === "schedule"` block (line ~458) that renders an account
`<select>` bound to `scan_source.replay_account_id` (options from the `accounts` prop:
`value={a.id}` / label `a.label`), and hides the schedule/scan-id inputs. When the
selected account's `ai_manager_state` is non-null, show an inline note: "This account
uses the AI Manager, which the backtest excludes — replay fidelity is most meaningful for
non-AI-Manager accounts."

- [ ] **Step 5: Results page — comparison section (BacktestResultsPage.tsx)**

The page gets the run via its polling hook (`run: BacktestRun`). Read
`const replay = run.results?.replay_comparison;`. When present, render a "Replay vs Live"
card above the normal charts, following the existing `HeroMetrics`/`neu-surface-base
neu-surface-inset` card pattern:
- Headline: `final_equity_delta_pct` (`+/-X.X%`), `pnl_correlation` (2dp, e.g. `0.99`),
  `directional_agreement` as `N/${replay.n_cycles}`, framed as fidelity (NOT pass/fail
  vs ±1%). Caption: "Backtest is typically a few % conservative vs live due to live
  execution latency."
- A per-cycle table from `replay.cycles`: columns scan (short id), live PnL, backtest
  PnL, live equity, backtest equity, delta %.

- [ ] **Step 6: Type-check + build**

Run: `cd frontend && npx tsc -b --noEmit && npm run build`
(package.json `build` = `tsc -b && vite build`; `tsc -b` is the project-references-correct
typecheck.) Expected: no type errors; build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/backtest/types.ts frontend/src/components/backtest/configSchema.ts frontend/src/components/backtest/BacktestConfigForm.tsx frontend/src/components/backtest/BacktestNewForm.tsx frontend/src/components/backtest/BacktestResultsPage.tsx
git commit -m "feat(backtest-ui): replay account picker + live-vs-backtest comparison section"
```

---

## Self-Review Notes

- **Spec coverage:** §2 drift → Task 1. §3 tiebreaker → Task 2 (+ golden regen). §4
  replay → Tasks 3a (schema), 3b (runner), 3c (service+persist), 3d (UI). §5 order
  (drift→tiebreaker→replay) → task order. §6 testing (golden gate per change, replay
  E2E) → Task 1.6, 2.6–2.7, 3c.7. §7 risks → Task 2.6, 2.3 test, 1.3 helper, 3d.4.
- **Breakeven explicitly excluded** — no task touches it (correct per spec §1 non-goal).
- **Golden safety:** Tasks 1 & 3 assert byte-identical golden; only Task 2 regenerates
  (`p0_multi_symbol_batch` only), with a mandatory invariant-based diff review.

### Review pass (2026-06-10, 4 parallel verifiers vs the codebase) — issues fixed

- **[CRITICAL] `summary` column collision** — `_persist_results` already stores
  `filter_stats` in `backtest_results.summary` and `_build_results` returns it.
  Overwriting it would clobber filter_stats on EVERY run and render a garbage replay
  card on normal runs. **Fixed:** Task 3c now NESTS `replay_comparison` inside `summary`
  and reads `summary_obj.get("replay_comparison")`.
- **[CRITICAL] Task 1 drift tests broken** — tests used a non-bar-aligned instant
  (00:08:15) and omitted the entry-bar 5m candle, so the 1m path was never exercised and
  the asserts passed/failed for the wrong reason. **Fixed:** bar-aligned `t=00:08:00` +
  entry-bar 5m candle added to all three tests.
- **[CRITICAL] Frontend access path / schema / account field** — result is
  `run.results.replay_comparison` (not `result.replay_comparison`); `configSchema.ts`
  zod enum was omitted (would strip the field); `ai_manager_enabled` is NOT on the
  accounts list type. **Fixed:** Task 3d rewritten with verified names — `BacktestResults`
  field, `configSchema.ts` step added, accounts via `getDashboard()` using
  `ai_manager_state`, and the parent (`BacktestNewForm`) fetches + passes `accounts`.
- **[HIGH] Golden-regen guidance would wrongly block the correct change** — the
  fingerprint is order-sensitive, so a benign tie-reorder shows positional money diffs.
  **Fixed:** Task 2 Step 6 now verifies INVARIANTS (trade multiset by symbol + aggregate
  metrics unchanged) instead of "no money diffs."
- **[MEDIUM] metrics baseline** — `compute_all_metrics` needs `starting_capital`; the
  replay config omitted it. **Fixed:** runner returns `starting_capital`; the branch
  anchors metrics to it. Replay equity points now emit `drawdown_pct`.
- **[MEDIUM] "byte-identical to live" overstated** — **Fixed:** `_rank_key` docstring now
  documents the 3 semantic caveats (analysis-runs vs payload timestamp, float vs string
  compare, added `id` tiebreak); claim downgraded to "matches live's selection order in
  the common case."
- **[MEDIUM] replay timeout/cancel** — documented as an accepted v1 limitation (cleanup
  is safe; bounded window completes in seconds).
- **[LOW] dropped** unused `live_final_equity` import from the runner.
