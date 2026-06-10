# Selective-Trade Backtest Parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a diagnostic harness that replays "Dad - Demo" account's actual live trade selection through the existing `BacktestEngine`, compare it cycle-by-cycle against the live `trades` oracle, and fix the engine gaps until backtest final equity is within ±1% of live.

**Architecture:** A read-only harness package (`backend/diagnostics/parity/`) with four small, independently testable units — hydration check, live-selection extractor, selection shim, parity reporter — plus a CLI entrypoint. The shim filters the engine's input `signals` list down to live's pinned `(scan_id, ticker, side)` set, so the engine still simulates fills/closes/PnL/compounding from candles but cannot pick a different symbol subset. Engine bugs the comparison exposes are fixed TDD in `backtest_engine.py`, each gated by the existing golden-master suite.

**Tech Stack:** Python 3.12, asyncio, asyncpg (`AsyncAnalysisDB`), pytest + pytest-asyncio. Reuses `BacktestEngine.run()` and `BacktestService` data-loading patterns. Data is hydrated into the local Postgres from prod via the `copy-prod-scans` skill before the harness runs.

---

## Reference Facts (verified against prod, 2026-06-10)

These are ground-truth values the implementation depends on. Do not re-derive — use them.

- **Validation account:** `Dad - Demo`, id `75aecaa7-0f10-400b-a562-1ddd7ae6cf94`, `ai_manager_enabled=false`.
- **Window:** `2026-06-05T00:00:00Z` → `2026-06-10T00:00:00Z`.
- **Live ground truth:** 51 closed trades + 1 open (MEGAUSDT, excluded). 17 trading cycles, exactly 3 trades each. First cycle `base_capital ≈ 200.43428197`.
- **Schedule:** `Every 2 Hour Scan`, schedule_id `d9c5f14f-a71f-4907-9449-dab3b75a52cb`. Dad's config is one entry in its `scan_config.auto_trade_configs` (account_id matches above).
- **Config under test:** `leverage=10, capital_pct=20, max_trades=3, take_profit_pct=150, stop_loss_pct=100, max_drawdown_pct=12, smart_drawdown_close=true, trailing_profit_pct=2, breakeven_timeout_hours=12, max_trade_duration_hours=24, min_score=7, confidence_filter="moderate", signal_sides="both", execution_mode="batch", fill_to_max_trades=true, skip_if_positions_open=true, adaptive_blacklist_enabled=true, adaptive_blacklist_min_trades=5, adaptive_blacklist_max_win_rate=30, adaptive_blacklist_lookback_hours=48, target_goal_type="profit_pct", target_goal_value=15, max_price_drift_pct=3, max_same_sector=2, max_same_direction=3, direction="straight"`.
- **Engine entry point:** `BacktestEngine().run(config, signals, klines, cancel_event=None, on_progress=None, instrument_info=None, scan_contexts=None, fine_klines=None) -> SimulationResult`.
  - `signals`: flat chronological list of dicts; engine groups by `sig["scan_id"]`. Each dict has keys: `id, ticker, direction, confidence, score, signal_time, analysis_completed_at, scan_id, signal_source, analysis_price`.
  - `klines`: `{symbol: [ {open_time: datetime, open, high, low, close, volume}, ... ascending ]}`.
  - `config` must also include `starting_capital`, `fee_rate_pct` (default 0.055), `slippage_bps` (default 2).
  - `SimulationResult` fields: `.trades` (list of closed-trade dicts), `.equity_curve`, `.metrics`, `.warnings`, `.filter_stats`.
- **Selection-divergence root cause:** live `auto_trade_service.execute_batch` sorts by `(abs(score), completed_at)`; the service's `_load_signals` reconstructs this via `ORDER BY signal_time, ABS(sr.score) DESC, ar.completed_at DESC NULLS LAST, sr.id` (joining `analysis_runs ar` on `run_id`; `completed_at` is 100% populated). The engine then re-sorts in-memory by `abs(score)` only. Pinning removes this variable entirely.
- **Case normalization:** `scan_results.direction` ∈ {`buy`,`sell`,`hold`}; `trades.side` ∈ {`Buy`,`Sell`}; `auto_trade_results[].side` ∈ {`Buy`,`Sell`}. Normalize to lowercase when matching pinned sets. `_to_symbol(ticker)` in `auto_trade_service` is identity for these USDT symbols but use the engine's symbol convention (`ticker` as-is, e.g. `ARKMUSDT`).
- **Close reasons in live data:** `rule_triggered` (~75%) and `external` (~25%, fees already in `net_pnl`, `fees=0`).

---

## File Structure

- `backend/diagnostics/__init__.py` — new package marker (diagnostics namespace).
- `backend/diagnostics/parity/__init__.py` — parity subpackage marker.
- `backend/diagnostics/parity/models.py` — dataclasses: `LiveTrade`, `Cycle`, `CycleComparison`, `ParityReport`.
- `backend/diagnostics/parity/extractor.py` — live-selection extractor (oracle reader). Pure functions over rows.
- `backend/diagnostics/parity/shim.py` — selection shim: filter engine `signals` to pinned set.
- `backend/diagnostics/parity/reporter.py` — parity reporter: run engine over pinned cycles, build comparison + pass/fail.
- `backend/diagnostics/parity/data_access.py` — async DB reads (trades, auto_trade_results, scan signals, klines, coverage check). Mirrors `BacktestService` query shapes.
- `backend/diagnostics/parity/run_parity.py` — CLI entrypoint wiring it together; prints the report.
- `tests/backend/diagnostics/__init__.py`, `tests/backend/diagnostics/test_extractor.py`, `test_shim.py`, `test_reporter.py` — unit tests (no DB; fixtures).
- Engine fixes (as discovered): `backend/services/backtest_engine.py` + regression tests in `tests/backend/`.

