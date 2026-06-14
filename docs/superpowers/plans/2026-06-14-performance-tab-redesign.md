# Performance Tab Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `/analytics` "Performance" tab so it reliably works by computing a cumulative-net-P&L curve and all KPIs directly from the `trades` table (exchange-independent), surfaced through a redesigned hero-strip + 4-tab neumorphic UI.

**Architecture:** A new `PerformanceService` computes everything from `trades` + `trading_cycles` (no dependency on the broken snapshot tables, no live Bybit call on the historical path). A new `/api/v1/performance` router exposes `overview`, `trades-breakdown`, `trades`, and `live`. The frontend replaces the 604-line `AnalyticsDashboard` with a composed `PerformanceDashboard` (control bar + sticky hero + `NeuTabs`) using TanStack Query. Delivered in 5 phases; **Phases 1–2 alone make the page work** and are independently shippable.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg (backend); pytest + pytest-asyncio in **strict** mode — every async test needs `@pytest.mark.asyncio` (backend tests); React 19 / TypeScript / TanStack Query + Router / Tailwind v4 / neumorphism design system / Recharts 3 (frontend); Vitest 4 + Testing Library 16 (frontend tests).

**Spec:** `docs/superpowers/specs/2026-06-14-performance-tab-redesign-design.md` (read it before starting — this plan implements it).

**Key conventions discovered in the codebase (follow these exactly):**
- DB access: `AsyncAnalysisDB` exposes `self.pool` (asyncpg). Query with `await self.pool.fetch("SELECT ... WHERE x=$1", val)` → list of `asyncpg.Record`; wrap rows as `dict(r)`. Use `fetchrow`/`fetchval` for single row/scalar.
- Routers: `APIRouter(prefix="/performance", tags=["performance"])`, registered in `backend/main.py` via `app.include_router(performance_router, prefix="/api/v1")` (lazy router imports are around line 763; the `include_router` calls run ~L771–796). Services reached via `request.app.state.<name>`.
- Service wiring: services are set on `app.state.<name>` during startup (e.g. `app.state.accounts_service`). The new service is set the same way.
- Pydantic v2 response models live in `backend/schemas/__init__.py` (`from pydantic import BaseModel, ConfigDict, Field`).
- Backend tests: `tests/backend/test_<name>.py`, classes grouping related cases, `unittest.mock.AsyncMock/MagicMock`, `@pytest.mark.asyncio` for async. Run: `python -m pytest tests/backend/test_x.py -x -q`.
- Frontend API client: namespace objects in `frontend/src/api/client.ts` (e.g. `export const tradesApi = { ... }`); `BASE_URL` is relative, Vite proxies `/api`.
- Frontend hooks: co-located `hooks/` dirs using `useQuery` with a module-level query-key object (see `frontend/src/components/trades/hooks/useTradeStats.ts`).
- Frontend tests: Vitest, run `cd frontend && npx vitest run <path>`; typecheck `npx tsc --noEmit`.

---

## File Structure

**Backend (new):**
- `backend/services/performance_service.py` — `PerformanceService`: all computation (canonical filter, D, curve, KPIs, breakdowns, live aggregation).
- `backend/routers/performance.py` — the 4 endpoints; thin, delegates to the service.
- `backend/schemas/__init__.py` (modify) — add `Performance*` response models.
- `backend/main.py` (modify) — import + register router; instantiate + set `app.state.performance_service`.
- `backend/async_persistence.py` (modify) — add 3 DB query helpers + 1 migration (partial index).

**Backend (tests):**
- `tests/backend/test_performance_service.py` — service math + edge cases.
- `tests/backend/test_performance_router.py` — endpoint shapes, validation, fail-soft.

**Frontend (new):**
- `frontend/src/components/analytics/PerformanceDashboard.tsx` — top-level composition (replaces `AnalyticsDashboard` usage).
- `frontend/src/components/analytics/PerformanceControlBar.tsx`
- `frontend/src/components/analytics/PerformanceHeroStrip.tsx`
- `frontend/src/components/analytics/tabs/OverviewTab.tsx`, `TradesTab.tsx`, `SignalsTab.tsx`, `LiveTab.tsx`
- `frontend/src/components/analytics/hooks/usePerformance.ts` — query hooks + query keys.
- `frontend/src/components/analytics/performanceTypes.ts` — TS types mirroring the API contract.

**Frontend (modify):**
- `frontend/src/api/client.ts` — add `performanceApi`.
- `frontend/src/components/analytics/{EquityCurveChart,DrawdownChart,DailyPnlChart,MonthlyPnlGrid,KpiCards}.tsx` — rewrite for new prop shapes.
- `frontend/src/lib/format.ts` — merge `backtest/format.ts` formatters in.
- `frontend/src/components/backtest/*` (7 importers) — repoint to `@/lib/format`.
- `frontend/src/routes/route-tree.tsx` — point `/analytics` wrapper at `PerformanceDashboard`.
- `frontend/src/components/accounts/AccountDetailView.tsx` — render `PerformanceDashboard` embedded.
- `frontend/src/App.tsx` — extend `shouldDehydrateQuery` to exclude `performance-live`.

**Frontend (tests):**
- `frontend/src/components/analytics/__tests__/` — migrate 4 existing test files + add new ones.

---

## PHASE 1 — Backend foundation (service + `/performance/overview` + schemas + migration)

**Outcome of this phase:** a fully tested backend that computes the overview (curve, drawdown, all KPIs) from `trades`, returns it from `GET /api/v1/performance/overview`, and renders correctly even with Bybit down. No frontend yet.

### Task 1.1: DB migration — partial index for portfolio-wide ordering

**Files:**
- Modify: `backend/async_persistence.py` (the `_MIGRATIONS` list)

- [ ] **Step 1: Find the migrations list and current max version**

Run: `grep -n "_MIGRATIONS\s*=\|_apply_migrations" backend/async_persistence.py` then read the last few entries of the `_MIGRATIONS` list. Format confirmed: `list[tuple[int, _MigrationSQL]]` where the SQL is either a string OR a callable — string tuples `(version, "SQL")` are valid and what you want here. **The current max version is 65** (verified), so the new migration is **version 66**. There is NO description field in the tuple.

- [ ] **Step 2: Append the new migration**

Add a new tuple `(66, "<SQL below>")` to the END of `_MIGRATIONS` (matching the existing string-tuple format). The SQL:

```sql
CREATE INDEX IF NOT EXISTS idx_trades_closed_at
ON trades (closed_at)
WHERE status = 'closed';
```

(The migration entries are `(version, "SQL")` tuples — no description field — so the new entry is just `(66, "CREATE INDEX ...")`.)

- [ ] **Step 3: Verify migrations still apply cleanly**

Run: `python -c "import backend.async_persistence"` (imports without syntax error)
Then run any existing migration/persistence test: `python -m pytest tests/backend/test_async_persistence_skipped.py -x -q` (expected: PASS or skip — confirms no import/registration break).

- [ ] **Step 4: Commit**

```bash
git add backend/async_persistence.py
git commit -m "feat(perf): add idx_trades_closed_at partial index migration"
```

### Task 1.2: DB helper — fetch the canonical closed-trade set for a scope

**Files:**
- Modify: `backend/async_persistence.py` (add method on `AsyncAnalysisDB`)
- Test: `tests/backend/test_performance_service.py` (created later; this task is DB-only, tested via the service in 1.5)

Per spec §4.1, the canonical filter is `status='closed' AND closed_at IS NOT NULL AND exit_price > 0`, joined to non-deleted, analytics-included accounts in scope, **with NO `parent_trade_id IS NULL` clause** (so partial-close children are included).

- [ ] **Step 1: Add the method**

Add to `AsyncAnalysisDB` (near `get_all_account_snapshots`, mirroring its scope-join + account_type pattern):

```python
async def get_performance_trades(
    self, *, account_ids: list[str] | None = None,
    account_type: str | None = None,
    start: "datetime | None" = None, end: "datetime | None" = None,
) -> list[dict]:
    """Canonical closed-trade set for performance analytics (spec §4.1).

    Includes partial-close children (NO parent_trade_id filter); excludes
    partially_closed parents and exit_price=0/external placeholder rows.
    Joined to active, non-deleted, analytics-included accounts.
    Ordered by closed_at ASC, id ASC (deterministic). `end` is exclusive.
    """
    sql = (
        "SELECT t.id, t.account_id, t.symbol, t.side, t.net_pnl, t.realized_pnl, "
        "t.realized_pnl_pct, t.base_capital, t.close_reason, t.strategy_kind, "
        "t.opened_at, t.closed_at, t.leverage "
        "FROM trades t "
        "JOIN trading_accounts ta ON ta.id = t.account_id "
        "WHERE t.status = 'closed' AND t.closed_at IS NOT NULL AND t.exit_price > 0 "
        "AND ta.deleted_at IS NULL AND ta.is_active = 1 "
        "AND ta.include_in_analytics = TRUE "
    )
    params: list = []
    if account_ids is not None:
        params.append(account_ids)
        sql += f"AND t.account_id = ANY(${len(params)}) "
    if account_type:
        params.append(account_type)
        sql += f"AND ta.account_type = ${len(params)} "
    if start is not None:
        params.append(start)
        sql += f"AND t.closed_at >= ${len(params)} "
    if end is not None:
        params.append(end)
        sql += f"AND t.closed_at < ${len(params)} "
    sql += "ORDER BY t.closed_at ASC, t.id ASC"
    rows = await self.pool.fetch(sql, *params)
    return [dict(r) for r in rows]
```

(Confirm `trading_accounts.is_active` is an integer `1` vs boolean `TRUE` by checking the existing `get_all_account_snapshots` query you read — match whichever it uses.)

- [ ] **Step 2: Verify import**

Run: `python -c "import backend.async_persistence"` → no error.

- [ ] **Step 3: Commit**

```bash
git add backend/async_persistence.py
git commit -m "feat(perf): add get_performance_trades canonical query"
```

### Task 1.3: DB helper — starting-equity components (cycles + first-trade fallback)

**Files:**
- Modify: `backend/async_persistence.py`

Per spec §3, `D` = Σ per-account earliest non-null `trading_cycles.initial_equity`, fallback first-trade `base_capital`. This task returns the raw per-account components; `compute_starting_equity` (Task 1.6) computes `D` + the contributing-account set from them.

- [ ] **Step 1: Add two methods**

```python
async def get_account_first_cycle_equity(self, account_ids: list[str]) -> dict[str, float]:
    """Per account: earliest non-null trading_cycles.initial_equity (by created_at).

    Returns {account_id: initial_equity} only for accounts that have one.
    """
    if not account_ids:
        return {}
    rows = await self.pool.fetch(
        "SELECT DISTINCT ON (account_id) account_id, initial_equity "
        "FROM trading_cycles "
        "WHERE account_id = ANY($1) AND initial_equity IS NOT NULL "
        "ORDER BY account_id, created_at ASC",
        account_ids,
    )
    return {r["account_id"]: float(r["initial_equity"]) for r in rows}

async def get_account_first_trade_capital(self, account_ids: list[str]) -> dict[str, float]:
    """Per account: first trade's base_capital (by opened_at), where non-null."""
    if not account_ids:
        return {}
    rows = await self.pool.fetch(
        "SELECT DISTINCT ON (account_id) account_id, base_capital "
        "FROM trades "
        "WHERE account_id = ANY($1) AND base_capital IS NOT NULL "
        "ORDER BY account_id, opened_at ASC NULLS LAST",
        account_ids,
    )
    return {r["account_id"]: float(r["base_capital"]) for r in rows}
```

- [ ] **Step 2: Verify import**

Run: `python -c "import backend.async_persistence"` → no error.

- [ ] **Step 3: Commit**

```bash
git add backend/async_persistence.py
git commit -m "feat(perf): add starting-equity component queries"
```

### Task 1.4: DB helper — eligible account ids for a scope

**Files:**
- Modify: `backend/async_persistence.py`

- [ ] **Step 1: Add the method**

```python
async def get_scope_account_ids(
    self, *, account_type: str | None = None, account_id: str | None = None,
) -> list[str]:
    """Resolve a performance scope to eligible account_ids.

    Active, non-deleted, analytics-included. account_type filters live/demo;
    account_id pins a single account. Currency note (spec §4.3): there is NO per-trade
    settle_coin column, so v1 ASSUMES all in-scope accounts settle in USDT and the page is
    labeled "USDT" (meta.currency). Mixed-settlement portfolios are a documented v1
    limitation — do not attempt a silent multi-currency sum. If a settle-coin signal is
    later added to trading_accounts, filter it here.
    """
    sql = (
        "SELECT id FROM trading_accounts "
        "WHERE deleted_at IS NULL AND is_active = 1 AND include_in_analytics = TRUE "
    )
    params: list = []
    if account_id:
        params.append(account_id)
        sql += f"AND id = ${len(params)} "
    if account_type:
        params.append(account_type)
        sql += f"AND account_type = ${len(params)} "
    sql += "ORDER BY id"
    rows = await self.pool.fetch(sql, *params)
    return [r["id"] for r in rows]
```

- [ ] **Step 2: Verify + commit**

Run: `python -c "import backend.async_persistence"` → no error.
```bash
git add backend/async_persistence.py
git commit -m "feat(perf): add get_scope_account_ids resolver"
```

---

### Task 1.5: PerformanceService — pure computation helpers (TDD)

**Files:**
- Create: `backend/services/performance_service.py`
- Test: `tests/backend/test_performance_service.py`

Build the math as **pure module-level functions** first (no DB, no I/O) so they're trivially testable. The orchestrating `PerformanceService` class (Task 1.6) calls them. All money summed with `Decimal`, coerced to `float` only at the boundary.

- [ ] **Step 1: Write failing tests for trade classification + sums**

Create `tests/backend/test_performance_service.py`:

