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
- Modify: `backend/services/backtest_service.py` — `replay` branch in `_execute_backtest`; persist `replay_comparison`.
- Create: `backend/services/backtest/replay_runner.py` — thin orchestrator that calls the harness units (keeps the service method small).
- Modify: results payload (`get` / `_persist_results`) to carry `replay_comparison`.
- Frontend: `frontend/src/components/backtest/BacktestConfigForm.tsx` (account picker for replay), `BacktestResultsPage.tsx` (replay-vs-live section), `types.ts`.
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
    t = _dt("2026-06-08T00:08:15")
    sig = _signal("BLESSUSDT", "sell", -7, 0.00855, t)
    klines = {"BLESSUSDT": [_5m(_dt("2026-06-08T00:10:00"), 0.009015)]}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    # A sell with price UP is admitted by the gate (drift_pct +5.4% is not < -3)
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is True

def test_drift_uses_1m_open_when_fine_window_present():
    """Same sell, but a BUY-equivalent rejection case: construct a BUY whose 5m
    next-bar-open trips the cap (+5.4% > 3) yet whose 1m open at the signal instant
    (+1.0%) does NOT. With a fine window the 1m price is used → admitted."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:15")
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")       # the 5m bar covering 00:08:15
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:10:00"), 105.4)]}   # +5.4% next-bar-open
    # 1m window for the entry bar: open at the signal minute is 101.0 (+1.0%)
    eng._fine_klines = {"FOOUSDT": {int(bar_open.timestamp()): [
        _1m(_dt("2026-06-08T00:05:00"), 100.5),
        _1m(_dt("2026-06-08T00:08:00"), 101.0),   # the minute of the signal
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
    t = _dt("2026-06-08T00:08:15")
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:10:00"), 105.4)]}
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
        """Selection rank, byte-identical to live's auto_trade_service.execute_batch:
        (abs(score), analysis_completed_at, id), all DESC under reverse=True.

        analysis_completed_at breaks score-ties (latest-analyzed first, matching live's
        `completed_at` DESC). A NULL completed_at must sort LAST within a tie (live's SQL
        uses NULLS LAST), so under reverse=True it needs the SMALLEST sort value — use a
        (has_ts, ts_epoch) pair where has_ts=0 for NULL. `id` is the final deterministic
        tiebreak.
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
Confirm every change only REORDERS entries that share the same `abs(score)` (different
symbols selected from a tied pool). **Any change to a non-tied selection, a price, or a
PnL is a red flag — stop and investigate.** (Most golden fixtures use distinct scores
and will NOT change at all; only fixtures with an explicit score-tie + more eligible
signals than max_trades are affected — e.g. `p0_multi_symbol_batch` if it has ties.)

- [ ] **Step 7: Re-run golden suite green with regenerated snapshots**

Run: `python -m pytest tests/backend/golden tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit (snapshots in the SAME commit, with a note)**

```bash
git add backend/services/backtest_engine.py tests/backend/test_engine_tiebreaker.py tests/backend/golden/snapshots/
git commit -m "fix(backtest-engine): break score-ties by (completed_at, id) to match live selection