Each unit is pure/synchronous except `data_access.py` (async DB). DB I/O is isolated so extractor/shim/reporter are testable with in-memory fixtures.

---

## Task 0: Hydrate local DB + verify ground truth

**Goal:** Get the validation account's prod data into local DB and assert the known invariants before writing any harness code. No app code yet — de-risks every later task.

**Files:** none (operational); produces `docs/superpowers/plans/parity-baseline.md` notes.

- [ ] **Step 1: Hydrate local DB from prod via copy-prod-scans**

Invoke the `copy-prod-scans` skill to copy, for account `75aecaa7-0f10-400b-a562-1ddd7ae6cf94` and window `2026-06-05`..`2026-06-10`: the 17 scans (with their `scan_results` and `auto_trade_results`), the 51 `trades` rows, and `kline_cache` 5m candles for every symbol those trades touched. If the skill cannot scope to one account, copy schedule `d9c5f14f-a71f-4907-9449-dab3b75a52cb`'s scans for the window.

- [ ] **Step 2: Verify the live oracle invariants in LOCAL db**

Run (local DB):

```bash
psql "$DATABASE_URL" -P pager=off -c "
select count(*) filter (where status='closed') as closed,
       count(*) filter (where status='open')   as open,
       min(base_capital) as first_base, count(distinct scan_result_id) as distinct_signals
from trades
where account_id='75aecaa7-0f10-400b-a562-1ddd7ae6cf94' and opened_at>='2026-06-05';"
```

Expected: `closed=51, open=1, first_base≈200.43, distinct_signals=51`.

- [ ] **Step 3: Verify kline coverage for every traded symbol**

Run (local DB):

```bash
psql "$DATABASE_URL" -P pager=off -c "
with syms as (
  select distinct symbol from trades
  where account_id='75aecaa7-0f10-400b-a562-1ddd7ae6cf94' and opened_at>='2026-06-05' and status='closed')
select s.symbol,
       (select count(*) from kline_cache k where k.symbol=s.symbol and k.interval='5m'
        and k.open_time between '2026-06-05' and '2026-06-10') as candles
from syms s order by candles asc limit 10;"
```

Expected: every symbol has > 0 candles. Note any zero-coverage symbol — Step 4 warms it.

- [ ] **Step 4: Warm any missing klines**

For any symbol with 0 candles, use the local MCP `cache_warmup` tool for that symbol, `5m`, `2026-06-05`..`2026-06-10`. Re-run Step 3 until all covered. Record final coverage in `parity-baseline.md`.

- [ ] **Step 5: Commit the baseline note**

```bash
git add docs/superpowers/plans/parity-baseline.md
git commit -m "docs(backtest-parity): local hydration + ground-truth baseline note"
```

---

## Task 1: Parity dataclasses (`models.py`)

**Files:**
- Create: `backend/diagnostics/__init__.py` (empty), `backend/diagnostics/parity/__init__.py` (empty)
- Create: `backend/diagnostics/parity/models.py`
- Test: `tests/backend/diagnostics/__init__.py` (empty), `tests/backend/diagnostics/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/diagnostics/test_models.py
from datetime import datetime, timezone
from backend.diagnostics.parity.models import LiveTrade, Cycle, CycleComparison, ParityReport

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def test_live_trade_pin_key_normalizes_side():
    t = LiveTrade("ARKMUSDT", "Sell", 11.93, "rule_triggered", 0.13392, 0.12986, 59771,
                  _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
    assert t.pin_key == ("ARKMUSDT", "sell")
    assert t.is_external is False

def test_cycle_pinned_set_and_net_pnl():
    t1 = LiveTrade("ARKMUSDT", "Sell", 11.93, "rule_triggered", 0.1, 0.1, 1, _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
    t2 = LiveTrade("MIRAUSDT", "Sell", 10.44, "external", 0.1, 0.1, 2, _dt("2026-06-05T01:28:25"), _dt("2026-06-05T04:43:25"))
    c = Cycle("s1", _dt("2026-06-05T01:28:00"), 200.43, [t1, t2])
    assert c.pinned_set == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell")}
    assert round(c.live_net_pnl, 2) == 22.37
    assert t2.is_external is True

def test_report_pass_within_tolerance():
    r = ParityReport(602.61, 600.00, [], tolerance_pct=1.0)
    assert r.passed is True

def test_report_fail_outside_tolerance():
    r = ParityReport(602.61, 500.00, [], tolerance_pct=1.0)
    assert r.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/diagnostics/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.diagnostics.parity.models`.

- [ ] **Step 3: Write minimal implementation**

Create the two empty `__init__.py` files, then:

```python
# backend/diagnostics/parity/models.py
"""Dataclasses for the backtest-parity diagnostic harness."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LiveTrade:
    symbol: str
    side: str                 # "Buy"/"Sell" as stored in trades.side
    net_pnl: float
    close_reason: str
    entry_price: float
    exit_price: float | None
    scan_result_id: int | None
    opened_at: datetime
    closed_at: datetime | None

    @property
    def pin_key(self) -> tuple[str, str]:
        return (self.symbol, self.side.lower())

    @property
    def is_external(self) -> bool:
        return self.close_reason == "external"


@dataclass
class Cycle:
    scan_id: str
    signal_time: datetime
    base_capital: float
    live_trades: list[LiveTrade] = field(default_factory=list)

    @property
    def pinned_set(self) -> set[tuple[str, str]]:
        return {t.pin_key for t in self.live_trades}

    @property
    def live_net_pnl(self) -> float:
        return sum(t.net_pnl for t in self.live_trades)


@dataclass
class CycleComparison:
    scan_id: str
    signal_time: datetime
    live_net_pnl: float
    backtest_net_pnl: float
    live_equity_after: float
    backtest_equity_after: float

    @property
    def delta_pct(self) -> float:
        if self.live_equity_after == 0:
            return 0.0
        return (self.backtest_equity_after - self.live_equity_after) / self.live_equity_after * 100.0


@dataclass
class ParityReport:
    live_final_equity: float
    backtest_final_equity: float
    cycles: list[CycleComparison]
    tolerance_pct: float = 1.0

    @property
    def final_equity_delta_pct(self) -> float:
        if self.live_final_equity == 0:
            return 0.0
        return (self.backtest_final_equity - self.live_final_equity) / self.live_final_equity * 100.0

    @property
    def passed(self) -> bool:
        return abs(self.final_equity_delta_pct) <= self.tolerance_pct
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/diagnostics/test_models.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/diagnostics tests/backend/diagnostics
git commit -m "feat(backtest-parity): parity harness dataclasses"
```

---

## Task 2: Live-selection extractor (`extractor.py`)

**Goal:** Pure transform from DB rows → ordered list of `Cycle` objects (the oracle). No DB here; DB reads live in Task 4. This keeps the selection logic unit-testable.

**Files:**
- Create: `backend/diagnostics/parity/extractor.py`
- Test: `tests/backend/diagnostics/test_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/diagnostics/test_extractor.py
from datetime import datetime, timezone
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.models import Cycle

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

# Rows shaped like trades joined to scans.completed_at (the signal_time anchor).
TRADE_ROWS = [
    # cycle A (scan s1) — 2 closed trades
    dict(symbol="ARKMUSDT", side="Sell", net_pnl=11.93, close_reason="rule_triggered",
         entry_price=0.13392, exit_price=0.12986, scan_result_id=1, status="closed",
         base_capital=200.43, scan_id="s1", signal_time=_dt("2026-06-05T01:28:00"),
         opened_at=_dt("2026-06-05T01:28:15"), closed_at=_dt("2026-06-05T04:43:25")),
    dict(symbol="MIRAUSDT", side="Sell", net_pnl=10.44, close_reason="rule_triggered",
         entry_price=0.0636, exit_price=0.06191, scan_result_id=2, status="closed",
         base_capital=200.43, scan_id="s1", signal_time=_dt("2026-06-05T01:28:00"),
         opened_at=_dt("2026-06-05T01:28:25"), closed_at=_dt("2026-06-05T04:43:25")),
    # cycle B (scan s2) — later
    dict(symbol="EIGENUSDT", side="Sell", net_pnl=26.94, close_reason="rule_triggered",
         entry_price=0.17711, exit_price=0.16681, scan_result_id=3, status="closed",
         base_capital=234.02, scan_id="s2", signal_time=_dt("2026-06-05T06:40:00"),
         opened_at=_dt("2026-06-05T06:40:54"), closed_at=_dt("2026-06-05T08:19:56")),
    # an OPEN trade — must be excluded
    dict(symbol="MEGAUSDT", side="Sell", net_pnl=None, close_reason=None,
         entry_price=0.04727, exit_price=None, scan_result_id=9, status="open",
         base_capital=574.21, scan_id="s9", signal_time=_dt("2026-06-09T16:20:00"),
         opened_at=_dt("2026-06-09T16:20:26"), closed_at=None),
]

def test_build_cycles_groups_by_scan_excludes_open_and_orders():
    cycles = build_cycles(TRADE_ROWS)
    assert [c.scan_id for c in cycles] == ["s1", "s2"]      # open-only scan s9 dropped, chronological
    assert cycles[0].pinned_set == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell")}
    assert cycles[0].base_capital == 200.43
    assert round(cycles[0].live_net_pnl, 2) == 22.37
    assert all(t.closed_at is not None for c in cycles for t in c.live_trades)

def test_live_final_equity_compounds():
    from backend.diagnostics.parity.extractor import live_final_equity
    cycles = build_cycles(TRADE_ROWS)
    # first base_capital + sum of all closed net_pnl
    assert round(live_final_equity(cycles), 2) == round(200.43 + 22.37 + 26.94, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/diagnostics/test_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/diagnostics/parity/extractor.py
"""Build the live-selection oracle (ordered Cycles) from trade rows."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import LiveTrade, Cycle


def build_cycles(trade_rows: list[Mapping[str, Any]]) -> list[Cycle]:
    """Group CLOSED trade rows into chronological Cycles keyed by scan_id.

    Open trades (status != 'closed' or closed_at is None) are excluded — parity is
    measured over fully-closed cycles only.
    """
    by_scan: dict[str, list[LiveTrade]] = {}
    meta: dict[str, tuple] = {}  # scan_id -> (signal_time, base_capital)
    for r in trade_rows:
        if r.get("status") != "closed" or r.get("closed_at") is None:
            continue
        sid = r["scan_id"]
        by_scan.setdefault(sid, []).append(LiveTrade(
            symbol=r["symbol"], side=r["side"],
            net_pnl=float(r["net_pnl"]) if r.get("net_pnl") is not None else 0.0,
            close_reason=r.get("close_reason") or "",
            entry_price=float(r["entry_price"]),
            exit_price=float(r["exit_price"]) if r.get("exit_price") is not None else None,
            scan_result_id=r.get("scan_result_id"),
            opened_at=r["opened_at"], closed_at=r["closed_at"],
        ))
        if sid not in meta:
            meta[sid] = (r["signal_time"], float(r["base_capital"]))

    cycles = [
        Cycle(scan_id=sid, signal_time=meta[sid][0], base_capital=meta[sid][1],
              live_trades=sorted(trades, key=lambda t: t.opened_at))
        for sid, trades in by_scan.items()
    ]
    cycles.sort(key=lambda c: c.signal_time)
    return cycles


def live_final_equity(cycles: list[Cycle]) -> float:
    """First cycle's base_capital + Σ net_pnl across all closed trades.

    base_capital compounds prior realized PnL, so this equals the last cycle's
    base_capital + its own net_pnl — computed additively for robustness.
    """
    if not cycles:
        return 0.0
    start = cycles[0].base_capital
    return start + sum(c.live_net_pnl for c in cycles)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/diagnostics/test_extractor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/diagnostics/parity/extractor.py tests/backend/diagnostics/test_extractor.py
git commit -m "feat(backtest-parity): live-selection extractor (oracle)"
```