```python
"""Unit tests for PerformanceService pure computation (spec §3/§4.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.performance_service import (
    classify_trades, compute_pnl_kpis,
)
# IMPORTANT (TDD import hygiene): import ONLY the helpers each task has implemented so far.
# A module-level import of a not-yet-defined name fails at pytest COLLECTION time (before
# any test runs), so `-k` can't bypass it and the task's "expect PASS" would be unreachable.
# Each later task (1.6, 1.7, 1.8, 1.9) extends THIS import line with the names it adds in
# its own Step 1, right before writing that task's tests. By Task 1.8 the import lists all
# 12 pure helpers; Task 1.9 additionally imports `PerformanceService`.


def _t(net_pnl, closed_at, *, realized=None, opened_at=None, base_capital=None,
       symbol="BTCUSDT", side="Buy", close_reason="take_profit",
       strategy_kind="trend", account_id="a1", _id=1):
    """Build a canonical-trade dict like get_performance_trades returns."""
    return {
        "id": _id, "account_id": account_id, "symbol": symbol, "side": side,
        "net_pnl": net_pnl, "realized_pnl": realized if realized is not None else net_pnl,
        "realized_pnl_pct": None, "base_capital": base_capital,
        "close_reason": close_reason, "strategy_kind": strategy_kind,
        "opened_at": opened_at, "closed_at": closed_at, "leverage": 20,
    }


class TestClassifyTrades:
    def test_win_loss_breakeven_null(self):
        trades = [_t(5.0, None, _id=1), _t(-3.0, None, _id=2),
                  _t(0.0, None, _id=3), _t(None, None, _id=4)]
        c = classify_trades(trades)
        assert c.win_count == 1
        assert c.loss_count == 1
        # breakeven (0) and null are neither win nor loss
        assert c.win_count + c.loss_count == 2
        assert len(trades) == 4  # but total_trades counts all 4 (asserted in compute_pnl_kpis)


class TestComputePnlKpis:
    def test_basic_reconciliation(self):
        # 2 wins (+4, +2), 1 loss (-3), 1 breakeven (0)
        trades = [_t(4.0, None, _id=1), _t(2.0, None, _id=2),
                  _t(-3.0, None, _id=3), _t(0.0, None, _id=4)]
        k = compute_pnl_kpis(trades)
        assert k["net_pnl"] == pytest.approx(3.0)
        assert k["total_trades"] == 4
        assert k["win_count"] == 2
        assert k["loss_count"] == 1
        assert k["win_rate"] == pytest.approx(50.0)  # 2/4
        assert k["avg_win"] == pytest.approx(3.0)     # (4+2)/2
        assert k["avg_loss"] == pytest.approx(-3.0)   # -3/1
        assert k["profit_factor"] == pytest.approx(2.0)  # 6/3
        assert k["expectancy"] == pytest.approx(0.75)    # 3/4

    def test_profit_factor_null_when_no_losses(self):
        k = compute_pnl_kpis([_t(4.0, None, _id=1)])
        assert k["profit_factor"] is None

    def test_null_net_pnl_coalesced_to_zero_in_sum(self):
        k = compute_pnl_kpis([_t(None, None, _id=1), _t(5.0, None, _id=2)])
        assert k["net_pnl"] == pytest.approx(5.0)
        assert k["total_trades"] == 2
        assert k["win_count"] == 1  # null is not a win
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: FAIL — `ModuleNotFoundError: backend.services.performance_service`.

- [ ] **Step 3: Implement the classification + KPI helpers**

Create `backend/services/performance_service.py` (start with these; more helpers appended in later steps):

```python
"""Performance analytics computed purely from the trades table (spec §3/§4.1).

Historical outputs (curve, drawdown, KPIs) read only `trades`/`trading_cycles`;
they never depend on snapshot tables or a live exchange call. Live-overlay
metrics (total_equity/unrealized_pnl/open_count) are sourced separately and
degrade to None. All money summed in Decimal, coerced to float at the boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from backend.services import portfolio_stats


def _npl(t: dict) -> Decimal:
    """COALESCE(net_pnl, 0) as Decimal."""
    v = t.get("net_pnl")
    return Decimal(str(v)) if v is not None else Decimal(0)


@dataclass
class TradeClassification:
    win_count: int
    loss_count: int


def classify_trades(trades: list[dict]) -> TradeClassification:
    """win = net_pnl>0, loss = net_pnl<0, breakeven/null = neither (spec §4.1)."""
    wins = sum(1 for t in trades if t.get("net_pnl") is not None and t["net_pnl"] > 0)
    losses = sum(1 for t in trades if t.get("net_pnl") is not None and t["net_pnl"] < 0)
    return TradeClassification(win_count=wins, loss_count=losses)


def compute_pnl_kpis(trades: list[dict]) -> dict[str, Any]:
    """Trade-derived KPIs over the canonical set (all numbers JSON-safe floats)."""
    total = len(trades)
    cls = classify_trades(trades)
    net = sum((_npl(t) for t in trades), Decimal(0))
    gross_realized = sum(
        (Decimal(str(t["realized_pnl"])) for t in trades if t.get("realized_pnl") is not None),
        Decimal(0),
    )
    winners = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None and t["net_pnl"] > 0]
    losers = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None and t["net_pnl"] < 0]
    gross_win = sum((Decimal(str(w)) for w in winners), Decimal(0))
    gross_loss = sum((Decimal(str(l)) for l in losers), Decimal(0))  # negative
    avg_win = float(gross_win / cls.win_count) if cls.win_count else None
    avg_loss = float(gross_loss / cls.loss_count) if cls.loss_count else None
    profit_factor = float(gross_win / abs(gross_loss)) if gross_loss != 0 else None
    expectancy = float(net / total) if total else None
    awl = (avg_win / abs(avg_loss)) if (avg_win is not None and avg_loss not in (None, 0)) else None
    pnls = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None]
    return {
        "net_pnl": float(net),
        "realized_pnl_gross": float(gross_realized),
        "win_rate": round(cls.win_count / total * 100, 4) if total else None,
        "win_count": cls.win_count,
        "loss_count": cls.loss_count,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_loss_ratio": awl,
        "best_trade": float(max(pnls)) if pnls else None,
        "worst_trade": float(min(pnls)) if pnls else None,
        "total_trades": total,
    }
```

Also add `from __future__` deps to `requirements` only if `dateutil` isn't present — check: `python -c "import dateutil"`. If missing, use a manual month/year delta instead of `relativedelta` (note in Task 1.7's window helper). Most installs have it via pandas; verify before relying on it.

- [ ] **Step 4: Run the tests — expect PASS**

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: PASS (the 4 tests written in Step 1).

- [ ] **Step 5: Commit**

```bash
git add backend/services/performance_service.py tests/backend/test_performance_service.py
git commit -m "feat(perf): trade classification + P&L KPIs (pure, tested)"
```

---

### Task 1.6: Starting-equity `D` + cumulative curve + drawdown (TDD)

**Files:**
- Modify: `backend/services/performance_service.py`
- Modify: `tests/backend/test_performance_service.py`

- [ ] **Step 1: Write failing tests**

First **extend the import line** at the top of `tests/backend/test_performance_service.py` to add this task's new helpers: `compute_starting_equity, compute_cumulative_curve, compute_drawdown_series`. Then append:
```python
class TestStartingEquity:
    def test_prefers_cycle_equity_one_value_per_account(self):
        # account a1 has a cycle equity (100), a2 has none → falls back to base_capital (50)
        D, contrib = compute_starting_equity(
            account_ids=["a1", "a2"],
            cycle_equity={"a1": 100.0},
            first_trade_capital={"a1": 999.0, "a2": 50.0},  # a1 ignores this (cycle wins)
        )
        assert D == pytest.approx(150.0)  # 100 + 50, NOT summed per-trade
        assert contrib == {"a1", "a2"}

    def test_null_account_excluded_returns_none_when_all_null(self):
        D, contrib = compute_starting_equity(account_ids=["a1"], cycle_equity={}, first_trade_capital={})
        assert D is None
        assert contrib == set()

    def test_partial_null_excludes_that_account(self):
        # a2 has no equity anywhere → excluded from D AND from the contributing set
        D, contrib = compute_starting_equity(
            account_ids=["a1", "a2"], cycle_equity={"a1": 100.0}, first_trade_capital={},
        )
        assert D == pytest.approx(100.0)
        assert contrib == {"a1"}  # a2 excluded → its P&L must NOT enter %/ratio numerators


class TestCumulativeCurve:
    def test_runs_from_zero_origin_ordered(self):
        trades = [_t(5.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-2.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2),
                  _t(3.0, datetime(2026, 5, 3, tzinfo=timezone.utc), _id=3)]
        curve = compute_cumulative_curve(trades)
        assert [round(p["cum_pnl"], 2) for p in curve] == [5.0, 3.0, 6.0]
        assert [round(p["peak"], 2) for p in curve] == [5.0, 5.0, 6.0]

    def test_null_pnl_coalesced(self):
        trades = [_t(None, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(4.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2)]
        curve = compute_cumulative_curve(trades)
        assert [round(p["cum_pnl"], 2) for p in curve] == [0.0, 4.0]


class TestDrawdownSeries:
    def test_peak_seeded_at_D_so_early_loss_registers(self):
        # D=100; first trade is a loss → drawdown must be negative, NOT 0
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2)]
        series, dd_max = compute_drawdown_series(trades, D=100.0)
        # equity_proxy: 90, 95 ; peak seeded at D=100 → 100,100
        assert series[0]["drawdown_pct"] == pytest.approx((90 - 100) / 100 * 100)  # -10.0
        assert dd_max["max_drawdown_pct"] == pytest.approx(-10.0)

    def test_naive_seed_would_hide_it_guard(self):
        # If peak were seeded at equity_proxy[0]=90 instead of D=100, first dd would be 0.
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1)]
        series, _ = compute_drawdown_series(trades, D=100.0)
        assert series[0]["drawdown_pct"] < 0  # proves D-seed, not equity_proxy[0]-seed

    def test_d_null_returns_abs_drawdown(self):
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1)]
        series, dd_max = compute_drawdown_series(trades, D=None)
        # absolute dollars under *_abs semantics; pct is None
        assert dd_max["max_drawdown_abs"] == pytest.approx(-10.0)
        assert dd_max["max_drawdown_pct"] is None
```

- [ ] **Step 2: Run — expect failures** (`compute_starting_equity`/`compute_cumulative_curve`/`compute_drawdown_series` undefined)

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: FAIL (ImportError on the new names).

- [ ] **Step 3: Implement the three helpers**

Append to `backend/services/performance_service.py`:

```python
def compute_starting_equity(
    *, account_ids: list[str], cycle_equity: dict[str, float],
    first_trade_capital: dict[str, float],
) -> tuple[float | None, set[str]]:
    """D = Σ per-account starting equity (cycle initial_equity, else first base_capital).

    ONE value per account; accounts with neither are EXCLUDED (spec §3). Returns
    (D, contributing_account_ids). D is None when no account contributes a positive
    value. The contributing set lets callers exclude a null-D account's P&L from the
    numerator of every %/ratio metric (spec §4.1 aggregate null-D rule) so its profit is
    never divided by other accounts' capital.
    """
    total = Decimal(0)
    contributing: set[str] = set()
    for aid in account_ids:
        val = cycle_equity.get(aid)
        if val is None:
            val = first_trade_capital.get(aid)
        if val is not None and val > 0:
            total += Decimal(str(val))
            contributing.add(aid)
    if not contributing or total <= 0:
        return None, set()
    return float(total), contributing


def compute_cumulative_curve(trades: list[dict]) -> list[dict]:
    """Cumulative net P&L from origin 0, per trade, with running peak (spec §4.1)."""
    out: list[dict] = []
    cum = Decimal(0)
    peak = Decimal(0)
    for t in trades:
        cum += _npl(t)
        peak = max(peak, cum)
        out.append({
            "t": t["closed_at"].isoformat() if hasattr(t["closed_at"], "isoformat") else t["closed_at"],
            "cum_pnl": float(cum),
            "peak": float(peak),
        })
    return out


def compute_drawdown_series(
    trades: list[dict], D: float | None,
) -> tuple[list[dict], dict]:
    """Drawdown from running peak of equity_proxy = D + cum_pnl, peak SEEDED AT D.

    Returns (series, max_drawdown). When D is present, series carries drawdown_pct
    and the second return is {"max_drawdown_pct": ..., "max_drawdown_abs": None}.
    When D is None, series carries drawdown_abs and the second return mirrors it.
    The peak is seeded at the pre-first-trade equity (D, or 0 when D is None) so an
    initial losing streak registers real drawdown (spec §4.1 — do NOT seed at proxy[0]).
    """
    base = Decimal(str(D)) if D is not None else Decimal(0)
    cum = Decimal(0)
    peak = base  # SEED AT D (not equity_proxy[0])
    series: list[dict] = []
    worst_pct = Decimal(0)
    worst_abs = Decimal(0)
    for t in trades:
        cum += _npl(t)
        proxy = base + cum
        peak = max(peak, proxy)
        ts = t["closed_at"].isoformat() if hasattr(t["closed_at"], "isoformat") else t["closed_at"]
        if D is not None and peak > 0:
            dd = (proxy - peak) / peak * Decimal(100)
            worst_pct = min(worst_pct, dd)
            series.append({"t": ts, "drawdown_pct": float(dd)})
        else:
            dd_abs = proxy - peak
            worst_abs = min(worst_abs, dd_abs)
            series.append({"t": ts, "drawdown_abs": float(dd_abs)})
    if D is not None:
        return series, {"max_drawdown_pct": float(worst_pct), "max_drawdown_abs": None}
    return series, {"max_drawdown_pct": None, "max_drawdown_abs": float(worst_abs)}
```

- [ ] **Step 4: Run — expect PASS**

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: PASS (all classification + curve + drawdown tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/performance_service.py tests/backend/test_performance_service.py
git commit -m "feat(perf): starting equity D, cumulative curve, drawdown (peak seeded at D)"
```

---

### Task 1.7: Daily-return series, risk ratios, max_consecutive, timeframe window (TDD)

**Files:**
- Modify: `backend/services/performance_service.py`
- Modify: `tests/backend/test_performance_service.py`

- [ ] **Step 1: Write failing tests**

First **extend the import line** with this task's new helpers: `build_daily_return_series, compute_risk_ratios, resolve_timeframe_window, compute_max_consecutive`. Then append:

```python
class TestMaxConsecutive:
    def test_per_trade_sequence_not_daily(self):
        # 3 wins in a row then a loss → max_consecutive_wins = 3, breakeven breaks streak
        trades = [_t(1.0, None, _id=1), _t(2.0, None, _id=2), _t(3.0, None, _id=3),
                  _t(-1.0, None, _id=4)]
        w, l = compute_max_consecutive(trades)
        assert w == 3
        assert l == 1

    def test_breakeven_breaks_streak(self):
        trades = [_t(1.0, None, _id=1), _t(0.0, None, _id=2), _t(2.0, None, _id=3)]
        w, _ = compute_max_consecutive(trades)
        assert w == 1


class TestDailyReturnSeries:
    def test_forward_filled_calendar_days_first_seeded_at_D(self):
        # trades on day1 (+10) and day3 (+5); day2 has no trade → 0% return that day
        D = 100.0
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 3, 8, tzinfo=timezone.utc), _id=2)]
        pairs = build_daily_return_series(trades, D=D)
        # returns (date, return_pct) pairs; day1 +10%, day2 (no trade) 0%, day3 ~4.545%
        assert len(pairs) == 3  # calendar-filled: 5/1, 5/2, 5/3
        rets = [r for (_d, r) in pairs]
        assert rets[0] == pytest.approx(10.0)
        assert rets[1] == pytest.approx(0.0)
        assert rets[2] == pytest.approx((115 - 110) / 110 * 100)


class TestRiskRatios:
    def test_null_below_10_trading_days(self):
        # only 2 trading days → ratios null
        D = 100.0
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 2, 8, tzinfo=timezone.utc), _id=2)]
        r = compute_risk_ratios(trades, D=D, max_drawdown_pct=-4.2)
        assert r["sharpe_ratio"] is None
        assert r["sortino_ratio"] is None
        assert r["calmar_ratio"] is None

    def test_calmar_uses_abs_drawdown_positive(self):
        # 10 trading days, all small positive returns, negative max_dd → positive Calmar
        D = 100.0
        trades = [_t(1.0, datetime(2026, 5, d, 8, tzinfo=timezone.utc), _id=d)
                  for d in range(1, 12)]  # 11 distinct trading days
        r = compute_risk_ratios(trades, D=D, max_drawdown_pct=-2.0)
        assert r["calmar_ratio"] is not None
        assert r["calmar_ratio"] > 0  # abs(max_dd) used

    def test_d_null_all_ratios_null(self):
        trades = [_t(1.0, datetime(2026, 5, d, 8, tzinfo=timezone.utc), _id=d)
                  for d in range(1, 12)]
        r = compute_risk_ratios(trades, D=None, max_drawdown_pct=None)
        assert r == {"sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None}


class TestTimeframeWindow:
    def test_all_has_no_lower_bound(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, a = resolve_timeframe_window("ALL", anchor)
        assert start is None
        assert a == anchor

    def test_1m_is_calendar_month(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("1M", anchor)
        assert start == datetime(2026, 5, 14, 12, tzinfo=timezone.utc)

    def test_1d_is_trailing_24h(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("1D", anchor)
        assert start == anchor - timedelta(hours=24)

    def test_ytd_is_jan1(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("YTD", anchor)
        assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            resolve_timeframe_window("7H", datetime(2026, 6, 14, tzinfo=timezone.utc))
```

- [ ] **Step 2: Run — expect failures**

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: FAIL (new names undefined).

- [ ] **Step 3: Implement the helpers**

Append to `backend/services/performance_service.py`:

```python
_MIN_TRADING_DAYS = 10


def compute_max_consecutive(trades: list[dict]) -> tuple[int, int]:
    """Longest win / loss streak over the PER-TRADE sequence (NOT the daily series).

    Trades are already ordered closed_at,id. Reuses portfolio_stats.max_consecutive
    by mapping each trade to +1 (win) / -1 (loss) / 0 (breakeven/null breaks streak).
    """
    seq = []
    for t in trades:
        v = t.get("net_pnl")
        seq.append(1.0 if (v is not None and v > 0) else (-1.0 if (v is not None and v < 0) else 0.0))
    wins = portfolio_stats.max_consecutive(seq, negative=False)
    losses = portfolio_stats.max_consecutive(seq, negative=True)
    return wins, losses


def _trading_day_count(trades: list[dict]) -> int:
    return len({t["closed_at"].date() for t in trades if t.get("closed_at") is not None})


def build_daily_return_series(trades: list[dict], D: float) -> list[tuple[Any, float]]:
    """Forward-filled UTC-calendar-day % return series for Sharpe/Sortino/Calmar.

    Built over ALL of `trades` (origin 0). Day set = every UTC calendar day from first to
    last trading day, inclusive. No-trade days carry equity forward → 0% return. First day
    seeded at D. Returns (date, return_pct) pairs so a caller can restrict to a window
    WITHOUT re-seeding the window's first day (spec §4.1 step 5).
    """
    if not trades or D is None or D <= 0:
        return []
    by_day: dict[Any, Decimal] = {}
    cum = Decimal(0)
    for t in trades:
        cum += _npl(t)
        by_day[t["closed_at"].date()] = cum  # last write per day = end-of-day cum
    days = sorted(by_day.keys())
    first, last = days[0], days[-1]
    base = Decimal(str(D))
    out: list[tuple[Any, float]] = []
    prev_proxy = base  # before first day
    cur_cum = Decimal(0)
    d = first
    one = timedelta(days=1)
    while d <= last:
        if d in by_day:
            cur_cum = by_day[d]
        proxy = base + cur_cum
        ret = float((proxy - prev_proxy) / prev_proxy * Decimal(100)) if prev_proxy > 0 else 0.0
        out.append((d, ret))
        prev_proxy = proxy
        d = d + one
    return out


def compute_risk_ratios(
    trades: list[dict], D: float | None, max_drawdown_pct: float | None,
    window: "tuple[datetime | None, datetime] | None" = None,
) -> dict[str, float | None]:
    """Sharpe/Sortino/Calmar from the daily-% series; None below 10 trading days,
    on D-null, or on degenerate (zero variance / zero drawdown). Calmar uses abs(dd).

    `trades` is the ALL-HISTORY set; the all-history daily-% series is built once and then
    restricted to days within `window` (spec §4.1 step 5 — first in-window day keeps its
    recurrence return, NOT a re-seed at D). When window is None, the whole series is used.
    The <10 gate counts distinct TRADING days within the window.
    """
    nulls = {"sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None}
    if D is None or D <= 0:
        return dict(nulls)
    pairs = build_daily_return_series(trades, D)  # [(date, return_pct), ...] all-history
    if window is not None:
        start, end = window
        sd = start.date() if start is not None else None
        ed = end.date()
        pairs = [(d, r) for (d, r) in pairs if (sd is None or d >= sd) and d < ed]
    series = [r for (_d, r) in pairs]
    # in-window trading-day count (distinct close-days that fall in the window)
    win_trades = trades
    if window is not None:
        start, end = window
        win_trades = [t for t in trades
                      if (start is None or t["closed_at"] >= start) and t["closed_at"] < end]
    if _trading_day_count(win_trades) < _MIN_TRADING_DAYS:
        return dict(nulls)
    if len(series) < 2:
        return dict(nulls)
    # zero-variance guard (helpers would return 0.0 → we want None)
    mean = sum(series) / len(series)
    if all(abs(r - mean) < 1e-12 for r in series):
        sharpe = sortino = None
    else:
        sharpe = portfolio_stats.calc_sharpe(series) or None  # 0.0 → None
        sortino = portfolio_stats.calc_sortino(series) or None
    # Calmar: None on no-drawdown; also map a 0.0 result (zero mean return) → None for parity.
    calmar = None if max_drawdown_pct in (None, 0) else (portfolio_stats.calc_calmar(series, abs(max_drawdown_pct)) or None)
    return {"sharpe_ratio": sharpe, "sortino_ratio": sortino, "calmar_ratio": calmar}


_TF = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


def resolve_timeframe_window(timeframe: str, anchor: datetime) -> tuple[datetime | None, datetime]:
    """Resolve a timeframe token to [start, anchor) in UTC (spec §4.2). ALL → start None."""
    if timeframe not in _TF:
        raise ValueError(f"unknown timeframe: {timeframe}")
    if timeframe == "ALL":
        return None, anchor
    if timeframe == "1D":
        return anchor - timedelta(hours=24), anchor
    if timeframe == "1W":
        return anchor - timedelta(days=7), anchor
    if timeframe == "1M":
        return anchor - relativedelta(months=1), anchor
    if timeframe == "3M":
        return anchor - relativedelta(months=3), anchor
    if timeframe == "1Y":
        return anchor - relativedelta(years=1), anchor
    if timeframe == "YTD":
        return datetime(anchor.year, 1, 1, tzinfo=timezone.utc), anchor
    raise ValueError(timeframe)  # unreachable
```

> **`dateutil` note:** if `python -c "import dateutil"` failed in Task 1.5, replace `relativedelta(months=n)` with a small manual helper that subtracts `n` calendar months (clamping the day), and `relativedelta(years=1)` with a year decrement. Add a test for Feb-29 / month-end clamping if you hand-roll it.

- [ ] **Step 4: Run — expect PASS**

Run: `python -m pytest tests/backend/test_performance_service.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/performance_service.py tests/backend/test_performance_service.py
git commit -m "feat(perf): daily-return series, risk ratios, max_consecutive, timeframe window"
```

---

### Task 1.8: Daily P&L + monthly P&L + drawdown duration helpers (TDD)

**Files:**
- Modify: `backend/services/performance_service.py`
- Modify: `tests/backend/test_performance_service.py`

- [ ] **Step 1: Write failing tests**

First **extend the import line** with this task's new helpers: `compute_daily_pnl, compute_monthly_pnl, compute_drawdown_duration` (the import now lists all 12 pure helpers). Then append:

```python
class TestDailyMonthlyPnl:
    def test_daily_pnl_grouped_by_utc_day(self):
        trades = [_t(2.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(1.0, datetime(2026, 5, 1, 20, tzinfo=timezone.utc), _id=2),
                  _t(-1.0, datetime(2026, 5, 2, 9, tzinfo=timezone.utc), _id=3)]
        daily = compute_daily_pnl(trades)
        assert daily == [{"date": "2026-05-01", "pnl": pytest.approx(3.0)},
                         {"date": "2026-05-02", "pnl": pytest.approx(-1.0)}]

    def test_monthly_pnl_with_return_pct(self):
        trades = [_t(8.0, datetime(2026, 5, 10, tzinfo=timezone.utc), _id=1)]
        monthly = compute_monthly_pnl(trades, D=160.0)
        assert monthly == [{"month": "2026-05", "pnl": pytest.approx(8.0),
                            "return_pct": pytest.approx(5.0)}]

    def test_monthly_return_pct_null_when_D_null(self):
        trades = [_t(8.0, datetime(2026, 5, 10, tzinfo=timezone.utc), _id=1)]
        monthly = compute_monthly_pnl(trades, D=None)
        assert monthly[0]["return_pct"] is None


class TestDrawdownDuration:
    def test_recovered_episode_floored_days(self):
        # peak at day1 (after +10), trough day2 (-6 → 4), recover day5 (+8 → 12 > 10 peak)
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-6.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2),
                  _t(8.0, datetime(2026, 5, 5, tzinfo=timezone.utc), _id=3)]
        days, recovered = compute_drawdown_duration(trades, D=100.0)
        assert recovered is True
        assert days == 4  # 5/1 peak → 5/5 recovery = 4 days, floored

    def test_unrecovered_uses_last_in_window(self):
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-6.0, datetime(2026, 5, 4, tzinfo=timezone.utc), _id=2)]
        days, recovered = compute_drawdown_duration(trades, D=100.0)
        assert recovered is False
        assert days == 3  # 5/1 peak → 5/4 last trade
```

- [ ] **Step 2: Run — expect failure**, then **Step 3: implement**:

```python
def compute_daily_pnl(trades: list[dict]) -> list[dict]:
    """Sum net_pnl by UTC close date, oldest first."""
    agg: dict[Any, Decimal] = {}
    for t in trades:
        d = t["closed_at"].date()
        agg[d] = agg.get(d, Decimal(0)) + _npl(t)
    return [{"date": d.isoformat(), "pnl": float(v)} for d, v in sorted(agg.items())]


def compute_monthly_pnl(trades: list[dict], D: float | None,
                        pct_trades: "list[dict] | None" = None) -> list[dict]:
    """Monthly grid. Dollar `pnl` sums `net_pnl` over `trades` (every in-scope account).
    `return_pct = month_pnl / D` is computed from `pct_trades` — the D-relative subset
    (accounts that contributed to D) so a null-D account's P&L is never divided by other
    accounts' capital (spec §4.1). Defaults `pct_trades = trades` when not given.
    """
    pct_trades = trades if pct_trades is None else pct_trades
    agg: dict[str, Decimal] = {}
    for t in trades:
        key = t["closed_at"].strftime("%Y-%m")
        agg[key] = agg.get(key, Decimal(0)) + _npl(t)
    pct_agg: dict[str, Decimal] = {}
    for t in pct_trades:
        key = t["closed_at"].strftime("%Y-%m")
        pct_agg[key] = pct_agg.get(key, Decimal(0)) + _npl(t)
    out = []
    for key, v in sorted(agg.items()):
        rp = (float(pct_agg.get(key, Decimal(0)) / Decimal(str(D)) * 100)
              if (D and D > 0) else None)
        out.append({"month": key, "pnl": float(v), "return_pct": rp})
    return out


def compute_drawdown_duration(trades: list[dict], D: float | None) -> tuple[int | None, bool]:
    """Duration (floored days) of the single deepest drawdown episode, + recovered flag.

    Walk equity_proxy = D + cum (peak seeded at D). Track the running peak's timestamp;
    find the trough with the largest drop from its preceding peak; duration = peak→
    (recovery that reclaims peak, else last trade), floored. Returns (None, True) when
    there is no drawdown or D is None.
    """
    if not trades or D is None:
        return None, True
    base = Decimal(str(D))
    cum = Decimal(0)
    peak = base
    peak_ts = trades[0]["closed_at"]  # pre-first-trade peak time ≈ first close
    worst_drop = Decimal(0)
    worst_peak_ts = None
    worst_trough_idx = -1
    for i, t in enumerate(trades):
        cum += _npl(t)
        proxy = base + cum
        if proxy >= peak:
            peak = proxy
            peak_ts = t["closed_at"]
        else:
            drop = peak - proxy
            if drop > worst_drop:
                worst_drop = drop
                worst_peak_ts = peak_ts
                worst_trough_idx = i
    if worst_trough_idx < 0 or worst_peak_ts is None:
        return 0, True
    # find recovery: first later trade whose proxy reclaims the worst episode's peak
    base_peak = None
    cum2 = Decimal(0)
    pk = base
    for i, t in enumerate(trades):
        cum2 += _npl(t)
        proxy = base + cum2
        pk = max(pk, proxy)
        if i == worst_trough_idx:
            base_peak = pk
    recovery_ts = None
    cum3 = Decimal(0)
    for i, t in enumerate(trades):
        cum3 += _npl(t)
        if i > worst_trough_idx and (base + cum3) >= base_peak:
            recovery_ts = t["closed_at"]
            break
    if recovery_ts is not None:
        return int((recovery_ts - worst_peak_ts).total_seconds() // 86400), True
    last_ts = trades[-1]["closed_at"]
    return int((last_ts - worst_peak_ts).total_seconds() // 86400), False
```

- [ ] **Step 4: Run — expect PASS.** Run: `python -m pytest tests/backend/test_performance_service.py -x -q`

- [ ] **Step 5: Commit**

```bash
git add backend/services/performance_service.py tests/backend/test_performance_service.py
git commit -m "feat(perf): daily/monthly P&L + drawdown duration helpers"
```

---

### Task 1.9: PerformanceService class — orchestrate `compute_overview` (TDD)

**Files:**
- Modify: `backend/services/performance_service.py`
- Modify: `tests/backend/test_performance_service.py`

The class wires the DB helpers to the pure functions and assembles the `overview` payload. Live-overlay (`total_equity`/`unrealized_pnl`/`open_count`) is fetched best-effort and degrades to `None` — for the historical path it is NOT required.

- [ ] **Step 1: Write failing test (DB + accounts service mocked)**

```python
class TestComputeOverview:
    @pytest.mark.asyncio
    async def test_overview_from_trades_no_live_call(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1, account_id="a1"),
                  _t(-4.0, datetime(2026, 5, 2, 8, tzinfo=timezone.utc), _id=2, account_id="a1"),
                  _t(6.0, datetime(2026, 5, 3, 8, tzinfo=timezone.utc), _id=3, account_id="a1")]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        # accounts_service deliberately raises → degraded live overlay, historical still works
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(side_effect=RuntimeError("bybit down"))

        svc = PerformanceService(db=db, accounts_service=accounts)
        result = await svc.compute_overview(scope="all", timeframe="ALL", anchor=anchor)

        assert result["kpis"]["net_pnl"] == pytest.approx(12.0)
        assert result["kpis"]["total_trades"] == 3
        # live overlay degraded → None, but historical present
        assert result["kpis"]["total_equity"] is None
        assert result["meta"]["degraded"] is True
        assert result["meta"]["starting_equity"] == pytest.approx(100.0)
        assert len(result["equity_curve"]) == 3
        assert result["meta"]["currency"] == "USDT"

    @pytest.mark.asyncio
    async def test_window_slices_not_rebases(self):
        """A 1M view shows the all-time line over the last month: the first in-window
        curve point carries the pre-window cumulative total (NOT a from-0 rebase)."""
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        # one OLD trade (+14 before the 1M window) + two IN-window (+10, then +2)
        all_trades = [
            _t(14.0, datetime(2026, 4, 1, 8, tzinfo=timezone.utc), _id=1, account_id="a1"),
            _t(10.0, datetime(2026, 5, 20, 8, tzinfo=timezone.utc), _id=2, account_id="a1"),
            _t(2.0, datetime(2026, 6, 1, 8, tzinfo=timezone.utc), _id=3, account_id="a1"),
        ]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades = AsyncMock(return_value=all_trades)  # service slices internally
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(side_effect=RuntimeError("down"))
        svc = PerformanceService(db=db, accounts_service=accounts)
        result = await svc.compute_overview(scope="all", timeframe="1M", anchor=anchor)
        # window = [2026-05-14, 2026-06-14): only the +10 and +2 trades are in-window
        assert result["kpis"]["net_pnl"] == pytest.approx(12.0)  # windowed KPI
        # but the curve is NOT rebased to 0: first in-window point = 14 + 10 = 24
        assert result["equity_curve"][0]["cum_pnl"] == pytest.approx(24.0)
        assert result["equity_curve"][-1]["cum_pnl"] == pytest.approx(26.0)

    @pytest.mark.asyncio
    async def test_single_account_empty_scope_does_not_leak_all(self):
        """An account-id scope that resolves to no eligible account returns empty —
        it must NOT fall through to all-accounts."""
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=[])  # bad/excluded id → []
        db.get_performance_trades = AsyncMock(return_value=[
            _t(99.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1, account_id="other")])
        db.get_account_first_cycle_equity = AsyncMock(return_value={})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="acc_bad", timeframe="ALL", anchor=anchor)
        # empty scope → get_performance_trades is never called with this scope's data
        assert result["kpis"]["total_trades"] == 0
        assert result["kpis"]["net_pnl"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_aggregate_null_D_account_does_not_inflate_return(self):
        """A null-D account's P&L must NOT be divided by other accounts' capital (spec §4.1):
        it counts in dollar net_pnl but is excluded from total_return_pct's numerator."""
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        # a1 has D=100 and +10 P&L; a2 has NO cycle and NO base_capital (null-D) and +90 P&L
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1, account_id="a1"),
                  _t(90.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2, account_id="a2")]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1", "a2"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})  # a2 absent
        db.get_account_first_trade_capital = AsyncMock(return_value={})            # a2 absent
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="all", timeframe="ALL", anchor=anchor)
        # dollar P&L counts BOTH accounts
        assert result["kpis"]["net_pnl"] == pytest.approx(100.0)
        # but total_return_pct uses ONLY a1's +10 over D=100 = 10%, NOT 100/100=100%
        assert result["kpis"]["total_return_pct"] == pytest.approx(10.0)
        assert result["meta"]["starting_equity"] == pytest.approx(100.0)