Regenerated golden snapshots: diffs only reorder equal-abs(score) selections
(the intended fidelity change); no price/PnL/non-tie changes."
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
from backend.diagnostics.parity.extractor import build_cycles, live_final_equity
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
        return ({"trades": [], "equity_curve": []},
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
    equity_curve = [{"ts": cc.signal_time, "equity": cc.backtest_equity_after}
                    for cc in report.cycles]
    result = {"trades": engine_trades, "equity_curve": equity_curve}
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
`_load_signals` path:

```python
            scan_source = config.get("scan_source", {})
            if scan_source.get("mode") == "replay":
                from backend.diagnostics.parity.data_access import ParityDataAccess
                from backend.services.backtest.replay_runner import run_replay
                account_id = scan_source.get("replay_account_id")
                result_dict, comparison = await run_replay(
                    ParityDataAccess(self._db), self._kline_cache, account_id,
                    config["date_range_start"], config["date_range_end"], config)
                # Reuse the standard metrics + persistence on the replay's engine trades.
                from backend.services.backtest_metrics import compute_all_metrics
                metrics = compute_all_metrics(
                    result_dict["trades"], result_dict["equity_curve"], config)
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

- [ ] **Step 4: Thread `replay_comparison` through `_persist_results` via the `summary` column**

`backtest_results` already has a `summary JSONB NOT NULL DEFAULT '{}'` column
(`async_persistence.py:690`) — store the comparison there; **no migration needed.**
Modify `_persist_results` (~line 1462):

```python
    async def _persist_results(self, run_id: str, result: Any,
                               replay_comparison: Optional[dict[str, Any]] = None) -> None:
```
In its results-row UPSERT, set `summary` to `json.dumps(replay_comparison, default=str)`
when `replay_comparison` is not None, else keep the existing default `'{}'`. (Find the
`INSERT INTO backtest_results (... )` in this method and add `summary` to the column
list + values; the normal path passes None → `'{}'`.) Use the same `_json_safe`/default=str
pattern the method already uses for `metrics`/`equity_curve` so datetimes serialize.

- [ ] **Step 5: Return `replay_comparison` in the run GET payload**

The results read already selects from `backtest_results`. Add `summary` to that SELECT
(if not already) and surface it: in the result-assembly dict add
`"replay_comparison": self._coerce_json(row["summary"]) or None`. When `summary` is the
default `{}`, this yields an empty dict the UI treats as "no replay comparison"; a
populated replay run yields the full comparison. (If `summary` is already selected and
used for something else, nest the comparison under `summary["replay_comparison"]`
instead and read that key.)

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

**Files:**
- Modify: `frontend/src/components/backtest/types.ts` (ScanSource type + ReplayComparison type)
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx` (Replay source option + account picker)
- Modify: `frontend/src/components/backtest/BacktestResultsPage.tsx` (replay comparison section)

- [ ] **Step 1: Add types**

In `frontend/src/components/backtest/types.ts`, extend the scan-source mode union and
add the comparison shape:

```typescript
export type ScanSourceMode = "schedule" | "date_range" | "explicit" | "replay";

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
And add `replay_account_id?: string` to the ScanSource type and `replay_comparison?: ReplayComparison` to the backtest result type.

- [ ] **Step 2: Config form — Replay option + account picker**

In `BacktestConfigForm.tsx`, add "Replay (validate vs live)" to the scan-source選択 and,
when selected, render an account dropdown (reuse the accounts query the app already
uses for the accounts page) bound to `scan_source.replay_account_id`. Hide the
schedule/scan-id inputs in replay mode. When the chosen account has
`ai_manager_enabled`, show an inline note: "This account uses the AI Manager, which the
backtest excludes — replay fidelity is most meaningful for non-AI-Manager accounts."

- [ ] **Step 3: Results page — comparison section**

In `BacktestResultsPage.tsx`, when `result.replay_comparison` is present, render a
"Replay vs Live" card above the normal charts:
- Headline stats: `final_equity_delta_pct` (formatted `+/-X.X%`), `pnl_correlation`
  (e.g. `0.99`), `directional_agreement` as `N/total cycles`, framed as fidelity (NOT a
  pass/fail vs ±1%). Add a caption: "Backtest is typically a few % conservative vs live
  due to live execution latency."
- A per-cycle table from `cycles`: columns scan (short), live PnL, backtest PnL, live
  equity, backtest equity, delta %.

- [ ] **Step 4: Type-check + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no type errors; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/backtest/types.ts frontend/src/components/backtest/BacktestConfigForm.tsx frontend/src/components/backtest/BacktestResultsPage.tsx
git commit -m "feat(backtest-ui): replay account picker + live-vs-backtest comparison section"
```

---

## Self-Review Notes

- **Spec coverage:** §2 drift → Task 1. §3 tiebreaker → Task 2 (+ golden regen). §4
  replay → Tasks 3a (schema), 3b (runner), 3c (service+persist), 3d (UI). §5 order
  (drift→tiebreaker→replay) → task order. §6 testing (golden gate per change, replay
  E2E) → Task 1.6, 2.6–2.7, 3c.7. §7 risks (tie-only golden diff, NULL completed_at,
  no look-ahead, UI framing) → Task 2.6, 2.3 test, 1.3 helper, 3d.3.
- **Breakeven explicitly excluded** — no task touches it (correct per spec §1 non-goal).
- **Type/name consistency:** `_rank_key`, `_drift_reference_price`, `run_replay`,
  `ReplayComparison`, `replay_account_id`, `replay_comparison` used consistently across
  backend tasks and the TS types.
- **No placeholders:** every code step shows full code; every run step has a command +
  expected result. The only non-literal step is Task 3c.4/3.5 persistence, which depends
  on whether results are a JSON blob or a column — both branches are specified.
- **Golden safety:** Tasks 1 & 3 assert byte-identical golden; only Task 2 regenerates,
  with a mandatory manual tie-only diff review.