---

## Task 3: Selection shim (`shim.py`)

**Goal:** Restrict the engine's input `signals` list to exactly live's pinned `(scan_id, ticker, side)` set, so the engine opens the same symbols live did. This is the core fix that removes the unrecoverable selection variable. The engine still simulates everything else.

**Why this seam:** `BacktestEngine.run(config, signals, klines, ...)` groups `signals` by `scan_id` internally and runs its dedup/rank/filter per scan. If we pre-filter `signals` to only the pinned `(ticker, side)` per scan, the engine's selection logic has nothing else to choose — it opens the pinned symbols (subject to its own gates, which we expect to pass since live passed them). No engine fork; the engine's price/close/PnL/compound code stays the code under test.

**Files:**
- Create: `backend/diagnostics/parity/shim.py`
- Test: `tests/backend/diagnostics/test_shim.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/diagnostics/test_shim.py
from datetime import datetime, timezone
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.models import LiveTrade, Cycle

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _sig(scan_id, ticker, direction, score):
    return {"scan_id": scan_id, "ticker": ticker, "direction": direction,
            "score": score, "signal_time": _dt("2026-06-05T01:28:00"),
            "confidence": "high", "analysis_price": 1.0}

# Scan s1 candidate pool: 5 signals, all |score| 8/7 (a tie pool > max_trades)
SIGNALS = [
    _sig("s1", "ARKMUSDT", "sell", -8),
    _sig("s1", "MIRAUSDT", "sell", -8),
    _sig("s1", "PENDLEUSDT", "sell", -8),
    _sig("s1", "ZZZUSDT", "sell", -8),     # tied but NOT traded live
    _sig("s1", "WWWUSDT", "sell", -7),
]

def _cycle(scan_id, pins):
    trades = [LiveTrade(sym, side.title(), 1.0, "rule_triggered", 1.0, 1.0, i,
                        _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
              for i, (sym, side) in enumerate(pins)]
    return Cycle(scan_id, _dt("2026-06-05T01:28:00"), 200.43, trades)

def test_pin_signals_keeps_only_pinned_symbols():
    cycles = [_cycle("s1", [("ARKMUSDT", "sell"), ("MIRAUSDT", "sell"), ("PENDLEUSDT", "sell")])]
    out = pin_signals(SIGNALS, cycles)
    kept = {(s["ticker"], s["direction"]) for s in out}
    assert kept == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell"), ("PENDLEUSDT", "sell")}
    assert ("ZZZUSDT", "sell") not in kept     # tied-but-untraded is dropped

def test_pin_signals_matches_side_case_insensitively():
    # live side "Sell" must match scan_results direction "sell"
    cycles = [_cycle("s1", [("ARKMUSDT", "Sell")])]
    out = pin_signals(SIGNALS, cycles)
    assert {(s["ticker"], s["direction"]) for s in out} == {("ARKMUSDT", "sell")}

def test_pin_signals_drops_scans_with_no_cycle():
    # signals for a scan that has no pinned cycle are dropped entirely
    extra = SIGNALS + [_sig("s2", "FOOUSDT", "buy", 9)]
    cycles = [_cycle("s1", [("ARKMUSDT", "sell")])]
    out = pin_signals(extra, cycles)
    assert all(s["scan_id"] == "s1" for s in out)

def test_pin_signals_reports_missing_pins():
    # a pinned (symbol, side) with no matching signal is surfaced, not silently lost
    cycles = [_cycle("s1", [("ARKMUSDT", "sell"), ("NOSIGNALUSDT", "sell")])]
    out, missing = pin_signals(SIGNALS, cycles, return_missing=True)
    assert ("s1", "NOSIGNALUSDT", "sell") in missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/diagnostics/test_shim.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/diagnostics/parity/shim.py
"""Selection shim: pin the engine's input signals to live's actual trades."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import Cycle


def pin_signals(
    signals: list[Mapping[str, Any]],
    cycles: list[Cycle],
    return_missing: bool = False,
):
    """Filter `signals` to only those matching a pinned (scan_id, ticker, side).

    `signals` items are engine signal dicts (keys: scan_id, ticker, direction,
    score, signal_time, ...). `cycles` carries the pinned (symbol, lower-side) per
    scan. Matching normalizes side/direction to lowercase. Signals for scans with
    no cycle are dropped. If return_missing, also returns the set of pinned keys
    that had no matching signal (a data-integrity surface, never silent).
    """
    pinned_by_scan: dict[str, set[tuple[str, str]]] = {}
    for c in cycles:
        pinned_by_scan.setdefault(c.scan_id, set()).update(c.pinned_set)

    out: list[Mapping[str, Any]] = []
    matched: set[tuple[str, str, str]] = set()
    for s in signals:
        sid = s.get("scan_id")
        pins = pinned_by_scan.get(sid)
        if not pins:
            continue
        key = (s.get("ticker"), str(s.get("direction", "")).lower())
        if key in pins:
            out.append(s)
            matched.add((sid, key[0], key[1]))

    if not return_missing:
        return out

    missing: set[tuple[str, str, str]] = set()
    for sid, pins in pinned_by_scan.items():
        for sym, side in pins:
            if (sid, sym, side) not in matched:
                missing.add((sid, sym, side))
    return out, missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/diagnostics/test_shim.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/diagnostics/parity/shim.py tests/backend/diagnostics/test_shim.py
git commit -m "feat(backtest-parity): selection shim pins engine input to live trades"
```