```

> **Note for the implementer:** in these tests `get_performance_trades` is mocked to return the full list regardless of `start`/`end`, because the service now fetches **all-history** (`start=None, end=None`) and slices in Python. The window-slice test asserts the service does the slicing correctly.

- [ ] **Step 2: Run — expect failure** (`PerformanceService` undefined).

- [ ] **Step 3: Implement the class**

Append to `backend/services/performance_service.py`:

```python
class PerformanceService:
    """Computes performance analytics from trades; live overlay is best-effort."""

    def __init__(self, db, accounts_service=None):
        self._db = db
        self._accounts = accounts_service

    async def _resolve_scope(self, scope: str) -> tuple[list[str], str | None, str | None]:
        """scope token → (account_ids, account_type, account_id)."""
        if scope == "all":
            return await self._db.get_scope_account_ids(), None, None
        if scope in ("live", "demo"):
            return await self._db.get_scope_account_ids(account_type=scope), scope, None
        # else: a single account id
        ids = await self._db.get_scope_account_ids(account_id=scope)
        return ids, None, scope

    async def _live_overlay(self, account_ids: list[str]) -> tuple[dict, bool]:
        """Best-effort live totals via accounts_service.get_dashboard. Degrades to None.

        NOTE: dashboard cards key the account PK as `id` (from `**acc`), unrealized P&L as
        `total_perp_upl`, and these money fields are STRINGS (e.g. "123.45") or None on a
        disabled/errored card — so coerce with float(x or 0). (Verified against
        accounts_service._fetch_card.)
        """
        nulls = {"total_equity": None, "unrealized_pnl": None, "open_count": None}
        if self._accounts is None or not account_ids:
            return nulls, True
        try:
            cards = await self._accounts.get_dashboard()
            wanted = set(account_ids)
            mine = [c for c in cards if c.get("id") in wanted]
            # if a card errored/disabled its money fields are None → treat the overlay as degraded
            if not mine or any(c.get("total_equity") is None for c in mine):
                return nulls, True
            eq = sum(float(c.get("total_equity") or 0) for c in mine)
            upl = sum(float(c.get("total_perp_upl") or 0) for c in mine)
            oc = sum(int(c.get("positions_count") or 0) for c in mine)
            return {"total_equity": eq, "unrealized_pnl": upl, "open_count": oc}, False
        except Exception:  # noqa: BLE001 — any live failure degrades the overlay only
            return nulls, True

    async def compute_overview(self, *, scope: str, timeframe: str, anchor: datetime) -> dict:
        account_ids, account_type, account_id = await self._resolve_scope(scope)
        # Guard: a single-account scope that resolved to NO eligible account must NOT
        # fall through to "all accounts". Sentinel [] (not None) means "empty scope".
        if account_id is not None and not account_ids:
            account_ids = []  # explicit empty — see _fetch_scoped below
        start, end = resolve_timeframe_window(timeframe, anchor)
        # starting equity D (DB-only, all-history components) + the set of accounts that
        # actually contributed to D (null-D accounts are excluded from %/ratio metrics).
        cycle_eq = await self._db.get_account_first_cycle_equity(account_ids) if account_ids else {}
        first_cap = await self._db.get_account_first_trade_capital(account_ids) if account_ids else {}
        D, d_accounts = compute_starting_equity(account_ids=account_ids, cycle_equity=cycle_eq,
                                                first_trade_capital=first_cap)
        # ALL-HISTORY trade set (origin 0); the window is applied by SLICING, never by
        # rebasing — so a 1M view shows the all-time line over the last month (spec §4.1).
        all_trades = await self._fetch_scoped(account_ids, account_id, account_type, start=None, end=None)
        win_trades = [t for t in all_trades
                      if (start is None or t["closed_at"] >= start) and t["closed_at"] < end]
        # D-RELATIVE subset: only trades from accounts that contributed to D. Used for every
        # metric whose denominator is D (total_return_pct, drawdown %, risk ratios) so a
        # null-D account's P&L is never divided by other accounts' capital (spec §4.1).
        all_d = [t for t in all_trades if t["account_id"] in d_accounts]
        win_d = [t for t in win_trades if t["account_id"] in d_accounts]
        # Dollar KPIs use the full WINDOWED in-scope subset (P&L counts every account).
        pnl = compute_pnl_kpis(win_trades)
        mc_w, mc_l = compute_max_consecutive(win_trades)
        # Raw cumulative-P&L curve covers ALL in-scope trades (dollars, no D needed);
        # slice to the window (carries the pre-window running total into the first point).
        full_curve = compute_cumulative_curve(all_trades)
        curve = [p for p in full_curve
                 if (start is None or _parse_ts(p["t"]) >= start) and _parse_ts(p["t"]) < end]
        # Drawdown % uses the D-relative subset (equity_proxy = D + cum needs a consistent base).
        full_dd, _ = compute_drawdown_series(all_d, D)
        dd_series = [p for p in full_dd
                     if (start is None or _parse_ts(p["t"]) >= start) and _parse_ts(p["t"]) < end]
        dd_max = _max_drawdown_over(dd_series, D)  # max over the WINDOW slice
        dd_days, dd_recovered = compute_drawdown_duration(win_d, D)
        # Risk ratios: all-history D-relative daily-% series, restricted to in-window days.
        ratios = compute_risk_ratios(all_d, D, dd_max.get("max_drawdown_pct"),
                                     window=(start, end))
        total_return_pct = (float(sum((_npl(t) for t in win_d), Decimal(0)) / Decimal(str(D)) * 100)
                            if (D and D > 0) else None)
        hold = [(t["closed_at"] - t["opened_at"]).total_seconds() / 3600
                for t in win_trades if t.get("opened_at")]
        overlay, degraded = await self._live_overlay(account_ids)
        kpis = {
            **pnl,
            "total_return_pct": total_return_pct,
            "max_consecutive_wins": mc_w, "max_consecutive_losses": mc_l,
            "avg_hold_time_hours": (sum(hold) / len(hold)) if hold else None,
            **dd_max, "drawdown_duration_days": dd_days, "drawdown_recovered": dd_recovered,
            **ratios, **overlay,
        }
        return {
            "kpis": kpis,
            "kpis_prev": await self._compute_prev(scope, timeframe, anchor, account_ids,
                                                  account_id, account_type, D, d_accounts),
            "equity_curve": curve,
            "equity_now": ({"t": anchor.isoformat(), "equity": overlay["total_equity"]}
                           if overlay["total_equity"] is not None else None),
            "drawdown_series": dd_series,
            "daily_pnl": compute_daily_pnl(win_trades),
            "monthly_pnl": compute_monthly_pnl(win_trades, D, pct_trades=win_d),
            "meta": {
                "currency": "USDT", "grouping_tz": "UTC",
                "trading_days": _trading_day_count(win_trades),
                "starting_equity": D, "return_basis": "recorded_history",
                "live_equity_available": overlay["total_equity"] is not None,
                "live_sourced": ["total_equity", "unrealized_pnl", "open_count"],
                "degraded": degraded,
            },
        }

    async def _fetch_scoped(self, account_ids, account_id, account_type, *, start, end):
        """Fetch the canonical trade set honoring the empty-scope sentinel.

        A single-account scope that resolved to no eligible account (account_id set but
        account_ids == []) returns [] — it must NOT fall through to all-accounts. For
        all/live/demo, account_ids is the resolved list (or empty list = no accounts).
        """
        if account_id is not None and not account_ids:
            return []  # explicit empty scope
        if account_id is None and account_type is None and not account_ids:
            return []  # 'all' resolved to zero eligible accounts
        return await self._db.get_performance_trades(
            account_ids=account_ids or None, account_type=account_type, start=start, end=end,
        )

    async def _compute_prev(self, scope, timeframe, anchor, account_ids, account_id,
                            account_type, D, d_accounts) -> dict | None:
        """Prior equal-length window KPIs for hero delta chips. None for ALL.

        `d_accounts` is the set of accounts that contributed to D — %/ratio metrics use only
        their trades (same aggregate null-D rule as compute_overview).
        """
        if timeframe == "ALL":
            return None
        start, _ = resolve_timeframe_window(timeframe, anchor)
        if start is None:
            return None
        prev_len = anchor - start
        prev_start, prev_end = start - prev_len, start  # equal-length window before `start`
        # all-history up to prev_end, then slice to [prev_start, prev_end) IN PYTHON (don't
        # rely on the DB's `end` bound — keeps this consistent with compute_overview's slicing).
        all_prev = await self._fetch_scoped(account_ids, account_id, account_type, start=None, end=prev_end)
        all_prev = [t for t in all_prev if t["closed_at"] < prev_end]
        prev_win = [t for t in all_prev if t["closed_at"] >= prev_start]
        all_prev_d = [t for t in all_prev if t["account_id"] in d_accounts]
        pnl = compute_pnl_kpis(prev_win)  # dollar/win KPIs over all in-scope
        # prior-window-END realized equity proxy = D + cum(D-relative trades through prev_end)
        cum_to_prev_end = float(sum((_npl(t) for t in all_prev_d), Decimal(0)))
        full_dd, _ = compute_drawdown_series(all_prev_d, D)
        prev_dd = [p for p in full_dd if p["t"] and prev_start <= _parse_ts(p["t"]) < prev_end]
        dd_max = _max_drawdown_over(prev_dd, D)
        ratios = compute_risk_ratios(all_prev_d, D, dd_max.get("max_drawdown_pct"),
                                     window=(prev_start, prev_end))
        return {
            "total_equity": (D + cum_to_prev_end) if D is not None else None,
            "net_pnl": pnl["net_pnl"], "win_rate": pnl["win_rate"],
            "sharpe_ratio": ratios["sharpe_ratio"],
            "max_drawdown_pct": dd_max.get("max_drawdown_pct"),
            "total_trades": pnl["total_trades"],
        }
