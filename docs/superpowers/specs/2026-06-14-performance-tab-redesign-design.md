# Performance Tab — Complete Redesign & Rebuild

**Date:** 2026-06-14
**Status:** Design approved, ready for implementation planning
**Route:** `/analytics` (nav label "Performance")
**Skill workflow:** `/new-feature` (brainstorming → writing-plans → implement-plan)

---

## 1. Problem Statement

The Performance tab (`/analytics`, rendered by `frontend/src/components/analytics/AnalyticsDashboard.tsx`) **never works**. It perpetually shows "0 snapshots / No history yet", blank LATEST EQUITY, blank REALIZED PNL, and an empty equity area — even when the user has real trades and real account equity ($199.02 across 2/2 live accounts).

### Root cause (confirmed by codebase analysis)

The analytics page is built entirely on a **snapshot** foundation that is never auto-populated for the view it defaults to:

1. There are **two snapshot tables**: `daily_snapshots` (`async_persistence.py:1194`) and `high_freq_snapshots` (`async_persistence.py:1218`).
2. The background `SnapshotScheduler` (`backend/main.py:382`) only wires `take_all_hf_snapshots` → it writes **only** `high_freq_snapshots` every 300s. Nothing ever calls `take_all_snapshots` (daily) on a cadence — it is reachable only via the manual "Take Snapshot" button (`POST /api/v1/snapshots/all`).
3. The GET analytics endpoints default to `period="1M"` (`analytics.py:156,178`), which is **not** a sub-day period, so they read the **daily** table — which is empty. Result: "No history yet" forever.
4. Additional guards: the entire accounts_service + scheduler block is gated on `ACCOUNTS_ENCRYPTION_KEY` (`main.py:363`); accounts must be `is_active AND include_in_analytics` to be eligible.

### Secondary problems

- **Reliability:** The 604-line monolith uses raw `useState` + `useEffect` + `AbortController` with four interacting effects and shared refs (`AnalyticsDashboard.tsx:96-184`). Racing aborts and manual refetch make it fragile. No TanStack Query caching despite the rest of the app using it.
- **Numeric fields as strings:** `avg_win`, `avg_loss`, `total_pnl` arrive as strings (`KpiCards.tsx:32-35`); null/`"NaN"`/missing values render `NaN` or blank.
- **Always-empty timeframes:** The PERIOD picker includes sub-day buckets (15M/30M/2H/6H/12H) that require intraday snapshots that rarely exist, so short timeframes are near-always empty.
- **Wasted data:** A large amount of real, working data is ignored — full trade history with realized P&L (`/trades`, `/trades/stats`), a complete but **hidden** signal-analytics surface (`/signal-analytics/*`, routed but with no nav entry), portfolio summary, per-strategy stats, sector data.
- **Visual weakness:** The page mixes two design-token systems (shadcn + neumorphism) inconsistently and lacks the polish of the app's best surfaces (e.g. `backtest/BacktestResultsPage.tsx`).

---

## 2. Goals & Non-Goals

### Goals

1. Make the Performance tab **reliably work with zero manual setup** by deriving analytics from the source-of-truth trade data, not from snapshots.
2. **Surface everything meaningful** across the app that relates to performance, organized across four domains: Portfolio KPIs + curves, Trade & strategy breakdowns, Signal quality & benchmarks, and Live positions & accounts.
3. **Redesign the UX** with a hero KPI strip + tabbed sections, refined within the existing neumorphic design system.
4. Fix the reliability foundations: TanStack Query, numeric coercion, real loading/empty/error states, meaningful timeframes only.

### Non-Goals