---

## Task 4: Async DB access (`data_access.py`)

**Goal:** The only async/DB unit. Reads the live trades (oracle), the scan signals (engine input), and klines from the LOCAL db. Mirrors `BacktestService._load_signals` and `_load_klines` shapes so the engine receives identical inputs.

**Files:**
- Create: `backend/diagnostics/parity/data_access.py`
- Test: covered by the integration run in Task 6 (DB-dependent; no pure unit test). Add a light smoke test guarded by a `DATABASE_URL` check.

- [ ] **Step 1: Write the smoke test (skipped without DB)**

```python
# tests/backend/diagnostics/test_data_access_smoke.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PARITY_DB_SMOKE"), reason="set PARITY_DB_SMOKE=1 to run against local DB")

@pytest.mark.asyncio
async def test_fetch_live_trades_returns_51_closed():
    from backend.async_persistence import AsyncAnalysisDB
    from backend.diagnostics.parity.data_access import ParityDataAccess
    db = AsyncAnalysisDB(os.environ["DATABASE_URL"])
    await db.connect()
    try:
        da = ParityDataAccess(db)
        rows = await da.fetch_live_trades("75aecaa7-0f10-400b-a562-1ddd7ae6cf94",
                                          "2026-06-05", "2026-06-10")
        closed = [r for r in rows if r["status"] == "closed"]
        assert len(closed) == 51
    finally:
        await db.close()
```

- [ ] **Step 2: Run to verify it is collected and skipped**

Run: `python -m pytest tests/backend/diagnostics/test_data_access_smoke.py -v`
Expected: SKIPPED (1) — confirms import path resolves.

- [ ] **Step 3: Write implementation**

```python
# backend/diagnostics/parity/data_access.py
"""Async DB reads for the parity harness (local DB, read-only)."""
from __future__ import annotations
from datetime import datetime
from typing import Any

# Reuse the production signal/kline loaders' query shape so the engine gets
# byte-identical inputs to a real backtest.
_TRADES_SQL = """
    SELECT t.symbol, t.side, t.net_pnl, t.close_reason, t.entry_price, t.exit_price,
           t.scan_result_id, t.status, t.base_capital, t.opened_at, t.closed_at,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           sr.scan_id AS scan_id
    FROM trades t
    JOIN scan_results sr ON sr.id = t.scan_result_id
    JOIN scans s ON s.scan_id = sr.scan_id
    WHERE t.account_id = $1
      AND t.opened_at >= $2::timestamptz
      AND t.opened_at <  $3::timestamptz
    ORDER BY t.opened_at
"""

# Same SELECT/ORDER BY as BacktestService._load_signals "explicit" mode.
_SIGNALS_SQL = """
    SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           ar.completed_at::timestamptz AS analysis_completed_at,
           s.scan_id, sr.signal_source, sr.analysis_price
    FROM scan_results sr
    JOIN scans s ON sr.scan_id = s.scan_id
    LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
    WHERE s.scan_id = ANY($1)
      AND sr.status = 'completed'
      AND sr.direction IN ('buy', 'sell')
    ORDER BY signal_time, ABS(sr.score) DESC, ar.completed_at DESC NULLS LAST, sr.id
"""


class ParityDataAccess:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch_live_trades(self, account_id: str, start: str, end: str) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(_TRADES_SQL, account_id, start, end)
        return [dict(r) for r in rows]

    async def fetch_signals(self, scan_ids: list[str]) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(_SIGNALS_SQL, scan_ids)
        return [
            {
                "id": r["id"], "ticker": r["ticker"], "direction": r["direction"],
                "confidence": r["confidence"], "score": r["score"],
                "signal_time": r["signal_time"],
                "analysis_completed_at": r["analysis_completed_at"],
                "scan_id": r["scan_id"], "signal_source": r["signal_source"],
                "analysis_price": float(r["analysis_price"]) if r["analysis_price"] is not None else None,
            }
            for r in rows
        ]

    async def fetch_klines(self, kline_cache: Any, symbols: list[str],
                           start: datetime, end: datetime, interval: str = "5m") -> dict[str, list[dict]]:
        import asyncio
        symbols = sorted(set(symbols))
        results = await asyncio.gather(
            *(kline_cache.get_klines(sym, interval, start, end) for sym in symbols)
        )
        return {sym: series for sym, series in zip(symbols, results)}
```