```

The orchestrator references three module-level helpers — add them near the top of the file (after `_npl`):

```python
def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string (with Z or offset) to an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _max_drawdown_over(dd_series: list[dict], D: float | None) -> dict:
    """Recompute the max drawdown over a (sliced) drawdown series.

    Used so window/prev-window metrics reflect only the in-window slice. Honors the
    pct-vs-abs distinction: with D present, takes the min drawdown_pct; without D, the
    min drawdown_abs.
    """
    if not dd_series:
        return {"max_drawdown_pct": (0.0 if D is not None else None),
                "max_drawdown_abs": (None if D is not None else 0.0)}
    if D is not None:
        worst = min((p.get("drawdown_pct", 0.0) for p in dd_series), default=0.0)
        return {"max_drawdown_pct": float(worst), "max_drawdown_abs": None}
    worst = min((p.get("drawdown_abs", 0.0) for p in dd_series), default=0.0)
    return {"max_drawdown_pct": None, "max_drawdown_abs": float(worst)}
```

> **Note:** the slice carries the pre-window peak naturally because `compute_drawdown_series` was run over ALL history — each in-window point already holds the drawdown vs the all-history running peak. `_max_drawdown_over` then takes the worst within the slice.

- [ ] **Step 4: Run — expect PASS.** Run: `python -m pytest tests/backend/test_performance_service.py -x -q`

- [ ] **Step 5: Commit**

```bash
git add backend/services/performance_service.py tests/backend/test_performance_service.py
git commit -m "feat(perf): PerformanceService.compute_overview orchestrator"
```

---

### Task 1.10: Pydantic response models for overview

**Files:**
- Modify: `backend/schemas/__init__.py`

These Pydantic models document the typed contract and mirror the TS types (Task 2.2); they are the authoritative field list. Use `model_config = ConfigDict(extra="forbid")` (the file's convention) and `Optional[...]` for every nullable metric. **The router (Task 1.11) returns the raw service dict and deliberately does NOT set `response_model`** — `extra="forbid"` would reject the response at runtime if the service ever adds a field, turning an additive change into a 500. The models are the contract-of-record for the frontend and a structural reference for reviewers; if you later want runtime validation, construct `PerformanceOverviewResponse(**result)` inside the endpoint (which coerces/validates) rather than relying on FastAPI's `response_model` serialization.

- [ ] **Step 1: Add the models**

Append near `TradeStatsResponse` in `backend/schemas/__init__.py`:

```python
class PerformanceKpis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # live-overlay (None when degraded)
    total_equity: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    open_count: Optional[int] = None
    # trade-derived
    net_pnl: float
    realized_pnl_gross: float
    total_return_pct: Optional[float] = None
    win_rate: Optional[float] = None
    win_count: int
    loss_count: int
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    avg_win_loss_ratio: Optional[float] = None
    best_trade: Optional[float] = None
    worst_trade: Optional[float] = None
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_hold_time_hours: Optional[float] = None
    total_trades: int
    # curve-derived
    max_drawdown_pct: Optional[float] = None
    max_drawdown_abs: Optional[float] = None
    drawdown_duration_days: Optional[int] = None
    drawdown_recovered: Optional[bool] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None