- **AI Manager analytics** — explicitly deferred (consistent with project's backtest decision).
- **Removing the snapshot system** — snapshots stay in place (used elsewhere); we simply stop depending on them as the primary analytics source. A future enhancement can layer intraday "live pulse" on top of HF snapshots.
- **Redaction redesign** — the REST API already returns full unredacted numbers to the frontend (redaction is MCP-layer only); no change needed.
- **Changing the global AppMarketBar** header strip (RUNTIME/LIVE EQUITY/RESEARCH QUEUE/SCANNER PULSE/TRADE DESK) — it already works and is separate from this page.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND  /analytics  (PerformancePage)                     │
│                                                              │
│  ControlBar  →  scope (portfolio/live/demo/account) +        │
│                 timeframe (1D/1W/1M/3M/YTD/1Y/ALL)           │
│  HeroStrip   →  5 sticky KPI cards (AnimatedNumber + delta)  │
│  Tabs:                                                        │
│    Overview  →  EquityCurve, Drawdown, DailyPnl,            │
│                 MonthlyHeatmap, KpiGrid                      │
│    Trades    →  per-symbol, per-strategy, close-reason,     │
│                 P&L distribution, hold-time                 │
│    Signals   →  rolling win-rate, calibration, benchmark,   │
│                 regime, decay alerts                        │
│    Live      →  open positions, account tiles, sector conc. │
│                                                              │
│  Data layer: TanStack Query hooks (usePerformance*)         │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST /api/v1
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKEND                                                     │
│  NEW  performance.py router  →  /api/v1/performance/*        │
│  NEW  performance_service.py →  computes from trades         │
│  REUSE signal_analytics.py   →  /api/v1/signal-analytics/*  │
│  REUSE portfolio.py          →  /api/v1/portfolio/summary   │
│  REUSE trades.py             →  /api/v1/trades              │
│                                                              │
│  Source of truth (existing tables):                         │
│    trades, closed_pnl_records, trading_accounts,            │
│    signal_performance                                       │
│  Math reuse: portfolio_stats.py, backtest_metrics.py        │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** the equity curve, drawdown, and all KPIs are **reconstructed from closed trade history** (ordered by `closed_at`, accumulating `realized_pnl` from a starting-capital baseline). This makes the page self-sufficient and historically accurate with no snapshot dependency.

---

## 4. Backend Design

### 4.1 New service — `backend/services/performance_service.py`

A new service class `PerformanceService` that computes performance analytics purely from existing source-of-truth tables. It does **not** read `daily_snapshots` or `high_freq_snapshots`.

**Data sources:**
- `trades` table (`async_persistence.py:68`) — `realized_pnl`, `realized_pnl_pct`, `net_pnl`, `close_reason`, `strategy_kind`, `opened_at`, `closed_at`, `symbol`, `side`, `status`, `leverage`.
- `closed_pnl_records` table (`async_persistence.py:1177`) — Bybit-sourced closed P&L (cross-check / fallback).
- `trading_accounts` table — `include_in_analytics`, `strategy_cohort`, account type (live/demo), for scope filtering and starting-capital baseline.

**Core computation — equity curve reconstruction:**
1. Resolve the account scope → set of eligible `account_id`s (portfolio = all included; live/demo = by type; single = one id).
2. Fetch closed trades in scope, ordered by `closed_at` ascending, within the timeframe window.
3. Establish a **starting-capital baseline** per scope. Baseline strategy: derive from current equity minus cumulative realized P&L within the window (so the curve ends at present equity), OR use earliest-known equity. Exact baseline rule is an implementation decision to finalize in the plan; it must make the curve's final point reconcile with `portfolio/summary` equity.
4. Accumulate `realized_pnl` to produce equity points: `equity[i] = baseline + Σ realized_pnl[0..i]`.
5. Derive **drawdown series** from the running peak of the equity curve: `drawdown_pct[i] = (equity[i] - peak[i]) / peak[i] * 100`.
6. Derive **daily P&L** (sum realized_pnl grouped by close date) and **monthly P&L** (grouped by year-month).

**KPI computation** (reuse `backend/services/portfolio_stats.py` and patterns from `backtest_metrics.py`):
- Returns: `total_return_pct`, `net_pnl`, `realized_pnl`, `unrealized_pnl` (live, from open positions).
- Risk: `max_drawdown_pct`, `sharpe_ratio` (`portfolio_stats.calc_sharpe`), `sortino_ratio` (`calc_sortino`), `calmar_ratio` (`calc_calmar`), `drawdown_duration_days` (`calc_drawdown_duration`).
- Quality: `win_rate`, `win_count`, `loss_count`, `profit_factor`, `expectancy`, `avg_win`, `avg_loss`, `avg_win_loss_ratio`.
- Consistency: `best_day`, `worst_day`, `max_consecutive_wins`, `max_consecutive_losses` (`portfolio_stats.max_consecutive`), `avg_hold_time`.
- Counts: `total_trades`, `open_count`.

**All numeric outputs must be returned as JSON numbers (float/int), never strings**, to fix the existing string-coercion bug. Null-safe: missing/undefined metrics return `null`, never `"NaN"`.

### 4.2 New router — `backend/routers/performance.py`

Mounted at prefix `/api/v1/performance` in `backend/main.py` (alongside the existing analytics router).

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/performance/overview` | `scope`, `account_id?`, `account_type?`, `timeframe` | `{ kpis, equity_curve[], drawdown_series[], daily_pnl[], monthly_pnl[] }` |
| GET | `/performance/trades-breakdown` | `scope`, `account_id?`, `account_type?`, `timeframe` | `{ by_symbol[], by_strategy[], by_close_reason[], pnl_distribution[], hold_time_buckets[] }` |
| GET | `/performance/live` | `scope`, `account_id?`, `account_type?` | `{ positions[], account_tiles[], sector_concentration[] }` |

**Scope semantics:** `scope ∈ {portfolio, live, demo, account}`. When `scope=account`, `account_id` is required. `timeframe ∈ {1D, 1W, 1M, 3M, YTD, 1Y, ALL}` → resolved to a start datetime server-side.

**Pydantic response models** defined in `backend/schemas/__init__.py` (v2), so the contract is typed and validated — unlike the current analytics router which returns raw dicts. Each model documents units (USD vs pct vs ratio).

**Signals tab** does **not** need new endpoints — it reuses the existing `/api/v1/signal-analytics/*` endpoints (`summary`, `win-rate`, `calibration`, `benchmarks`, `regime`, `decay-alerts`), which already accept an optional `account_id`.

**Live tab** reuses `/api/v1/portfolio/summary` and `/api/v1/portfolio/dashboard` for account tiles; open positions come from the new `/performance/live` (which wraps existing position-fetch logic with live unrealized P&L) or directly from `/accounts/{id}/trades/open` aggregated.

### 4.3 Performance & safety

- **Caching:** Overview/breakdown queries are read-only aggregations. Acceptable to compute on-the-fly for typical trade volumes; if a scope has very large trade counts, add a short-TTL in-memory cache keyed by `(scope, account_id, timeframe)`. Decide threshold in plan.
- **Empty data:** When a scope has zero closed trades, endpoints return empty arrays + null KPIs (HTTP 200), so the frontend renders a true "no trades yet" empty state rather than an error.
- **Unredacted:** REST routers return full numbers (confirmed: redaction is MCP-only). No `financial_detail` flag needed here.

---

## 5. Frontend Design

### 5.1 Component structure

The 604-line `AnalyticsDashboard.tsx` is replaced by a focused composition. New/changed files under `frontend/src/components/analytics/`:

| File | Purpose |
|---|---|
| `PerformancePage.tsx` (new top-level) | Orchestrates ControlBar + HeroStrip + Tabs; owns scope/timeframe state (persisted to `localStorage`) |
| `PerformanceControlBar.tsx` | Scope selector (Portfolio / Live / Demo / single account) + Live/Demo toggle + timeframe picker |
| `PerformanceHeroStrip.tsx` | 5 sticky KPI cards w/ AnimatedNumber + delta chip + mini sparkline |
| `tabs/OverviewTab.tsx` | EquityCurve, Drawdown, DailyPnl, MonthlyHeatmap, KpiGrid |
| `tabs/TradesTab.tsx` | per-symbol, per-strategy, close-reason, P&L distribution, hold-time |
| `tabs/SignalsTab.tsx` | rolling win-rate, calibration, benchmark, regime, decay alerts |
| `tabs/LiveTab.tsx` | open positions table, account tiles, sector concentration |
| `hooks/usePerformance.ts` | TanStack Query hooks: `usePerformanceOverview`, `useTradesBreakdown`, `usePerformanceLive`, plus signal-analytics hooks |

**Reuse (do not rebuild):**
- Charts: existing `EquityCurveChart.tsx`, `DrawdownChart.tsx`, `DailyPnlChart.tsx`, `MonthlyPnlGrid.tsx` — restyled, fed by new data shape.
- `KpiCards.tsx` — adapted to numeric (not string) inputs and grouped categories.
- `backtest/format.ts` helpers (`formatUsd`, `formatPct`, `formatRatio`) — promote to a shared location or import directly.
- `backtest/MetricsGrid.tsx` polish patterns; `layout/PageHeader.tsx`; `ui/animated-number.tsx`; `ui/tabs.tsx`; `ui/AccountSelector.tsx`.
- `CleanupDialog.tsx` — retained (snapshot cleanup still valid as a secondary action, de-emphasized).

The old `AnalyticsDashboard.tsx` is also embedded in `AccountDetailView` via `embedded`/`accountId` props. The new `PerformancePage` must preserve an `embedded`/`accountId` mode so the account-detail view continues to work (scoped to a single account, hero strip optionally condensed).

### 5.2 Page layout

```
┌─ CONTROL BAR ─────────────────────────────────────────────┐
│ Scope:[Portfolio ▾]  [Live│Demo]   1D 1W 1M 3M YTD 1Y ALL │
├─ HERO STRIP (sticky) ─────────────────────────────────────┤
│ Total Equity │ Net P&L │ Win Rate │ Sharpe │ Max DD        │
│  $199.02     │ +$X ▲   │  62.5%   │  1.8   │ -4.2%         │
├─ TABS ────────────────────────────────────────────────────┤
│ [ Overview ] [ Trades ] [ Signals ] [ Live ]              │
├───────────────────────────────────────────────────────────┤
│ (active tab content)                                       │
└───────────────────────────────────────────────────────────┘
```

### 5.3 Tab content detail

**Overview** — big gradient equity area chart (peak line dashed); drawdown underwater chart; daily P&L emerald/red bars; monthly P&L heatmap; full KPI grid grouped Returns / Risk / Quality / Consistency.

**Trades** — per-symbol leaderboard table (sortable by P&L / win rate / count); per-strategy split (trend vs mean-reversion) as paired cards; close-reason donut (TP / SL / trailing / breakeven / manual); P&L distribution histogram; hold-time buckets.

**Signals** — rolling win-rate line; confidence calibration curve (predicted vs realized by tier); benchmark comparison (system vs buy-and-hold vs random); win rate by market regime; active decay alerts list. (This is the previously-hidden `/signal-analytics` surface, now brought forward.)

**Live** — open positions table (symbol, side, size, leverage, entry, live unrealized P&L, color-coded); account equity tiles (live vs demo, equity, today's P&L, positions count); sector concentration horizontal bars.

### 5.4 Timeframe & scope behavior

- Timeframes reduced to **1D / 1W / 1M / 3M / YTD / 1Y / ALL** — all backed by trade history, so none are dead. Sub-day buckets removed.
- Default timeframe: **1M**. Default scope: **Portfolio**.
- Scope + timeframe persisted to `localStorage` (`performance-filters`) and reflected in query keys so caching works per-view.
- Changing scope/timeframe triggers a TanStack Query refetch (cached, no abort races).
- Live tab data refetches on an interval (e.g. 15–20s, matching `AppMarketBar`) for fresh unrealized P&L; historical tabs use a longer stale time.

### 5.5 States

- **Loading:** card-shaped skeletons matching final layout (reuse `ui/skeleton.tsx`).
- **Empty:** only when a scope genuinely has zero trades — a single clear empty card with a CTA linking to Scanner / Auto-trade (not the misleading "take a snapshot" dead-end).
- **Error:** inline error card per query with a retry button; one failing tab does not blank the whole page.
- **Numeric safety:** all values coerced to numbers; `null`/missing → an em-dash "—", never `NaN`.

---

## 6. Visual Design (Refined Neumorphic)

Stays native to the existing design system — `--neu-*` tokens (`frontend/src/design-system/neumorphism/styles.css`), Geist Variable font, warm orange accent `oklch(0.58 0.16 28)`, raised dual-shadow cards, 12/16/22px radii, pill chips. Light "clay" base + graphite dark mode both supported.

- **Hero strip:** 5 raised neu-cards, each = label + `AnimatedNumber` value + delta chip (▲ emerald / ▼ red) + faint sparkline. Sticky on scroll.
- **Charts:** Recharts (already installed `^3.8.1`), restyled — equity = gradient area (accent → transparent) w/ dashed peak; drawdown = red-tinted underwater area; daily P&L = emerald/red bars; monthly = neu heat-grid. All colors from CSS vars so both themes work.
- **KPI grid:** soft raised tiles, color-coded (emerald good / red bad / amber caution), grouped by category.
- **Tabs:** existing pill-style `ui/tabs.tsx` with inset-shadow active state.
- **Tables:** neu-surface rows, monospace numbers for alignment, hover lift, color-coded P&L.
- **Motion:** framer-motion KPI count-ups + gentle stagger-in on tab switch; skeletons match card shapes.
- **Consistency cleanup:** the page uses **only** neumorphism tokens (the old page mixed shadcn + neu inconsistently).

Color convention (app-wide): emerald = profit, red/destructive = loss, amber = caution.

---

## 7. API Contract (response shapes)

Illustrative shapes; exact Pydantic models finalized in the plan. All money in account currency (USD), all numbers are JSON numbers.

```jsonc
// GET /api/v1/performance/overview?scope=portfolio&timeframe=1M
{
  "kpis": {
    "total_equity": 199.02, "net_pnl": 12.50, "realized_pnl": 14.10,
    "unrealized_pnl": -1.60, "total_return_pct": 6.7, "win_rate": 62.5,
    "win_count": 10, "loss_count": 6, "profit_factor": 1.9,
    "expectancy": 0.78, "avg_win": 3.2, "avg_loss": -1.7,
    "sharpe_ratio": 1.8, "sortino_ratio": 2.4, "calmar_ratio": 1.1,
    "max_drawdown_pct": -4.2, "drawdown_duration_days": 3,
    "best_day": 5.1, "worst_day": -3.3,
    "max_consecutive_wins": 4, "max_consecutive_losses": 2,
    "total_trades": 16, "open_count": 1, "avg_hold_time_hours": 8.4
  },
  "equity_curve":   [{ "t": "2026-05-15T00:00:00Z", "equity": 186.5, "peak": 186.5 }],
  "drawdown_series":[{ "t": "2026-05-15T00:00:00Z", "drawdown_pct": 0.0 }],
  "daily_pnl":      [{ "date": "2026-05-15", "pnl": 2.3 }],
  "monthly_pnl":    [{ "month": "2026-05", "pnl": 8.1, "return_pct": 4.3 }]
}

// GET /api/v1/performance/trades-breakdown?scope=portfolio&timeframe=1M
{
  "by_symbol":      [{ "symbol": "BTCUSDT", "trades": 5, "win_rate": 60.0, "pnl": 7.2 }],
  "by_strategy":    [{ "strategy": "trend", "trades": 11, "win_rate": 63.6, "pnl": 9.8 },
                     { "strategy": "mean_reversion", "trades": 5, "win_rate": 60.0, "pnl": 2.7 }],
  "by_close_reason":[{ "reason": "take_profit", "count": 8, "pnl": 18.4 }],
  "pnl_distribution":[{ "bucket": "0 to 2%", "count": 4 }],
  "hold_time_buckets":[{ "bucket": "<1h", "count": 3, "win_rate": 66.7 }]
}

// GET /api/v1/performance/live?scope=portfolio
{
  "positions": [{ "account_id": "...", "symbol": "ETHUSDT", "side": "Buy",
                  "size": 0.1, "leverage": 20, "entry": 2950.0,
                  "unrealized_pnl": -1.6, "unrealized_pnl_pct": -2.7 }],
  "account_tiles": [{ "account_id": "...", "label": "Main (Live)", "type": "live",
                      "equity": 120.0, "today_pnl": 1.2, "positions_count": 1 }],
  "sector_concentration": [{ "sector": "L1", "exposure_pct": 45.0, "positions": 2 }]
}
```

---

## 8. Testing Strategy (TDD — non-negotiable per project rules)

### Backend (`tests/backend/`, pytest + pytest-asyncio)

- `performance_service`: equity-curve reconstruction correctness (known trade fixtures → expected curve); baseline reconciles to current equity; drawdown derivation; KPI math (win rate, profit factor, expectancy, Sharpe/Sortino) against hand-computed values; per-symbol / per-strategy / close-reason grouping; empty-scope returns empty arrays + null KPIs; scope filtering (portfolio/live/demo/account) and `include_in_analytics` honored; timeframe window boundaries (1D/YTD/ALL).
- `performance` router: each endpoint 200 shape, param validation (missing `account_id` when `scope=account` → 422), numbers-not-strings invariant, null-safety.

### Frontend (`frontend/src/components/analytics/__tests__/`, Vitest)

- Hooks: query key composition per scope/timeframe; numeric coercion; null → "—".
- Components: HeroStrip renders deltas + signs; each tab renders with mock data; loading skeletons; empty state shows CTA (not snapshot dead-end); error card + retry; charts receive correctly-shaped data; `embedded`/`accountId` mode scopes to one account.
- Regression: account-detail embedding still works.

### Verification

- Backend: `python -m pytest tests/backend/ -x -q`.
- Frontend: `cd frontend && npx tsc --noEmit && npm run build`.
- Manual: load `/analytics` against a DB with real trades → equity curve renders, KPIs populated, all four tabs functional, no `NaN`, final equity matches `portfolio/summary`.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Starting-capital baseline makes equity curve not reconcile with live equity | Anchor curve so its final point == current `portfolio/summary` equity; cover with a reconciliation test |
| Large trade volumes slow on-the-fly aggregation | Short-TTL in-memory cache keyed by (scope, account_id, timeframe); add DB indexes if needed |
| `closed_at` nulls / open trades skew the curve | Curve uses closed trades only; open positions contribute unrealized P&L to KPIs separately |
| Breaking the `AccountDetailView` embedding | Preserve `embedded`/`accountId` API; explicit regression test |
| Two strategy cohorts (trend / mean_reversion) with sparse data | Per-strategy cards handle zero-trade strategy gracefully (show "—") |
| Timeframe tokens mis-parsed server-side (old bug) | Server owns timeframe→datetime resolution from a fixed enum; reject unknown tokens with 422 |

---

## 10. File Change Summary

**New backend:**
- `backend/services/performance_service.py`
- `backend/routers/performance.py`
- Pydantic models in `backend/schemas/__init__.py`
- Router mount in `backend/main.py`
- Tests in `tests/backend/`

**New/changed frontend:**
- `frontend/src/components/analytics/PerformancePage.tsx` (new)
- `PerformanceControlBar.tsx`, `PerformanceHeroStrip.tsx` (new)
- `tabs/OverviewTab.tsx`, `tabs/TradesTab.tsx`, `tabs/SignalsTab.tsx`, `tabs/LiveTab.tsx` (new)
- `hooks/usePerformance.ts` (new)
- Restyle: `EquityCurveChart.tsx`, `DrawdownChart.tsx`, `DailyPnlChart.tsx`, `MonthlyPnlGrid.tsx`, `KpiCards.tsx`
- New client functions in `frontend/src/api/client.ts`
- Route wiring in `frontend/src/routes/route-tree.tsx` (point `/analytics` to `PerformancePage`)
- `AccountDetailView` embedding update
- Tests in `frontend/src/components/analytics/__tests__/`

**Retained:** `CleanupDialog.tsx` (de-emphasized secondary action). Old `AnalyticsDashboard.tsx` removed once embedding migrated.

---

## 11. Open Questions for Planning

1. Exact starting-capital baseline rule (anchor-to-current-equity vs earliest-known) — confirm during plan.
2. Whether to promote `backtest/format.ts` to a shared module or import directly.
3. Caching threshold for on-the-fly aggregation.
4. Whether the Signals tab should also appear as its own nav entry (currently `/signal-analytics` is routed but hidden) or live only inside Performance.