- [ ] **Step 4: Run smoke test against local DB (manual gate)**

Run: `PARITY_DB_SMOKE=1 python -m pytest tests/backend/diagnostics/test_data_access_smoke.py -v`
Expected: PASS — 51 closed trades. (If it fails, Task 0 hydration is incomplete — fix before continuing.)

- [ ] **Step 5: Commit**

```bash
git add backend/diagnostics/parity/data_access.py tests/backend/diagnostics/test_data_access_smoke.py
git commit -m "feat(backtest-parity): async DB access for parity harness"
```

---

## Task 5: Parity reporter (`reporter.py`)

**Goal:** Pure function: given live `cycles` and the engine's `SimulationResult`, build per-cycle comparisons and a `ParityReport`. The engine-run wiring is in Task 6; the math is unit-tested here on a fixture.

**Files:**
- Create: `backend/diagnostics/parity/reporter.py`
- Test: `tests/backend/diagnostics/test_reporter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/diagnostics/test_reporter.py
from datetime import datetime, timezone
from backend.diagnostics.parity.reporter import build_report
from backend.diagnostics.parity.models import LiveTrade, Cycle

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _cycle(scan_id, base, pnls, t0):
    trades = [LiveTrade(f"S{i}", "Sell", p, "rule_triggered", 1.0, 1.0, i, t0, t0)
              for i, p in enumerate(pnls)]
    return Cycle(scan_id, t0, base, trades)

def test_build_report_matches_when_engine_equals_live():
    cycles = [
        _cycle("s1", 200.0, [10.0, 12.0], _dt("2026-06-05T01:28:00")),   # +22 -> 222
        _cycle("s2", 222.0, [26.0], _dt("2026-06-05T06:40:00")),         # +26 -> 248
    ]
    # engine_trades: closed-trade dicts as SimulationResult.trades yields them.
    engine_trades = [
        {"scan_id": "s1", "pnl": 10.0}, {"scan_id": "s1", "pnl": 12.0},
        {"scan_id": "s2", "pnl": 26.0},
    ]
    report = build_report(cycles, engine_trades, starting_capital=200.0, tolerance_pct=1.0)
    assert round(report.live_final_equity, 2) == 248.0
    assert round(report.backtest_final_equity, 2) == 248.0
    assert report.passed is True
    assert len(report.cycles) == 2
    assert round(report.cycles[0].backtest_net_pnl, 2) == 22.0

def test_build_report_fails_when_engine_diverges():
    cycles = [_cycle("s1", 200.0, [10.0, 12.0], _dt("2026-06-05T01:28:00"))]
    engine_trades = [{"scan_id": "s1", "pnl": -50.0}, {"scan_id": "s1", "pnl": 12.0}]
    report = build_report(cycles, engine_trades, starting_capital=200.0, tolerance_pct=1.0)
    assert report.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/diagnostics/test_reporter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/diagnostics/parity/reporter.py
"""Build the parity report: live cycles vs engine SimulationResult.trades."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import Cycle, CycleComparison, ParityReport
from backend.diagnostics.parity.extractor import live_final_equity


def build_report(
    cycles: list[Cycle],
    engine_trades: list[Mapping[str, Any]],
    starting_capital: float,
    tolerance_pct: float = 1.0,
) -> ParityReport:
    """Compare per-cycle live vs engine PnL and compound both equity curves."""
    bt_by_scan: dict[str, float] = {}
    for t in engine_trades:
        bt_by_scan[t.get("scan_id", "")] = bt_by_scan.get(t.get("scan_id", ""), 0.0) + float(t.get("pnl", 0.0))

    comparisons: list[CycleComparison] = []
    live_eq = starting_capital
    bt_eq = starting_capital
    for c in cycles:
        live_pnl = c.live_net_pnl
        bt_pnl = bt_by_scan.get(c.scan_id, 0.0)
        live_eq += live_pnl
        bt_eq += bt_pnl
        comparisons.append(CycleComparison(
            scan_id=c.scan_id, signal_time=c.signal_time,
            live_net_pnl=live_pnl, backtest_net_pnl=bt_pnl,
            live_equity_after=live_eq, backtest_equity_after=bt_eq,
        ))

    return ParityReport(
        live_final_equity=live_final_equity(cycles),
        backtest_final_equity=bt_eq,
        cycles=comparisons,
        tolerance_pct=tolerance_pct,
    )


def format_report(report: ParityReport) -> str:
    """Human-readable per-cycle table + headline. Used by the CLI."""
    lines = [
        f"{'cycle (scan)':<14} {'live_pnl':>10} {'bt_pnl':>10} {'live_eq':>10} {'bt_eq':>10} {'delta%':>8}",
        "-" * 66,
    ]
    for c in report.cycles:
        lines.append(f"{c.scan_id[:12]:<14} {c.live_net_pnl:>10.2f} {c.backtest_net_pnl:>10.2f} "
                     f"{c.live_equity_after:>10.2f} {c.backtest_equity_after:>10.2f} {c.delta_pct:>8.2f}")
    lines.append("-" * 66)
    lines.append(f"LIVE final equity:     {report.live_final_equity:.2f}")
    lines.append(f"BACKTEST final equity: {report.backtest_final_equity:.2f}")
    lines.append(f"FINAL DELTA: {report.final_equity_delta_pct:+.2f}%  "
                 f"=> {'PASS' if report.passed else 'FAIL'} (tol {report.tolerance_pct}%)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/diagnostics/test_reporter.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/diagnostics/parity/reporter.py tests/backend/diagnostics/test_reporter.py
git commit -m "feat(backtest-parity): parity reporter (per-cycle + final-equity delta)"
```