class PerformanceKpisPrev(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_equity: Optional[float] = None
    net_pnl: Optional[float] = None
    win_rate: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    total_trades: int = 0


class CurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: str
    cum_pnl: float
    peak: float


class DrawdownPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: str
    drawdown_pct: Optional[float] = None
    drawdown_abs: Optional[float] = None


class DailyPnlPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    pnl: float


class MonthlyPnlPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str
    pnl: float
    return_pct: Optional[float] = None


class EquityNow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: str
    equity: float


class PerformanceMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str
    grouping_tz: str
    trading_days: int
    starting_equity: Optional[float] = None
    return_basis: str
    live_equity_available: bool
    live_sourced: List[str]
    degraded: bool


class PerformanceOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kpis: PerformanceKpis
    kpis_prev: Optional[PerformanceKpisPrev] = None
    equity_curve: List[CurvePoint]
    equity_now: Optional[EquityNow] = None
    drawdown_series: List[DrawdownPoint]
    daily_pnl: List[DailyPnlPoint]
    monthly_pnl: List[MonthlyPnlPoint]
    meta: PerformanceMeta
```

- [ ] **Step 2: Verify import**

Run: `python -c "from backend.schemas import PerformanceOverviewResponse; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/schemas/__init__.py
git commit -m "feat(perf): Performance* Pydantic response models"
```

### Task 1.11: Router — `GET /performance/overview` (TDD)

**Files:**
- Create: `backend/routers/performance.py`
- Test: `tests/backend/test_performance_router.py`

- [ ] **Step 1: Write failing router test**

Create `tests/backend/test_performance_router.py`. Mirror the structure of `tests/backend/test_accounts_router.py` (read it first for the app/TestClient fixture pattern — use the same fixture the repo already uses). The test sets a mocked `app.state.performance_service` and asserts the endpoint shape + validation:

```python
"""Router tests for /api/v1/performance/overview."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.performance import router as perf_router


def _app(svc):
    app = FastAPI()
    app.state.performance_service = svc
    app.include_router(perf_router, prefix="/api/v1")
    return app


def test_overview_returns_payload():
    svc = MagicMock()
    svc.compute_overview = AsyncMock(return_value={
        "kpis": {"net_pnl": 12.5, "realized_pnl_gross": 14.1, "win_count": 10,
                 "loss_count": 6, "max_consecutive_wins": 4, "max_consecutive_losses": 2,
                 "total_trades": 16},
        "kpis_prev": None, "equity_curve": [], "equity_now": None,
        "drawdown_series": [], "daily_pnl": [], "monthly_pnl": [],
        "meta": {"currency": "USDT", "grouping_tz": "UTC", "trading_days": 0,
                 "starting_equity": 174.0, "return_basis": "recorded_history",
                 "live_equity_available": False,
                 "live_sourced": ["total_equity", "unrealized_pnl", "open_count"],
                 "degraded": True},
    })
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=ALL")
    assert r.status_code == 200
    assert r.json()["kpis"]["net_pnl"] == 12.5

def test_overview_unknown_timeframe_422():
    svc = MagicMock()
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=7H")
    assert r.status_code == 422

def test_overview_service_missing_503():
    app = FastAPI()
    app.include_router(perf_router, prefix="/api/v1")
    client = TestClient(app)
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=ALL")
    assert r.status_code == 503
```

(Confirm `fastapi.testclient` + a real `from datetime import datetime, timezone` anchor is acceptable; the router computes `anchor = datetime.now(timezone.utc)` internally — the test does not pin it.)

- [ ] **Step 2: Run — expect failure** (`backend.routers.performance` missing).

- [ ] **Step 3: Implement the router**

Create `backend/routers/performance.py`:

```python
"""Performance analytics router — trades-derived KPIs, curve, breakdowns, live."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/performance", tags=["performance"])

_VALID_TIMEFRAMES = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


def _svc(request: Request):
    s = getattr(request.app.state, "performance_service", None)
    if s is None:
        raise HTTPException(503, detail="Performance service not available")
    return s


def _validate_timeframe(tf: str) -> str:
    if tf not in _VALID_TIMEFRAMES:
        raise HTTPException(422, detail=f"timeframe must be one of {sorted(_VALID_TIMEFRAMES)}")
    return tf


@router.get("/overview")
async def get_overview(
    request: Request,
    scope: str = Query("all"),
    timeframe: str = Query("ALL"),
):
    svc = _svc(request)
    _validate_timeframe(timeframe)
    anchor = datetime.now(timezone.utc)
    return await svc.compute_overview(scope=scope, timeframe=timeframe, anchor=anchor)
```

- [ ] **Step 4: Run — expect PASS.** Run: `python -m pytest tests/backend/test_performance_router.py -x -q`

- [ ] **Step 5: Commit**

```bash
git add backend/routers/performance.py tests/backend/test_performance_router.py
git commit -m "feat(perf): /performance/overview router"
```

### Task 1.12: Wire the service + router into `main.py`

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Instantiate the service on app.state (unconditionally)**

The historical path needs no Bybit, so the service must exist even when `ACCOUNTS_ENCRYPTION_KEY` is unset. Locate the two relevant spots with:
```
grep -n "app.state.accounts_service = AccountsService\|app.state.db = \|^\s*db = \|ACCOUNTS_ENCRYPTION_KEY" backend/main.py
```
Then:

(a) **Inside** the `ACCOUNTS_ENCRYPTION_KEY` block, immediately AFTER the line `app.state.accounts_service = AccountsService(...)` (~line 369), add:
```python
from backend.services.performance_service import PerformanceService
app.state.performance_service = PerformanceService(
    db=db, accounts_service=app.state.accounts_service,
)
```

(b) To cover the no-key path, ALSO add — right after the whole `if os.environ.get("ACCOUNTS_ENCRYPTION_KEY"):` block ends (find its dedent) — a guard that creates the service without an overlay if it wasn't created above:
```python
if not hasattr(app.state, "performance_service"):
    from backend.services.performance_service import PerformanceService
    app.state.performance_service = PerformanceService(db=db, accounts_service=None)
```

This guarantees `app.state.performance_service` always exists; the live overlay is wired only when accounts_service is available (and degrades to "—" otherwise).

- [ ] **Step 2: Register the router**

In the router-registration block (lazy imports ~L763, `include_router` calls ~L771–796 — find them with `grep -n "include_router\|from backend.routers" backend/main.py`), add the lazy import alongside the others:
```python
from backend.routers.performance import router as performance_router
```
and the registration alongside the others:
```python
app.include_router(performance_router, prefix="/api/v1")
```

- [ ] **Step 3: Verify the app imports and router is mounted**

Run: `python -c "import backend.main"` → no error.
Run the router test again to be safe: `python -m pytest tests/backend/test_performance_router.py -x -q` → PASS.

- [ ] **Step 4: Run the full new backend test suite**

Run: `python -m pytest tests/backend/test_performance_service.py tests/backend/test_performance_router.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(perf): wire PerformanceService + router into app"
```

---

**⛔ PHASE 1 GATE:** All of `test_performance_service.py` and `test_performance_router.py` pass; `python -c "import backend.main"` succeeds. The backend can serve `/api/v1/performance/overview` computed entirely from trades. Do not start Phase 2 until this gate is green.

---

## PHASE 2 — Overview UI + reliability (the working page)

**Outcome:** `/analytics` renders the new `PerformanceDashboard` — control bar (scope + timeframe), sticky hero strip, and an Overview tab (cumulative-P&L chart, drawdown, daily P&L, monthly heatmap, KPI grid) — fed by `/performance/overview` via TanStack Query, with real loading/empty/error states, working at low data volumes, and the account-detail embedding preserved. **After this phase the page works and looks good.**

Run frontend commands from `frontend/`. Typecheck: `npx tsc --noEmit`. Test: `npx vitest run <path>`. Build: `npm run build`.

### Task 2.1: Merge `backtest/format.ts` into `lib/format.ts`

**Files:**
- Modify: `frontend/src/lib/format.ts` (add the backtest formatters)
- Delete: `frontend/src/components/backtest/format.ts` (after repointing imports)
- Modify (7 importers): `frontend/src/components/backtest/{BacktestComparePage,BacktestAnalysisTab,BacktestListPage,BacktestResultsPage,MetricsGrid,TradeListTable}.tsx` + `frontend/src/components/backtest/__tests__/format.test.ts`

`lib/format.ts` already exists with `formatDuration`/`formatDurationBetween`/`formatDateTimeLabel`. `backtest/format.ts` exports a disjoint set (`formatUsd`, `formatPct`, `formatRatio`, `formatHours`, `formatDateTime`, `formatInt`, `formatCloseReason`, `signOf`, `pnlColorClass`, `NA`, `DASH`, `TH_CLASS`, `TH_CLASS_RIGHT`, `PNL_NEGATIVE_CLASS`, `PNL_POSITIVE_CLASS`). No name collisions — verified.

- [ ] **Step 1: Append the backtest formatters into `lib/format.ts`**

Copy the full body of `frontend/src/components/backtest/format.ts` (all exports listed above) and paste it at the end of `frontend/src/lib/format.ts`. Keep both files' existing exports. (There is a near-duplicate date formatter — `formatDateTimeLabel` (locale) vs `formatDateTime` (ISO slice); keep BOTH under their existing names, they are not collisions.)

- [ ] **Step 2: Repoint the 7 importers**

In each of the 7 files, change `from "./format"` (or `from "@/components/backtest/format"`) to `from "@/lib/format"`.

Run to find exact import lines: `grep -rn "from \"./format\"\|backtest/format" src/components/backtest/`

- [ ] **Step 3: Delete the old module**

```bash
rm src/components/backtest/format.ts
```

- [ ] **Step 4: Typecheck + run backtest tests**

Run: `npx tsc --noEmit` → no errors.
Run: `npx vitest run src/components/backtest/__tests__/format.test.ts` → PASS (after repointing the test's import to `@/lib/format`).

- [ ] **Step 5: Commit**

```bash
git add src/lib/format.ts src/components/backtest/
git commit -m "refactor(perf): merge backtest formatters into lib/format"
```

### Task 2.2: TypeScript types mirroring the API contract

**Files:**
- Create: `frontend/src/components/analytics/performanceTypes.ts`

- [ ] **Step 1: Write the types** (exact field names from spec §7 / Task 1.10 models):

```typescript
export type PerformanceScope = "all" | "live" | "demo" | string; // string = account id
export type PerformanceTimeframe = "1D" | "1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL";

export interface PerformanceKpis {
  total_equity: number | null;
  unrealized_pnl: number | null;
  open_count: number | null;
  net_pnl: number;
  realized_pnl_gross: number;
  total_return_pct: number | null;
  win_rate: number | null;
  win_count: number;
  loss_count: number;
  profit_factor: number | null;
  expectancy: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  avg_win_loss_ratio: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_hold_time_hours: number | null;
  total_trades: number;
  max_drawdown_pct: number | null;
  max_drawdown_abs: number | null;
  drawdown_duration_days: number | null;
  drawdown_recovered: boolean | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
}

export interface PerformanceKpisPrev {
  total_equity: number | null;
  net_pnl: number | null;
  win_rate: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  total_trades: number;
}

export interface CurvePoint { t: string; cum_pnl: number; peak: number; }
export interface DrawdownPoint { t: string; drawdown_pct?: number | null; drawdown_abs?: number | null; }
export interface DailyPnlPoint { date: string; pnl: number; }
export interface MonthlyPnlPoint { month: string; pnl: number; return_pct: number | null; }
export interface EquityNow { t: string; equity: number; }

export interface PerformanceMeta {
  currency: string;
  grouping_tz: string;
  trading_days: number;
  starting_equity: number | null;
  return_basis: string;
  live_equity_available: boolean;
  live_sourced: string[];
  degraded: boolean;
}

export interface PerformanceOverview {
  kpis: PerformanceKpis;
  kpis_prev: PerformanceKpisPrev | null;
  equity_curve: CurvePoint[];
  equity_now: EquityNow | null;
  drawdown_series: DrawdownPoint[];
  daily_pnl: DailyPnlPoint[];
  monthly_pnl: MonthlyPnlPoint[];
  meta: PerformanceMeta;
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit` → no errors.
```bash
git add src/components/analytics/performanceTypes.ts
git commit -m "feat(perf): performance API TypeScript types"
```

### Task 2.3: API client — `performanceApi`

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add the namespace object** (follow the existing `tradesApi` pattern — read it at line 1492 for the exact `request`/`mutate` helper used):

```typescript
import type { PerformanceOverview } from "@/components/analytics/performanceTypes";

export const performanceApi = {
  getOverview: (scope: string, timeframe: string, signal?: AbortSignal) =>
    request<PerformanceOverview>(
      buildQuery("/api/v1/performance/overview", { scope, timeframe }),
      undefined,
      signal,
    ),
};
```

(The real GET helper is `request<T>(path, init?, signal?, timeoutMs?)` — pass `undefined` for `init` and the `signal` third, exactly as `accountsApi.list` does at client.ts:957–965. `buildQuery(path, params)` is the existing query-string helper used throughout the file; reuse it instead of hand-building the URL.)

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit` → no errors.
```bash
git add src/api/client.ts
git commit -m "feat(perf): performanceApi client"
```

### Task 2.4: TanStack Query hooks + query keys

**Files:**
- Create: `frontend/src/components/analytics/hooks/usePerformance.ts`

- [ ] **Step 1: Write the hook + keys**

```typescript
import { useQuery } from "@tanstack/react-query";
import { performanceApi } from "@/api/client";

export const performanceKeys = {
  overview: (scope: string, timeframe: string) =>
    ["performance-overview", scope, timeframe] as const,
};

export function usePerformanceOverview(scope: string, timeframe: string) {
  return useQuery({
    queryKey: performanceKeys.overview(scope, timeframe),
    queryFn: ({ signal }) => performanceApi.getOverview(scope, timeframe, signal),
    staleTime: 60_000, // historical: 60s
  });
}
```

(Live-tab keys are added in Phase 5 with prefix `"performance-live"`, which the App.tsx predicate in Task 2.5 excludes from persistence.)

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit` → no errors.
```bash
git add src/components/analytics/hooks/usePerformance.ts
git commit -m "feat(perf): usePerformanceOverview hook + query keys"
```

### Task 2.5: Exclude `performance-live` from query persistence

**Files:**
- Modify: `frontend/src/App.tsx` (the `shouldDehydrateQuery` predicate, ~line 180)

The Live tab (Phase 5) must not have its stale unrealized-P&L restored from sessionStorage. Extend the existing predicate now so it's ready.

- [ ] **Step 1: Edit the predicate**

Change:
```typescript
shouldDehydrateQuery: (query) =>
  query.state.status === "success" && query.queryKey[0] !== "proxy-models",
```
to:
```typescript
shouldDehydrateQuery: (query) =>
  query.state.status === "success" &&
  query.queryKey[0] !== "proxy-models" &&
  query.queryKey[0] !== "performance-live",
```

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit` → no errors.
```bash
git add src/App.tsx
git commit -m "feat(perf): exclude performance-live queries from persistence"
```

---

### Task 2.6: Rewrite the four chart components for new prop shapes (TDD)

**Files:**
- Modify: `frontend/src/components/analytics/EquityCurveChart.tsx`, `DrawdownChart.tsx`, `DailyPnlChart.tsx`, `MonthlyPnlGrid.tsx`
- Modify (migrate): `frontend/src/components/analytics/__tests__/Charts.test.tsx`, `DailyPnlChart.test.tsx`, `MonthlyPnlGrid.test.tsx` (the 4th existing test, `KpiCards.test.tsx`, is migrated in Task 2.7 — note that `KpiCards.tsx` is rewritten there, NOT here, so don't touch it in this task)

Each chart currently takes `snapshots: DailySnapshot[]`. Rewrite each to take the new series type. Keep the Recharts/CSS-var visual scaffolding.

- [ ] **Step 1: Migrate the existing tests to new props (write the failing tests first)**

Read each existing test (`Charts.test.tsx` etc.) to see what it asserts, then rewrite it to pass the new prop shapes. Example for `EquityCurveChart` (inside `Charts.test.tsx`):

```typescript
import { render } from "@testing-library/react";
import { EquityCurveChart } from "../EquityCurveChart";
import type { CurvePoint } from "../performanceTypes";

it("renders cumulative-P&L curve from CurvePoint[]", () => {
  const data: CurvePoint[] = [
    { t: "2026-05-01T08:00:00Z", cum_pnl: 5, peak: 5 },
    { t: "2026-05-02T08:00:00Z", cum_pnl: 3, peak: 5 },
  ];
  const { container } = render(<EquityCurveChart data={data} />);
  expect(container.querySelector("svg")).toBeTruthy();
});

it("renders an empty-state node when data is empty", () => {
  const { container } = render(<EquityCurveChart data={[]} />);
  expect(container.textContent).toContain("No"); // empty hint
});
```

Write analogous migrated tests for `DrawdownChart` (prop `data: DrawdownPoint[]`), `DailyPnlChart` (`data: DailyPnlPoint[]`), `MonthlyPnlGrid` (`data: MonthlyPnlPoint[]`).

- [ ] **Step 2: Run — expect failures** (props changed, components not yet updated)

Run: `npx vitest run src/components/analytics/__tests__/Charts.test.tsx`
Expected: FAIL (type/prop mismatch).

- [ ] **Step 3: Rewrite `EquityCurveChart.tsx`**

```typescript
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceDot, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { CurvePoint, EquityNow } from "./performanceTypes";

interface Props {
  data: CurvePoint[];
  /** optional absolute-equity offset D for the secondary "your equity" axis */
  startingEquity?: number | null;
  equityNow?: EquityNow | null;
}

export function EquityCurveChart({ data, startingEquity, equityNow }: Props) {
  const gradId = useId().replace(/:/g, "");
  if (data.length === 0) {
    return <div className="flex h-[300px] items-center justify-center text-[var(--neu-text-soft)]">No closed trades in this range</div>;
  }
  const rows = data.map((p) => ({
    t: p.t,
    cum_pnl: Math.round(p.cum_pnl * 100) / 100,
    equity: startingEquity != null ? Math.round((startingEquity + p.cum_pnl) * 100) / 100 : undefined,
  }));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={rows}>
        <defs>
          <linearGradient id={`eq-${gradId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--neu-accent)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--neu-accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--neu-border)" strokeDasharray="3 3" />
        <XAxis dataKey="t" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} minTickGap={32} />
        <YAxis yAxisId="pnl" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        {startingEquity != null && (
          <YAxis yAxisId="eq" orientation="right" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        )}
        <Tooltip />
        <Area yAxisId="pnl" type="monotone" dataKey="cum_pnl" stroke="var(--neu-accent)" fill={`url(#eq-${gradId})`} />
        {equityNow && startingEquity != null && (
          <ReferenceDot yAxisId="eq" x={equityNow.t} y={equityNow.equity} r={4} fill="var(--neu-accent)" />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 4: Rewrite `DrawdownChart.tsx`** (prop `data: DrawdownPoint[]`, plot `drawdown_pct ?? drawdown_abs`, red underwater area). **Rewrite `DailyPnlChart.tsx`** (prop `data: DailyPnlPoint[]`, emerald/red bars by `pnl` sign via `Cell`). **Rewrite `MonthlyPnlGrid.tsx`** (prop `data: MonthlyPnlPoint[]`, group by year into a heat-grid keyed on `month`, color by `pnl` sign). For each, render an empty-state node when `data.length === 0`. Use CSS vars (`--neu-success`/`--neu-danger`) for colors and `pnlColorClass` from `@/lib/format` for text. **Accessibility (spec §5.5):** wrap each chart's `ResponsiveContainer` in a `<figure role="img" aria-label="...">` with a one-line summary (e.g. `aria-label="Cumulative P&L curve, ending +26.62 USDT"`) so the chart is not conveyed visually-only.

- [ ] **Step 5: Run all migrated chart tests — expect PASS**

Run: `npx vitest run src/components/analytics/__tests__/Charts.test.tsx src/components/analytics/__tests__/DailyPnlChart.test.tsx src/components/analytics/__tests__/MonthlyPnlGrid.test.tsx`
Expected: PASS. Then `npx tsc --noEmit` → no errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/analytics/EquityCurveChart.tsx src/components/analytics/DrawdownChart.tsx src/components/analytics/DailyPnlChart.tsx src/components/analytics/MonthlyPnlGrid.tsx src/components/analytics/__tests__/
git commit -m "feat(perf): rewrite charts for trades-derived series"
```

### Task 2.7: Rewrite `KpiCards.tsx` for the numeric `kpis` shape (TDD)

**Files:**
- Modify: `frontend/src/components/analytics/KpiCards.tsx`
- Modify (migrate): `frontend/src/components/analytics/__tests__/KpiCards.test.tsx`

- [ ] **Step 1: Migrate the test (failing first)**

```typescript
import { render, screen } from "@testing-library/react";
import { KpiCards } from "../KpiCards";
import type { PerformanceKpis } from "../performanceTypes";

const KPIS: PerformanceKpis = {
  total_equity: 199.02, unrealized_pnl: -1.6, open_count: 1,
  net_pnl: 12.5, realized_pnl_gross: 14.1, total_return_pct: 7.2,
  win_rate: 62.5, win_count: 10, loss_count: 6, profit_factor: 1.9,
  expectancy: 0.78, avg_win: 2.64, avg_loss: -2.31, avg_win_loss_ratio: 1.14,
  best_trade: 5.1, worst_trade: -3.3, max_consecutive_wins: 4, max_consecutive_losses: 2,
  avg_hold_time_hours: 8.4, total_trades: 16,
  max_drawdown_pct: -4.2, max_drawdown_abs: null, drawdown_duration_days: 3,
  drawdown_recovered: true, sharpe_ratio: 1.8, sortino_ratio: 2.4, calmar_ratio: 1.1,
};

it("renders numeric KPIs without NaN", () => {
  render(<KpiCards kpis={KPIS} />);
  expect(screen.getByText(/62.5/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("NaN");
});

it("renders em-dash for null metrics", () => {
  render(<KpiCards kpis={{ ...KPIS, sharpe_ratio: null }} />);
  // Sharpe shows the em-dash, never "null" or "NaN"
  expect(document.body.textContent).not.toContain("null");
});
```

- [ ] **Step 2: Run — expect failure.** Run: `npx vitest run src/components/analytics/__tests__/KpiCards.test.tsx`

- [ ] **Step 3: Rewrite `KpiCards.tsx`**

Signature: `KpiCards({ kpis, lowDataNotice = false }: { kpis: PerformanceKpis; lowDataNotice?: boolean })`. Render grouped tiles. Format with `@/lib/format` (`formatUsd`, `formatPct`, `formatRatio`, `formatHours`, `formatInt`); show `DASH` for `null`. Color via `pnlColorClass`. Group definitions:
- **Quality (render FIRST — populated at low volume):** win_rate (pct), profit_factor (ratio), expectancy (usd), avg_win/avg_loss (usd), avg_win_loss_ratio (ratio)
- **Returns:** net_pnl (usd), total_return_pct (pct), realized_pnl_gross (usd)
- **Consistency:** best_trade/worst_trade (usd), max_consecutive_wins/losses (int), avg_hold_time_hours (hours)
- **Risk (render LAST):** max_drawdown_pct (pct), sharpe_ratio (ratio), sortino_ratio (ratio), calmar_ratio (ratio), drawdown_duration_days (days)

When `lowDataNotice` is true (caller passes `meta.trading_days < 10`), **collapse the Risk group to a single notice tile** ("Risk metrics need ≥10 trading days") instead of four "—" ratio tiles (spec §5.4). Leading with Quality keeps the first screen substantive on a young account.

**Accessibility (spec §5.5 — required):** each numeric tile renders the value with an explicit sign for P&L (`formatUsd(v, { sign: true })`) AND an `aria-label` describing label+value+direction (e.g. `aria-label="Net P&L: +12.50 USDT, profit"`), so profit/loss is never conveyed by color alone. Each tile is a `<div role="group">` with the label as its accessible name.

Each tile: label + value (via the right formatter, `DASH` if null). Keep framer-motion count-up if it was present (optional). **Never** render raw `null`/`NaN`.

- [ ] **Step 4: Run — expect PASS.** Run: `npx vitest run src/components/analytics/__tests__/KpiCards.test.tsx` then `npx tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add src/components/analytics/KpiCards.tsx src/components/analytics/__tests__/KpiCards.test.tsx
git commit -m "feat(perf): rewrite KpiCards for numeric kpis"
```

---

### Task 2.8: PerformanceControlBar (scope + timeframe)

**Files:**
- Create: `frontend/src/components/analytics/PerformanceControlBar.tsx`

Single scope selector (All / Live / Demo + individual accounts) and a 7-button timeframe picker. This component is **presentational** — it receives the account list as a prop (`accounts`); the parent `PerformanceDashboard` (Task 2.11) does the fetching via `accountsApi.list` and passes it down.

- [ ] **Step 1: Write the component**

```typescript
import type { PerformanceTimeframe } from "./performanceTypes";

const TIMEFRAMES: PerformanceTimeframe[] = ["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"];

interface Props {
  scope: string;
  timeframe: PerformanceTimeframe;
  onScopeChange: (s: string) => void;
  onTimeframeChange: (t: PerformanceTimeframe) => void;
  accounts: Array<{ id: string; label: string; account_type: "live" | "demo" }>;
  hideScope?: boolean; // embedded mode
}

export function PerformanceControlBar({ scope, timeframe, onScopeChange, onTimeframeChange, accounts, hideScope }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {!hideScope && (
        <select
          value={scope}
          onChange={(e) => onScopeChange(e.target.value)}
          className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] px-3 py-2 text-[var(--neu-text-strong)]"
          aria-label="Performance scope"
        >
          <option value="all">All Accounts</option>
          <option value="live">Live</option>
          <option value="demo">Demo</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.label}</option>
          ))}
        </select>
      )}
      <div className="flex gap-1" role="tablist" aria-label="Timeframe">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => onTimeframeChange(tf)}
            aria-pressed={tf === timeframe}
            className={`rounded-[var(--neu-radius-sm)] px-2.5 py-1 text-sm ${tf === timeframe ? "neu-surface-inset text-[var(--neu-accent)]" : "text-[var(--neu-text-soft)]"}`}
          >
            {tf}
          </button>
        ))}
      </div>
    </div>
  );
}
```

(Confirm `--neu-radius-sm` exists in the design tokens; if not, use `--neu-radius-md`. Adapt the `accounts` prop shape to whatever `accountsApi` returns — the dashboard passes it in.)

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit`.
```bash
git add src/components/analytics/PerformanceControlBar.tsx
git commit -m "feat(perf): PerformanceControlBar"
```

### Task 2.9: PerformanceHeroStrip (5 KPI cards + deltas + sparklines) (TDD)

**Files:**
- Create: `frontend/src/components/analytics/PerformanceHeroStrip.tsx`
- Create: `frontend/src/components/analytics/__tests__/PerformanceHeroStrip.test.tsx`

5 cards: Total Equity (live, "now"), Net P&L, Win Rate, Sharpe, Max DD. Delta chip vs `kpis_prev` (hidden when `kpis_prev` is null or `kpis_prev.total_trades < 3`). Sparklines on Total Equity (from `equity_curve`) and Net P&L (from `daily_pnl`).

- [ ] **Step 1: Write failing test**

```typescript
import { render, screen } from "@testing-library/react";
import { PerformanceHeroStrip } from "../PerformanceHeroStrip";
import type { PerformanceOverview, PerformanceKpis } from "../performanceTypes";

const KPIS: PerformanceKpis = {
  total_equity: 199.02, unrealized_pnl: -1.6, open_count: 1,
  net_pnl: 12.5, realized_pnl_gross: 14.1, total_return_pct: 7.2,
  win_rate: 62.5, win_count: 10, loss_count: 6, profit_factor: 1.9,
  expectancy: 0.78, avg_win: 2.64, avg_loss: -2.31, avg_win_loss_ratio: 1.14,
  best_trade: 5.1, worst_trade: -3.3, max_consecutive_wins: 4, max_consecutive_losses: 2,
  avg_hold_time_hours: 8.4, total_trades: 16,
  max_drawdown_pct: -4.2, max_drawdown_abs: null, drawdown_duration_days: 3,
  drawdown_recovered: true, sharpe_ratio: 1.8, sortino_ratio: 2.4, calmar_ratio: 1.1,
};

const base: PerformanceOverview = {
  kpis: KPIS,
  kpis_prev: { total_equity: 188.1, net_pnl: 7.1, win_rate: 58, sharpe_ratio: 1.4, max_drawdown_pct: -5, total_trades: 6 },
  equity_curve: [{ t: "2026-05-01T00:00:00Z", cum_pnl: 5, peak: 5 }],
  equity_now: { t: "2026-06-14T12:00:00Z", equity: 199.02 },
  drawdown_series: [], daily_pnl: [{ date: "2026-05-01", pnl: 2.3 }], monthly_pnl: [],
  meta: { currency: "USDT", grouping_tz: "UTC", trading_days: 14, starting_equity: 174,
          return_basis: "recorded_history", live_equity_available: true,
          live_sourced: [], degraded: false },
};

it("shows a delta chip when prior window has >=3 trades", () => {
  render(<PerformanceHeroStrip overview={base} />);
  expect(screen.getByText(/Win Rate/i)).toBeTruthy();
});

it("hides delta chips when kpis_prev is null", () => {
  const { queryAllByTestId } = render(<PerformanceHeroStrip overview={{ ...base, kpis_prev: null }} />);
  expect(queryAllByTestId("delta-chip")).toHaveLength(0);
});
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement** the hero with 5 cards (reuse `@/components/ui/animated-number` for the value, a small inline Recharts sparkline `<AreaChart>` for the two series cards, a delta chip computing `kpis[m] - kpis_prev[m]` with emerald/red + ▲/▼). Add `data-testid="delta-chip"` to each chip so it's hidden-testable. Total Equity card labeled "now" and shows `DASH` when `total_equity` is null (degraded). Sticky container: `className="sticky top-0 z-10 ..."`.

- [ ] **Step 4: Run — expect PASS** + `npx tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add src/components/analytics/PerformanceHeroStrip.tsx src/components/analytics/__tests__/PerformanceHeroStrip.test.tsx
git commit -m "feat(perf): PerformanceHeroStrip with deltas + sparklines"
```

### Task 2.10: OverviewTab (composes the charts + KPI grid)

**Files:**
- Create: `frontend/src/components/analytics/tabs/OverviewTab.tsx`

- [ ] **Step 1: Write the component**

```typescript
import type { PerformanceOverview } from "../performanceTypes";
import { EquityCurveChart } from "../EquityCurveChart";
import { DrawdownChart } from "../DrawdownChart";
import { DailyPnlChart } from "../DailyPnlChart";
import { MonthlyPnlGrid } from "../MonthlyPnlGrid";
import { KpiCards } from "../KpiCards";