---

## Task 6: CLI wiring + BASELINE parity run (`run_parity.py`)

**Goal:** Wire extractor → shim → engine → reporter into a runnable CLI, then run it against local data to produce the **baseline measurement**: the final-equity delta with selection pinned but no engine fixes yet. This number tells us how much error remains after removing selection — it drives Task 7.

**Files:**
- Create: `backend/diagnostics/parity/run_parity.py`
- Output: append the baseline number to `docs/superpowers/specs/2026-06-10-selective-backtest-parity-design.md` §10.

- [ ] **Step 1: Write the CLI**

```python
# backend/diagnostics/parity/run_parity.py
"""CLI: replay an account's live selection through BacktestEngine and report parity.

Usage:
  python -m backend.diagnostics.parity.run_parity \
      --account 75aecaa7-0f10-400b-a562-1ddd7ae6cf94 \
      --start 2026-06-05 --end 2026-06-10
"""
from __future__ import annotations
import argparse
import asyncio
import os
from datetime import datetime, timezone

from backend.async_persistence import AsyncAnalysisDB
from backend.services.kline_cache_service import KlineCacheService
from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.data_access import ParityDataAccess
from backend.diagnostics.parity.extractor import build_cycles, live_final_equity
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import build_report, format_report

# Dad - Demo config under test (see plan Reference Facts).
CONFIG = {
    "leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
    "stop_loss_pct": 100, "max_drawdown_pct": 12, "smart_drawdown_close": True,
    "trailing_profit_pct": 2, "breakeven_timeout_hours": 12, "max_trade_duration_hours": 24,
    "min_score": 7, "confidence_filter": "moderate", "signal_sides": "both",
    "execution_mode": "batch", "fill_to_max_trades": True, "skip_if_positions_open": True,
    "adaptive_blacklist_enabled": True, "adaptive_blacklist_min_trades": 5,
    "adaptive_blacklist_max_win_rate": 30, "adaptive_blacklist_lookback_hours": 48,
    "target_goal_type": "profit_pct", "target_goal_value": 15, "max_price_drift_pct": 3,
    "max_same_sector": 2, "max_same_direction": 3, "direction": "straight",
    "fee_rate_pct": 0.055, "slippage_bps": 2, "simulation_interval": "5m",
}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--tolerance", type=float, default=1.0)
    args = ap.parse_args()

    db = AsyncAnalysisDB(os.environ["DATABASE_URL"])
    await db.connect()
    try:
        da = ParityDataAccess(db)
        kline_cache = KlineCacheService(db)

        trade_rows = await da.fetch_live_trades(args.account, args.start, args.end)
        cycles = build_cycles(trade_rows)
        if not cycles:
            print("No closed cycles found — check hydration (Task 0).")
            return
        scan_ids = [c.scan_id for c in cycles]
        signals = await da.fetch_signals(scan_ids)

        pinned, missing = pin_signals(signals, cycles, return_missing=True)
        if missing:
            print(f"WARNING: {len(missing)} pinned (scan,symbol,side) had no signal row: {sorted(missing)[:5]}...")

        symbols = sorted({s["ticker"] for s in pinned})
        klines = await da.fetch_klines(kline_cache, symbols, _dt(args.start), _dt(args.end), "5m")

        starting_capital = cycles[0].base_capital
        config = dict(CONFIG)
        config.update({"starting_capital": starting_capital,
                       "date_range_start": _dt(args.start), "date_range_end": _dt(args.end)})

        result = BacktestEngine().run(config, pinned, klines)

        report = build_report(cycles, result.trades, starting_capital, args.tolerance)
        print(format_report(report))
        print(f"\nEngine warnings: {result.warnings}")
        print(f"Engine filter_stats: {result.filter_stats}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the baseline**

Run:
```bash
python -m backend.diagnostics.parity.run_parity \
  --account 75aecaa7-0f10-400b-a562-1ddd7ae6cf94 --start 2026-06-05 --end 2026-06-10