export function OverviewTab({ overview }: { overview: PerformanceOverview }) {
  const lowData = (overview.meta.trading_days ?? 0) < 10;
  return (
    <div className="flex flex-col gap-4">
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <EquityCurveChart
          data={overview.equity_curve}
          startingEquity={overview.meta.live_equity_available ? overview.meta.starting_equity : null}
          equityNow={overview.equity_now}
        />
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <DrawdownChart data={overview.drawdown_series} />
        </section>
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <DailyPnlChart data={overview.daily_pnl} />
        </section>
      </div>
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <MonthlyPnlGrid data={overview.monthly_pnl} />
      </section>
      <KpiCards kpis={overview.kpis} lowDataNotice={lowData} />
    </div>
  );
}
```

(The `lowDataNotice?: boolean` prop is defined on `KpiCards` in Task 2.7; when true it collapses the Risk group to a "needs ≥10 trading days" note instead of the four "—" ratio tiles — per spec §5.4.)

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit`.
```bash
git add src/components/analytics/tabs/OverviewTab.tsx src/components/analytics/KpiCards.tsx
git commit -m "feat(perf): OverviewTab composition + low-data notice"
```

### Task 2.11: PerformanceDashboard + tab shell (TDD)

**Files:**
- Create: `frontend/src/components/analytics/PerformanceDashboard.tsx`
- Create: `frontend/src/components/analytics/__tests__/PerformanceDashboard.test.tsx`

Top-level: owns `scope`/`timeframe` state (persisted to `localStorage` key `performance-filters`), renders ControlBar + HeroStrip + `NeuTabs` (Overview now; Trades/Signals/Live are placeholders until their phases). Supports `embedded`/`accountId` mode (forces `scope=accountId`, hides the scope selector and page header).

- [ ] **Step 1: Write failing test**

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PerformanceDashboard } from "../PerformanceDashboard";
import { performanceApi } from "@/api/client";
import { vi } from "vitest";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig();
  return {
    ...mod,
    performanceApi: { getOverview: vi.fn() },
    accountsApi: { ...mod.accountsApi, list: vi.fn().mockResolvedValue([]) },
  };
});

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const emptyOverview = {
  kpis: { net_pnl: 0, realized_pnl_gross: 0, win_count: 0, loss_count: 0,
          max_consecutive_wins: 0, max_consecutive_losses: 0, total_trades: 0,
          total_equity: null, unrealized_pnl: null, open_count: null,
          total_return_pct: null, win_rate: null, profit_factor: null, expectancy: null,
          avg_win: null, avg_loss: null, avg_win_loss_ratio: null, best_trade: null,
          worst_trade: null, avg_hold_time_hours: null, max_drawdown_pct: null,
          max_drawdown_abs: null, drawdown_duration_days: null, drawdown_recovered: null,
          sharpe_ratio: null, sortino_ratio: null, calmar_ratio: null },
  kpis_prev: null, equity_curve: [], equity_now: null, drawdown_series: [],
  daily_pnl: [], monthly_pnl: [],
  meta: { currency: "USDT", grouping_tz: "UTC", trading_days: 0, starting_equity: null,
          return_basis: "recorded_history", live_equity_available: false,
          live_sourced: [], degraded: true },
};

it("renders empty state when there are no closed trades", async () => {
  (performanceApi.getOverview as any).mockResolvedValue(emptyOverview);
  wrap(<PerformanceDashboard />);
  await waitFor(() => expect(document.body.textContent).toMatch(/no closed trades/i));
});

it("embedded mode hides the scope selector and scopes to the account", async () => {
  (performanceApi.getOverview as any).mockResolvedValue(emptyOverview);
  wrap(<PerformanceDashboard embedded accountId="acc_1" />);
  await waitFor(() => {
    expect(performanceApi.getOverview).toHaveBeenCalledWith("acc_1", expect.any(String), expect.anything());
  });
  expect(screen.queryByLabelText(/Performance scope/i)).toBeNull();
});
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement `PerformanceDashboard.tsx`**

```typescript
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NeuTabs } from "@/design-system/neumorphism";
import { accountsApi } from "@/api/client";
import { usePerformanceOverview } from "./hooks/usePerformance";
import { PerformanceControlBar } from "./PerformanceControlBar";
import { PerformanceHeroStrip } from "./PerformanceHeroStrip";
import { OverviewTab } from "./tabs/OverviewTab";
import type { PerformanceTimeframe } from "./performanceTypes";

interface Props { embedded?: boolean; accountId?: string; }

const STORAGE_KEY = "performance-filters";

function loadFilters(): { scope: string; timeframe: PerformanceTimeframe } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { scope: "all", timeframe: "ALL" };
}

export function PerformanceDashboard({ embedded = false, accountId }: Props) {
  const initial = loadFilters();
  const [scope, setScope] = useState(embedded && accountId ? accountId : initial.scope);
  const [timeframe, setTimeframe] = useState<PerformanceTimeframe>(initial.timeframe);
  const effectiveScope = embedded && accountId ? accountId : scope;

  const { data, isLoading, isError, refetch } = usePerformanceOverview(effectiveScope, timeframe);

  // Accounts for the scope dropdown (skip entirely in embedded mode).
  const { data: accountsRaw } = useQuery({
    queryKey: ["performance-accounts"],
    queryFn: ({ signal }) => accountsApi.list(undefined, signal),
    enabled: !embedded,
    staleTime: 60_000,
  });
  const accountOptions = (accountsRaw ?? []).map((a) => ({
    id: a.id,
    label: a.label ?? a.id,
    account_type: a.account_type as "live" | "demo",
  }));

  function update(next: { scope?: string; timeframe?: PerformanceTimeframe }) {
    const s = next.scope ?? scope;
    const t = next.timeframe ?? timeframe;
    setScope(s); setTimeframe(t);
    if (!embedded) localStorage.setItem(STORAGE_KEY, JSON.stringify({ scope: s, timeframe: t }));
  }

  const hasTrades = (data?.kpis.total_trades ?? 0) > 0;

  return (
    <div className="flex flex-col gap-4">
      <PerformanceControlBar
        scope={effectiveScope}
        timeframe={timeframe}
        onScopeChange={(s) => update({ scope: s })}
        onTimeframeChange={(t) => update({ timeframe: t })}
        accounts={accountOptions}
        hideScope={embedded}
      />
      {isLoading && <div className="h-40 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />}
      {isError && (
        <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-6 text-center">
          <p className="text-[var(--neu-danger)]">Failed to load performance.</p>
          <button onClick={() => refetch()} className="mt-2 underline">Retry</button>
        </div>
      )}
      {data && (
        <>
          <PerformanceHeroStrip overview={data} />
          {hasTrades ? (
            <NeuTabs
              value="overview"
              onValueChange={() => { /* tab state added in later phases */ }}
              variant="inset"
              items={[{ value: "overview", label: "Overview", content: <OverviewTab overview={data} /> }]}
            />
          ) : (
            <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-10 text-center">
              <p className="text-[var(--neu-text-strong)]">No closed trades yet</p>
              <p className="mt-1 text-[var(--neu-text-soft)]">Run the Scanner or enable Auto-Trade to start building performance.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

(Wire the real accounts list via a small `useAccounts` query using `accountsApi`; passing `[]` is acceptable for the first green test but replace before the phase gate. In later phases, add Trades/Signals/Live to the `items` array and lift active-tab state to `useState`.)

- [ ] **Step 4: Run — expect PASS** + `npx tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add src/components/analytics/PerformanceDashboard.tsx src/components/analytics/__tests__/PerformanceDashboard.test.tsx
git commit -m "feat(perf): PerformanceDashboard shell with Overview tab"
```

### Task 2.12: Wire the route + preserve the account-detail embedding

**Files:**
- Modify: `frontend/src/routes/route-tree.tsx`
- Modify: `frontend/src/components/accounts/AccountDetailView.tsx`

- [ ] **Step 1: Point `/analytics` at the new dashboard**

In `route-tree.tsx`: change the lazy import (line 75) and the `PerformancePage` wrapper (line 283) to use `PerformanceDashboard`. **Do NOT rewrite the wrapper from scratch** — read the existing `PerformancePage` first (it wraps the component in the repo's `RouteSuspense` with a real fallback) and change ONLY the lazy import target + the inner component name, leaving the existing `RouteSuspense`/fallback untouched:
```typescript
// line 75 — swap the lazy import target:
const PerformanceDashboard = lazy(() =>
  import("@/components/analytics/PerformanceDashboard").then((m) => ({ default: m.PerformanceDashboard })),
);
// line 283 — inside the EXISTING PerformancePage wrapper, swap only the inner element:
//   <RouteSuspense> ... <AnalyticsDashboard /> ... </RouteSuspense>
//   becomes
//   <RouteSuspense> ... <PerformanceDashboard /> ... </RouteSuspense>
```
(Keep the existing `RouteSuspense`/layout wrapper and its fallback exactly as they were — only swap the inner component and the lazy import.)

- [ ] **Step 2: Update the embedding**

In `AccountDetailView.tsx`: change the import (line 18) from `AnalyticsDashboard` to `PerformanceDashboard`, and the render site (it currently renders `<AnalyticsDashboard accountId={accountId} embedded />`) to `<PerformanceDashboard accountId={accountId} embedded />`.

- [ ] **Step 3: Typecheck + build + manual check**

Run: `npx tsc --noEmit` → no errors.
Run: `npm run build` → succeeds.
Manual: start the backend + frontend dev servers, open `/analytics` against a DB with trades; confirm the curve renders, KPIs populate, no `NaN`, and (with the backend's Bybit disabled) the Overview still renders with live values showing "—".

- [ ] **Step 4: Run the full analytics test suite + commit**

Run: `npx vitest run src/components/analytics/`
Expected: PASS.
```bash
git add src/routes/route-tree.tsx src/components/accounts/AccountDetailView.tsx
git commit -m "feat(perf): route /analytics to PerformanceDashboard; preserve embedding"
```

- [ ] **Step 5: Remove the dead `AnalyticsDashboard` (only after embedding verified)**

Confirm nothing else imports it: `grep -rn "AnalyticsDashboard" src/` → only the (now-removed) references. If clean, delete `src/components/analytics/AnalyticsDashboard.tsx` and its now-obsolete snapshot-era helpers ONLY if unused (`CleanupDialog` is retained). Run `npx tsc --noEmit` + `npm run build` again, then commit:
```bash
git rm src/components/analytics/AnalyticsDashboard.tsx
git commit -m "chore(perf): remove obsolete AnalyticsDashboard"
```

### Task 2.13: Responsive + skeleton polish (spec §5.5)

**Files:**
- Modify: `frontend/src/components/analytics/PerformanceHeroStrip.tsx`, `PerformanceDashboard.tsx`, `tabs/OverviewTab.tsx`
- Create: `frontend/src/components/analytics/__tests__/Responsive.test.tsx`

- [ ] **Step 1: Hero responsive grid**

In `PerformanceHeroStrip.tsx`, lay the 5 cards in a responsive grid that wraps on narrow widths: container `className="sticky top-0 z-10 grid grid-cols-2 gap-3 md:grid-cols-5"` (2-up on mobile, 5-up at `md`). The Total Equity card may span: `className="col-span-2 md:col-span-1"`.

- [ ] **Step 2: Tabs scroll + table adaptation**

In `PerformanceDashboard.tsx`, wrap the `NeuTabs` trigger row so it scrolls horizontally on mobile — add a wrapping `<div className="overflow-x-auto">` around the tabs (NeuTabs renders its own list; if it can't scroll, wrap the whole `NeuTabs` in the scroll container). Tables (added in Phase 3) must use `className="overflow-x-auto"` wrappers — note this requirement in Task 3.4.

- [ ] **Step 3: Card-shaped skeletons**

Replace the single `h-40 animate-pulse` loading block in `PerformanceDashboard` with a skeleton that mirrors the final layout: a hero-strip skeleton (5 short bars) + a tall chart skeleton + a KPI-grid skeleton. Reuse `@/components/ui/skeleton` if present (`grep -rn "skeleton" src/components/ui/`), else simple `animate-pulse neu-surface-base` divs sized to match.

- [ ] **Step 4: A11y + responsive test**

```typescript
import { render } from "@testing-library/react";
import { KpiCards } from "../KpiCards";
import type { PerformanceKpis } from "../performanceTypes";

const KPIS: PerformanceKpis = {
  total_equity: 199.02, unrealized_pnl: -1.6, open_count: 1,
  net_pnl: 12.5, realized_pnl_gross: 14.1, total_return_pct: 7.2,
  win_rate: 62.5, win_count: 10, loss_count: 6, profit_factor: 1.9,
  expectancy: 0.78, avg_win: 2.64, avg_loss: -2.31, avg_win_loss_ratio: 1.14,
  best_trade: 5.1, worst_trade: -3.3, max_consecutive_wins: 4, max_consecutive_losses: 2,
  avg_hold_time_hours: 8.4, total_trades: 16,
  max_drawdown_pct: -4.2, max_drawdown_abs: null, drawdown_duration_days: 3,
  drawdown_recovered: true, sharpe_ratio: 1.8, sortino_ratio: 2.4, calmar_ratio: 1.1,
};