```
Expected: a per-cycle table + a `FINAL DELTA: ±X%`. Record X (the baseline). Note any `missing` pins or `signals_no_kline` warnings — they indicate hydration gaps to fix before trusting the number.

- [ ] **Step 3: Interpret & record**

Append to design §10: the baseline delta, the per-cycle table, and which cycles exceed 1%. If `pinned` count ≠ 51, investigate the shim/extractor against those scans (the engine may have rejected a pinned signal via a gate live passed — e.g. price-drift on a stale candle, or `signals_no_kline`). This is the entry to Task 7.

- [ ] **Step 4: Commit**

```bash
git add backend/diagnostics/parity/run_parity.py docs/superpowers/specs/2026-06-10-selective-backtest-parity-design.md
git commit -m "feat(backtest-parity): CLI runner + baseline parity measurement"
```

---

## Task 7: Iterative engine-fix loop (systematic-debugging Phase 4)

**Goal:** Drive the final-equity delta to ≤ 1% by fixing engine gaps one at a time, each as a failing-first regression test. This task repeats until convergence (the reporter passes AND a re-run surfaces no new > 1% cycle). The golden suite is a hard gate on every fix.

**Files (per fix):** `backend/services/backtest_engine.py` (or `backtest_metrics.py` / `close_rule_evaluator.py`) + a new test in `tests/backend/`.

**Loop protocol (repeat for each gap, highest-PnL-impact cycle first):**

- [ ] **Step 1: Pick the worst cycle.** From the Task 6 report, take the cycle with the largest `|delta_pct|`. Pull its live trades vs the engine's trades for the same scan (symbols, entry/exit price, close_reason, pnl). Identify ONE divergence (e.g. engine closed via `max_duration` where live closed `external`; or entry fill price differs).

- [ ] **Step 2: Form ONE hypothesis.** State it concretely, e.g. "engine over-counts breakeven mass-close because it nets at candle-close, not at the live fee-buffer threshold." One variable.

- [ ] **Step 3: Write a failing regression test** in `tests/backend/` reproducing that single divergence with a minimal synthetic scan + klines (follow the pattern in `tests/backend/test_engine_advanced_rules.py`). Assert the engine's close_reason / pnl for the case.

- [ ] **Step 4: Run it — verify it fails** for the right reason.
Run: `python -m pytest tests/backend/<new_test>.py -v` → FAIL.

- [ ] **Step 5: Fix root cause** in the engine — minimal change, no bundled refactor.

- [ ] **Step 6: Verify the new test passes AND the golden suite is green.**
Run: `python -m pytest tests/backend/<new_test>.py tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py tests/backend/golden -v`
Expected: all PASS. If golden breaks, the fix changed the default path — investigate before continuing (the default path must stay byte-identical).

- [ ] **Step 7: Re-run the harness** (Task 6 Step 2). Record the new final-equity delta. If a previously-fine cycle now exceeds 1%, that's a new gap → loop again.

- [ ] **Step 8: Commit each fix atomically.**
```bash
git add backend/services/backtest_engine.py tests/backend/<new_test>.py
git commit -m "fix(backtest-engine): <one-line root cause> for live parity"
```

**Known candidate gaps (investigate in this order — see design §6):**
1. `external` closes (~25%): decide per-design whether to model via engine rules or treat as a bounded, quantified caveat. Document the residual they contribute.
2. Breakeven netting vs the post-`7c66050`/`420b9b4` live semantics (fail-closed zero-notional; buffer = Σ notional × 0.055% × 1.5).
3. Entry-fill basis: engine next-bar-open + slippage vs live `avg_fill_price`; confirm `base_capital`/compounding basis.
4. Per-cycle account-level close timing (all cycle positions close together, matching live `closed_at` clustering).

**Exit condition (⛔ STOP gate):** Loop ends only when the harness reports final-equity delta ≤ 1% AND a clean re-run shows no new > 1% cycle. Then proceed to Task 8.

---

## Task 8: Findings write-up + final validation

**Files:** `docs/superpowers/specs/2026-06-10-selective-backtest-parity-design.md` §10.

- [ ] **Step 1: Run the full diagnostics test suite.**
Run: `python -m pytest tests/backend/diagnostics tests/backend/test_golden_fingerprint.py tests/backend/test_backtest_golden.py tests/backend/golden tests/backend/test_backtest_engine.py -q`
Expected: all PASS.

- [ ] **Step 2: Run the harness one final time** and capture the passing report.

- [ ] **Step 3: Write §10 Findings:** baseline delta → final delta, the list of engine fixes landed (with one-line root causes), the quantified `external`-close residual, and any documented caveats. Include the final per-cycle table.

- [ ] **Step 4: Commit.**
```bash
git add docs/superpowers/specs/2026-06-10-selective-backtest-parity-design.md
git commit -m "docs(backtest-parity): findings — engine fixes + final parity result"
```

---

## Self-Review Notes

- **Spec coverage:** §1 root causes → Tasks 6–7 (measure + fix). §2 success criteria → reporter pass condition (Tasks 5–6) + exit gate (Task 7). §4 components → Tasks 1–6 (one task per unit). §6 investigation plan → Task 7 candidate gaps. §8 testing → per-task tests + golden gate. §7 scope (harness only, no product mode) → respected.
- **Open position:** excluded in `build_cycles` (Task 2) — matches design.
- **Type consistency:** `LiveTrade.pin_key`, `Cycle.pinned_set`, `pin_signals`, `build_cycles`, `live_final_equity`, `build_report`, `format_report` names are used consistently across tasks.
- **No placeholders:** every code step shows full code; every run step shows the command + expected result.