it("P&L values expose sign + aria-label, not color-only", () => {
  const { container } = render(<KpiCards kpis={KPIS} />);
  const labelled = container.querySelector('[aria-label*="Net P&L"]');
  expect(labelled).toBeTruthy();
});
```
(Fill the `kpis` with the complete `KPIS` object — copy the one from `KpiCards.test.tsx` to avoid a partial-object placeholder.)

- [ ] **Step 5: Typecheck + build + commit**

Run: `npx tsc --noEmit` && `npm run build` && `npx vitest run src/components/analytics/`.
```bash
git add src/components/analytics/
git commit -m "feat(perf): responsive layout + skeletons + a11y"
```

---

**⛔ PHASE 2 GATE:** `/analytics` renders the new dashboard; Overview tab shows the cumulative-P&L curve + drawdown + daily/monthly P&L + KPI grid from real trade data; hero strip works with deltas; empty/loading/error states correct; low-data UX (Quality-first KPI order, Risk collapsed <10 days); a11y (sign + aria-label, not color-only) and responsive (hero wraps, skeletons) in place; account-detail embedding still works; `npx tsc --noEmit` and `npm run build` pass; all `src/components/analytics/` tests pass. **The page now works — this is the user's primary ask.** Phases 3–5 are additive.

---

## PHASE 3 — Trades tab (breakdowns + paginated raw rows)

**Outcome:** a Trades tab showing per-symbol, per-strategy, close-reason, P&L distribution, and hold-time breakdowns (bounded aggregates) plus a sortable, cursor-paginated raw-trade table. Pure trade data — no exchange/empty-table risk. Recommended to ship with Phases 1–2 as the "minimum that fully satisfies."

### Task 3.1: Service — `compute_trades_breakdown` (TDD)

**Files:**
- Modify: `backend/services/performance_service.py`
- Modify: `tests/backend/test_performance_service.py`

- [ ] **Step 1: Write failing tests**

```python
class TestTradesBreakdown:
    def test_by_symbol_and_strategy_and_close_reason(self):
        from backend.services.performance_service import compute_breakdowns
        trades = [
            _t(5.0, datetime(2026,5,1,tzinfo=timezone.utc), symbol="BTCUSDT", strategy_kind="trend", close_reason="take_profit", _id=1),
            _t(-2.0, datetime(2026,5,2,tzinfo=timezone.utc), symbol="BTCUSDT", strategy_kind="trend", close_reason="stop_loss", _id=2),
            _t(3.0, datetime(2026,5,3,tzinfo=timezone.utc), symbol="ETHUSDT", strategy_kind="mean_reversion", close_reason="take_profit", _id=3),
        ]
        b = compute_breakdowns(trades)
        by_sym = {r["symbol"]: r for r in b["by_symbol"]}
        assert by_sym["BTCUSDT"]["trades"] == 2
        assert by_sym["BTCUSDT"]["pnl"] == pytest.approx(3.0)
        assert by_sym["BTCUSDT"]["win_rate"] == pytest.approx(50.0)
        by_strat = {r["strategy"]: r for r in b["by_strategy"]}
        assert by_strat["trend"]["trades"] == 2
        by_reason = {r["reason"]: r for r in b["by_close_reason"]}
        assert by_reason["take_profit"]["count"] == 2
        # close-reason buckets use real literals; no Trailing/Breakeven invented keys
        assert "trailing" not in by_reason

    def test_legacy_strategy_flag(self):
        from backend.services.performance_service import compute_breakdowns
        # trade opened before migration-44 cutoff would be flagged; here just assert key exists
        b = compute_breakdowns([])
        assert "strategy_legacy_approximate" in b["meta"]
```

- [ ] **Step 2: Run — expect failure**, **Step 3: implement** `compute_breakdowns(trades) -> dict` returning `by_symbol`, `by_strategy`, `by_close_reason`, `pnl_distribution` (bucket by `realized_pnl_pct` ranges, e.g. "<-5%", "-5..0%", "0..2%", ">2%"), `hold_time_buckets` (by `(closed_at-opened_at)` hours: "<1h","1-4h","4-24h",">24h"), and `meta.strategy_legacy_approximate`. Set the flag `True` when any in-range trade's `opened_at` predates the migration-44 cutoff. Determine the cutoff once: read the migration-44 entry in `async_persistence.py` (the one that adds `strategy_kind`) and use a module constant `_STRATEGY_KIND_MIGRATION_TS` set to the cutoff date you find there (if the migration carries no timestamp, use the date the column was added per git history of that migration; document the chosen constant in a comment). The flag is then `any(t["opened_at"] and t["opened_at"] < _STRATEGY_KIND_MIGRATION_TS for t in trades)`. Each grouped row carries `trades`/`count`, `win_rate`, `pnl`. Win definition `net_pnl > 0`. Map close-reason literals to display buckets per spec §7 (Take Profit / Stop Loss / Liquidation / ADL / External / Manual / Rule / Cycle; unmapped shown raw).

- [ ] **Step 4: Run — expect PASS. Step 5: commit** `feat(perf): compute_breakdowns`.

### Task 3.2: Service — `compute_trades_page` (keyset pagination, TDD)

**Files:**
- Modify: `backend/services/performance_service.py`, `backend/async_persistence.py`, `tests/backend/test_performance_service.py`

- [ ] **Step 1:** Add a DB method `get_performance_trades_page(*, account_ids, account_type, start, end, sort, direction, cursor, limit)` returning `(rows, next_cursor, has_more)`. Sort default `net_pnl` with `ORDER BY COALESCE(net_pnl,'-inf') DESC, id DESC`; the cursor encodes `(sort_value, id)` (base64 JSON). Mirror the keyset pattern from `trades.py` (read its `/trades` cursor handling for the exact encode/decode helper to reuse).
- [ ] **Step 2:** Write a failing test inserting rows with a NULL `net_pnl` and asserting deterministic ordering + no skip/dup across two pages (use a mocked DB returning a fixed ordered list; assert the service slices and emits cursors correctly).
- [ ] **Step 3:** Implement `compute_trades_page` on the service (delegates to the DB method, shapes `rows` as `{id,symbol,side,net_pnl,net_pnl_pct,close_reason,opened_at,closed_at,hold_hours}` where `net_pnl_pct = net_pnl / base_capital * 100` when base_capital present else null).
- [ ] **Step 4: PASS. Step 5: commit** `feat(perf): paginated trades page (keyset)`.

### Task 3.3: Router — `/performance/trades-breakdown` + `/performance/trades` + schemas (TDD)

**Files:**
- Modify: `backend/routers/performance.py`, `backend/schemas/__init__.py`, `tests/backend/test_performance_router.py`

- [ ] **Step 1:** Add `PerformanceBreakdownResponse` and `PerformanceTradesPageResponse` Pydantic models (fields per spec §7).
- [ ] **Step 2:** Write failing router tests (200 shape; `trades-breakdown` takes `scope,timeframe`; `trades` takes `scope,timeframe,sort,dir,cursor,limit`; unknown timeframe → 422).
- [ ] **Step 3:** Add the two endpoints to `performance.py`, delegating to the service (resolve scope + window the same way `overview` does — extract a shared `_resolve(scope, timeframe, anchor)` helper on the service if convenient).
- [ ] **Step 4: PASS** (`python -m pytest tests/backend/test_performance_router.py -q`). **Step 5: commit** `feat(perf): trades-breakdown + trades endpoints`.

### Task 3.4: Frontend — TradesTab + hooks + types + client (TDD)

**Files:**
- Modify: `frontend/src/components/analytics/performanceTypes.ts`, `hooks/usePerformance.ts`, `frontend/src/api/client.ts`
- Create: `frontend/src/components/analytics/tabs/TradesTab.tsx`, `__tests__/TradesTab.test.tsx`

- [ ] **Step 1:** Add TS types (`TradesBreakdown`, `TradesPage`, row types), `performanceApi.getTradesBreakdown`/`getTradesPage`, and `useTradesBreakdown`/`useTradesPage` hooks (query keys `["performance-breakdown", scope, timeframe]` / `["performance-trades", scope, timeframe, sort, dir, cursor]`).
- [ ] **Step 2:** Write a failing `TradesTab.test.tsx` (renders per-symbol leaderboard from mock data; renders the close-reason buckets; shows the legacy-approximate hint when `meta.strategy_legacy_approximate` is true).
- [ ] **Step 3:** Implement `TradesTab.tsx`: per-symbol sortable table, per-strategy paired cards, close-reason donut (Recharts `PieChart`), P&L distribution histogram (`BarChart`), hold-time buckets, and the raw-trade table with sort headers + a "Load more" button driving the cursor. Use `@/lib/format`. **Responsive (spec §5.5):** wrap every table in `<div className="overflow-x-auto">` so it scrolls instead of overflowing below the `md` breakpoint. When `meta.strategy_legacy_approximate` is true, show a small "legacy strategy data approximate" hint above the per-strategy cards. P&L cells use `pnlColorClass` + sign + `aria-label` (not color-only).
- [ ] **Step 4:** Add `TradesTab` to the `NeuTabs` items array in `PerformanceDashboard` (lift active-tab state to `useState("overview")`). Typecheck + test.
- [ ] **Step 5: commit** `feat(perf): Trades tab`.

**⛔ PHASE 3 GATE:** Trades tab renders all breakdowns + the paginated table from real data; backend + frontend tests pass; `npx tsc --noEmit` + `npm run build` pass.

---

## PHASE 4 — Signals tab (coverage-gated)

**Outcome:** a Signals tab surfacing the existing `/signal-analytics/*` data, scope-aware, with an honest empty state. **Gated on the §4.4 coverage check** — if `signal_performance` is ~empty for the user's accounts, ship only the rolling win-rate view + the empty card.

### Task 4.1: Coverage check (do this FIRST)

- [ ] **Step 1:** Against the dev/prod DB, run `SELECT count(*) FROM signal_performance;` and `SELECT count(DISTINCT account_id) FROM signal_performance;`. Record the result in the progress tracker. If near zero, narrow this phase to Task 4.3 (rolling win-rate + empty state) and skip 4.4 (calibration/benchmark/regime/decay) until coverage exists.

### Task 4.2: Scope-aware signal-analytics client + hooks

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/components/analytics/hooks/usePerformance.ts`, `performanceTypes.ts`

- [ ] **Step 1:** Add a `signalAnalyticsApi` namespace (or extend the existing signal-analytics calls) with per-endpoint functions (`summary`, `winRate`, `calibration`, `benchmarks`, `regime`, `decayAlerts`) each accepting an optional `account_id`. Confirm each backend endpoint honors `account_id` (read `signal_analytics.py` — they accept `account_id: Optional[str] = Query(None)`; verify all six).
- [ ] **Step 2:** Add `useSignalAnalytics(scope)` hooks. For `scope ∈ {live, demo}` (multi-account), fan out one request per account of that type and merge client-side (the spec's §4.2 mapping); for `all`, pass no `account_id`; for a single id, pass it. Query keys prefixed `["performance-signals", ...]`.
- [ ] **Step 3:** Typecheck + commit `feat(perf): scope-aware signal-analytics hooks`.

### Task 4.3: SignalsTab — rolling win-rate + honest empty state (TDD)

**Files:**
- Create: `frontend/src/components/analytics/tabs/SignalsTab.tsx`, `__tests__/SignalsTab.test.tsx`

- [ ] **Step 1:** Failing test: when `summary` returns zero signals → renders the explanatory empty card ("Signal analytics become available once trades are placed from scanner signals"), NOT a blank/0.0 surface.
- [ ] **Step 2:** Implement the rolling win-rate line chart + the empty-state gate. Add `SignalsTab` to the dashboard's `NeuTabs` items.
- [ ] **Step 3: PASS + commit** `feat(perf): Signals tab (win-rate + empty state)`.

### Task 4.4: SignalsTab — calibration, benchmark, regime, decay (ONLY if coverage exists)

- [ ] **Step 1:** If Task 4.1 showed real coverage, add: confidence calibration curve, benchmark comparison (system vs buy-and-hold vs random), win rate by regime, decay-alerts list. Each from its scope-aware hook, each with its own loading/empty/error state. Pin the exact fields each needs by reading the corresponding `signal_analytics_service` method's return shape first.
- [ ] **Step 2: commit** `feat(perf): Signals tab full visualizations`.

**⛔ PHASE 4 GATE:** Signals tab renders (win-rate + empty state minimum; full viz if coverage exists); tests pass; typecheck + build pass.

---

## PHASE 5 — Live tab (fail-soft exchange aggregation)

**Outcome:** a Live tab with open positions (live unrealized P&L), account equity tiles, and sector concentration — server-throttled, fail-soft, the page's only exchange dependency. First cut candidate if scope must shrink.

### Task 5.1: Resolve the sector-concentration source (decision FIRST)

- [ ] **Step 1:** Per §11 Q3, decide: add a small read endpoint on `sector_service`, OR compute concentration inline from open positions + the `symbol_sectors` table. Read `backend/services/sector_service.py` + the `symbol_sectors` schema to pick. Record the decision in the tracker. (Inline-from-positions is simplest for v1.)

### Task 5.2: Service — `compute_live` (fail-soft, TDD)

**Files:**
- Modify: `backend/services/performance_service.py`, `tests/backend/test_performance_service.py`

- [ ] **Step 1:** Failing test: one account's `get_positions` raises → the result still returns (no exception), `degraded: true`, that account's tile carries `error`, other accounts present.
- [ ] **Step 2:** Implement `compute_live(scope)`: resolve scope → per-account, wrap each account's `get_positions` + dashboard card in try/except with a timeout; aggregate `positions` (with `unrealized_pnl_pct`), `account_tiles` (equity/today_pnl/positions_count/type/error), `sector_concentration` (per the 5.1 decision), and a top-level `degraded`. Add a short-TTL (~10s) in-memory cache keyed by scope to avoid thundering-herd.
- [ ] **Step 3: PASS + commit** `feat(perf): compute_live fail-soft aggregation`.

### Task 5.3: Router — `/performance/live` + schema (TDD)

**Files:**
- Modify: `backend/routers/performance.py`, `backend/schemas/__init__.py`, `tests/backend/test_performance_router.py`

- [ ] **Step 1:** Add `PerformanceLiveResponse` model + the `GET /performance/live?scope=` endpoint (no timeframe). Failing test: 200 shape; degraded path returns partial data + `degraded:true`, not 500.
- [ ] **Step 2: implement, PASS, commit** `feat(perf): /performance/live endpoint`.

### Task 5.4: Frontend — LiveTab (TDD)

**Files:**
- Modify: `performanceTypes.ts`, `hooks/usePerformance.ts`, `frontend/src/api/client.ts`
- Create: `frontend/src/components/analytics/tabs/LiveTab.tsx`, `__tests__/LiveTab.test.tsx`

- [ ] **Step 1:** Add types + `performanceApi.getLive` + `usePerformanceLive(scope)` hook — query key `["performance-live", scope]` (already excluded from persistence in Task 2.5), `staleTime: 0`, `refetchInterval: 15_000` **only while the tab is mounted** (the hook is only mounted when LiveTab renders inside `NeuTabs`, whose inactive panels unmount — so the interval naturally stops when the tab is hidden).
- [ ] **Step 2:** Failing test: renders the `degraded` banner + a per-account `error` when present; renders positions table + tiles + sector bars from mock data.
- [ ] **Step 3:** Implement `LiveTab.tsx`: open-positions table (color-coded unrealized P&L), account equity tiles (live/demo), sector concentration horizontal bars, and a `degraded` banner. Add `LiveTab` to the dashboard's `NeuTabs` items.
- [ ] **Step 4: PASS + commit** `feat(perf): Live tab`.

**⛔ PHASE 5 GATE:** Live tab renders positions/tiles/sector concentration; one failing account degrades (not 500s); polls only while visible; tests pass; typecheck + build pass.

---

## Final verification (after all shipped phases)

- [ ] Backend: `python -m pytest tests/backend/test_performance_service.py tests/backend/test_performance_router.py -q` → all PASS.
- [ ] Frontend: `cd frontend && npx tsc --noEmit && npx vitest run src/components/analytics/ && npm run build` → all PASS.
- [ ] Manual: load `/analytics` against a DB with real trades → all shipped tabs functional, no `NaN`, curve renders, Overview works with backend Bybit disabled (live values show "—").
- [ ] Account-detail page (`/accounts/$accountId`) still embeds the dashboard correctly.

---
