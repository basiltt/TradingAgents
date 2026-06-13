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
│  ControlBar  →  single scope selector                        │
│                 {All | Live | Demo | <account>} +            │
│                 timeframe (1D/1W/1M/3M/YTD/1Y/ALL)           │
│  HeroStrip   →  5 sticky KPI cards (AnimatedNumber +         │
│                 delta-vs-prior-window; sparkline where data) │
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
│         (conditionally populated — see §4.4)                 │
│  AGGREGATE accounts_service.get_dashboard → Live tab tiles   │
│         (live Bybit calls — fail-soft, see §4.3)             │
│                                                              │
│  Single source of truth for history:  trades table          │
│    (net_pnl, closed_at, status, parent_trade_id)             │
│  Live/scope joins:  trading_accounts                         │
│  Signals surface:   signal_performance (may be sparse)       │
│  Math reuse: portfolio_stats.py (needs daily-bucket + adapter)│
└─────────────────────────────────────────────────────────────┘
```

**Key principle — Cumulative P&L curve (truly exchange-independent):** the primary curve is **Cumulative net P&L**, built only from the `trades` table — order closed trades by `closed_at`, accumulate `COALESCE(net_pnl, 0)` (fee-netted, not gross `realized_pnl`) **from the first recorded trade (origin 0)**. A selected timeframe **slices the x-axis** (zooms to that window) — it does NOT rebase the y-values to 0, so `cum_pnl` is always "cumulative since first trade" and a 1M view simply shows that all-time line over the last month. The y-axis is labeled **"Cumulative P&L (USDT)"**, NOT account equity. This needs zero live data, so the Overview tab renders fully even if Bybit is down — directly serving the "make it reliably work" goal.

**Starting-equity denominator `D` (exchange-independent, the basis for % metrics):** `D` = the scope's starting equity = **Σ over in-scope accounts of each account's earliest *non-null* `trading_cycles.initial_equity`** (verified real column, `async_persistence.py:1337`, written from the wallet at cycle start; filter `initial_equity IS NOT NULL` then take the earliest by `created_at`), falling back to that account's first trade `base_capital` (ordered by `opened_at`) when the account has no cycle. Computed **per account first (one value each), then summed** — never a `trades ⋈ cycles` join that would multiply an account's capital by its cycle/trade count. DB-only, no live call (both columns are stored at write time).

**Aggregate null-D rule (multi-account correctness):** an account whose `D` is null/≤0 (e.g. a manual-only account with no cycle and a null `base_capital`) is **excluded from BOTH the numerator and the denominator** of every scope-level `%`/ratio metric — never counted in the P&L numerator while dropped from the denominator (which would divide its profit by other accounts' capital and inflate the result). If excluding leaves zero accounts with a valid `D`, the scope's `%`/ratio metrics show "—" (dollar metrics still render). Single-account scope with null `D` → that card's `%`/ratios show "—".

**Approximation note (documented, not hidden):** the cycle source stores `totalEquity` while the trade fallback stores an available-balance figure — slightly different quantities. `D` is therefore an order-of-magnitude-correct "starting equity," and `total_return_pct` is labeled "Return (recorded history)", not presented as an audited figure. Good enough for a performance lens; not an accounting statement.

`D` is `COALESCE`-guarded and queryable from the DB with no live call. From `D` the service derives an **exchange-independent equity proxy** `equity_proxy[i] = D + cum_pnl[i]`, used for proper percentage drawdown and for the daily-return series behind Sharpe/Sortino/Calmar. If `D ≤ 0` or unavailable, all `_pct`/ratio metrics that need it return `null` (UI shows "—"), never a divide-by-zero.

One **optional, purely cosmetic overlay** (no metric depends on it):
- **Live "now" equity marker** — current `total_equity` (live-sourced) plotted as a separate annotation, and an optional right-hand absolute-equity axis. If the live fetch is degraded the marker/axis is omitted; the curve, drawdown, and every KPI are unaffected because they use `D` (DB-sourced), not live equity. The live marker may differ from `D + cum_pnl[last]` by untracked deposits/withdrawals — that gap is shown honestly, not reconciled away.

**Drawdown** is the running peak-to-trough of `equity_proxy` (`drawdown_pct[i] = (equity_proxy[i] − peak[i]) / peak[i] * 100`) over the selected window — a true percentage, exchange-independent, never dollars-under-a-`_pct`-key.

**Why not anchor the curve to live equity:** back-solving a baseline from present equity re-introduces a live Bybit dependency for *all* history and makes the curve blank during an outage — the exact failure this redesign exists to kill. Cumulative-P&L from a DB-sourced origin is reproducible, stable across refetches, deterministic regardless of Bybit availability, and never blank when trades exist.

**Documented limitations (stated, not hidden):**
- **`trades`/cycle history start:** `D` is the earliest *recorded* starting equity (first cycle or first trade). If an account traded before logging existed, `D` reflects "equity at first recorded activity," not original deposited capital, so `total_return_pct` is "return over recorded history" — labeled exactly that. The cumulative-P&L curve and all dollar KPIs are always correct regardless.
- **Deposits/withdrawals:** no capital-flow ledger exists in the schema. The cumulative-P&L curve and dollar KPIs are immune (flows don't appear in `net_pnl`). The only place a flow shows is the cosmetic live-equity marker diverging from `D + cum_pnl` — shown honestly, not reconciled away.

---

## 4. Backend Design

### 4.1 New service — `backend/services/performance_service.py`

A new service class `PerformanceService` computes performance analytics. Its **historical** outputs (curve, drawdown, daily/monthly P&L, trade-derived KPIs) read only the `trades` table and never `daily_snapshots`/`high_freq_snapshots`. Its **live** outputs (`total_equity`, `unrealized_pnl`, `open_count`) require live account data and are sourced separately (see "Live-dependent KPIs" below) — the "no snapshots" rule is about not depending on the broken snapshot tables, NOT a claim that every number comes from `trades` alone.

**Data sources:**
- `trades` table (verified `async_persistence.py:67-129`) — **single source of truth for history**. Columns confirmed to exist: `realized_pnl NUMERIC(20,8)` (gross), `net_pnl NUMERIC(20,8)` (fee-netted), `realized_pnl_pct`, `close_reason`, `strategy_kind` (added migration 44, defaults `'trend'` for legacy rows — see caveat), `opened_at`/`closed_at TIMESTAMPTZ`, `symbol`, `side`, `status`, `leverage`, `account_id`, `parent_trade_id`, `exit_price`.
- `trading_accounts` (verified `async_persistence.py:1158-1216`) — `account_type CHECK IN ('demo','live')`, `include_in_analytics`, `strategy_cohort`, `deleted_at`. `account_type` lives ONLY here, so scope filtering requires `trades JOIN trading_accounts`.
- Live equity / unrealized P&L / open positions — from `accounts_service.get_dashboard()` aggregation (live Bybit), NOT from `trades`. Used only for the three live-dependent KPIs and the Live tab.
- **NOT used:** `closed_pnl_records` (different precision/epoch units, Bybit-synced, can disagree with `trades`) and `compute_analytics()` (snapshot-gated — returns empty when `daily_snapshots` is empty, the exact bug we're fixing). The v1 single source is `trades`; a `closed_pnl_records` cross-check is explicitly out of scope.

**Canonical trade-set filter (resolves the partial-close double-count ambiguity — Critical):**
History and KPIs operate on the SAME set: trades where `status = 'closed' AND closed_at IS NOT NULL AND exit_price > 0`, joined to non-deleted, USDT-settled accounts in scope (`trading_accounts.deleted_at IS NULL AND include_in_analytics = TRUE`). This set **includes partial-close child rows** (verified `trade_repository.py:732-748`: each child is its own `status='closed'` row with its own `net_pnl`, `parent_trade_id`, and `closed_at`; the parent flips to `partially_closed` and its later full-close `net_pnl` covers only the remaining qty — disjoint, so no double-count) and **excludes** `partially_closed` parents. The `exit_price > 0` guard drops `close_reason='external'` placeholder-zero rows.

⚠️ **Implementation trap (do NOT copy existing queries):** every current stats query in `trade_repository.py` (`:544-545, 653-659, 686-699`) filters `... AND parent_trade_id IS NULL`, which **excludes children and undercounts partials**. The canonical set deliberately OMITS that clause. An implementer who copies an existing query reintroduces the undercount. The correct predicate is exactly `status='closed' AND exit_price > 0` (+ the account join) — no `parent_trade_id` clause.

⚠️ **`net_pnl` is nullable** (`NUMERIC(20,8)`, no NOT NULL/default — `async_persistence.py:103`). Legacy closed rows predating the column are `NULL`, and Python `None > 0` / `None +` raise `TypeError`. The canonical query MUST use `COALESCE(net_pnl, 0)` for sums and `net_pnl IS NOT NULL AND net_pnl > 0` for the win predicate. State this in every fixture.

⚠️ **Win/loss/breakeven classification (pin exactly — used by win_rate, win_count, loss_count, avg_win, avg_loss, profit_factor, max_consecutive):** over the canonical set, classify each trade by `net_pnl`:
- **win** = `net_pnl IS NOT NULL AND net_pnl > 0`
- **loss** = `net_pnl IS NOT NULL AND net_pnl < 0`
- **breakeven/unknown** = `net_pnl IS NULL OR net_pnl = 0` — counted in `total_trades` but in NEITHER `win_count` NOR `loss_count`.
So `win_count + loss_count ≤ total_trades` (equal only when no breakeven/null rows). `win_rate = win_count / total_trades * 100` (denominator is total_trades, NOT win+loss). `avg_win = Σ winners' net_pnl / win_count`; `avg_loss = Σ losers' net_pnl / loss_count`; `profit_factor = Σ winners / |Σ losers|` (`null` when `Σ losers = 0`). Breakeven/null rows contribute 0 to `cum_pnl` (via COALESCE) but never inflate win or loss stats.

**Core computation — cumulative-P&L curve:**
1. Resolve scope → set of eligible `account_id`s via the join above (All = every included account; Live/Demo = by `account_type`; single = one id).
2. Compute the scope's starting-equity denominator `D` per §3 (per-account earliest non-null `trading_cycles.initial_equity`, fallback first-trade `base_capital`, computed per-account-then-summed; null-D accounts excluded from both numerator and denominator). DB-only, no live call.
3. Fetch the canonical trade set in scope ordered by **`closed_at` ascending, `id` ascending** (deterministic tiebreak so same-timestamp closes never reorder between requests). The canonical filter already requires `closed_at IS NOT NULL`, so no closed row sorts nondeterministically. The cumulative sum runs from the **first recorded trade**: `cum_pnl[i] = Σ COALESCE(net_pnl,0)[0..i]`. A selected timeframe **slices the x-axis** to that window (zoom) — values are NOT rebased, so `cum_pnl` stays "cumulative since first trade." (To render a window efficiently, the running total of pre-window trades seeds the first in-window point.)
4. Derive the exchange-independent **equity proxy** `equity_proxy[i] = D + cum_pnl[i]` (one point **per trade**, at that trade's `closed_at`, matching the `equity_curve` granularity — NOT an end-of-day series) and the **drawdown series** from its running peak: `drawdown_pct[i] = (equity_proxy[i] − peak[i]) / peak[i] * 100` — always a true percentage. **The running peak is seeded at `D`** (equity before any trade, i.e. `peak` starts at `equity_proxy` of a notional pre-first-trade point = `D`), so an initial losing streak registers as real drawdown rather than a flat 0 — do NOT seed the peak at `equity_proxy[0]` (the first trade's post-close value), which would hide an early underwater period and inflate Calmar. If `D` is unavailable, drawdown is reported in absolute dollars under a distinct `drawdown_abs` field (never dollars under a `_pct` key). `max_drawdown_pct` and curve metrics are computed over the **selected window's** slice (when zoomed, the running peak is carried in from the pre-window high so an in-window trough isn't understated). `drawdown_duration_days` (defined in the KPI computation block below) measures peak→recovery; if the window's last in-window trade is still below the prior peak, duration = peak→that-last-trade's-`closed_at` and `drawdown_recovered: false`.
5. Derive **daily P&L** (sum `COALESCE(net_pnl,0)` grouped by `DATE(closed_at)` in **UTC**, labeled "UTC") and **monthly P&L** (UTC year-month; `monthly_pnl.return_pct = month_pnl / D * 100`).

**Daily-return bucketing (required before Sharpe/Sortino/Calmar — High; pin these exactly so two engineers get identical numbers):**
`portfolio_stats.calc_sharpe/calc_sortino(daily_returns)` annualize by `√365`; `calc_calmar(daily_returns, max_drawdown)` divides annualized mean **return %** by max-drawdown **%**. The daily series MUST be **percentages**. Exact, unambiguous construction:
1. **Day set = every UTC calendar day from the first trading day to the last, INCLUSIVE (forward-filled), NOT only days with trades.** Build `equity_proxy[d] = D + cum_pnl[d]` where `cum_pnl[d]` is the cumulative net P&L through end of UTC day `d` (carried forward on no-trade days). A no-trade day therefore contributes a `0.0%` return — this is the intended, standard treatment; do NOT use the sparse trading-days-only series for the ratio inputs (that would overstate the mean). *(The `< 10` gate below counts distinct **trading** days — days with ≥1 close — a data-sufficiency check; it is a different quantity from the calendar series used for the math. Both are defined here so they're never conflated.)*
2. **First day:** `daily_return_pct[d0] = cum_pnl[d0] / D * 100` (seed the prior value at `D`, i.e. equity before any trades). No day is dropped.
3. `daily_return_pct[d] = (equity_proxy[d] − equity_proxy[d-1]) / equity_proxy[d-1] * 100` for `d > d0`.
4. **Calmar sign:** pass **`abs(max_drawdown_pct)`** (a positive magnitude) to `calc_calmar` so the ratio is positive (matches existing `accounts_service.py:1213` which uses `max(drawdowns)`); never pass the stored negative `max_drawdown_pct` directly.
5. **Windowing the series (for non-ALL timeframes):** build the all-history daily-% series once (steps 1–3), then **restrict the inputs fed to the ratios to days whose date falls in the `[start, anchor)` window** (§4.2). The first in-window day keeps its return computed against the **prior calendar day's `equity_proxy`** (the recurrence in step 3) — do NOT re-seed a window's first day at `D`. (Step 2's `D`-seed applies only to the genuine first trading day of all history.) The `<10` trading-day sufficiency gate counts trading days **within the window**. This makes Sharpe/Sortino/Calmar deterministic for every timeframe, not just ALL.

**`D` is always the DB denominator — never live equity — so these ratios are deterministic regardless of Bybit availability.** If `D` is `null`/≤0, the three ratios are `null`. Data-sufficiency: when distinct **trading-day** count `< 10`, return them `null` (UI "—" + "needs ≥10 trading days" hint), never `0.0`. **Degenerate-but-sufficient case (≥10 trading days):** if return variance is 0 (Sharpe/Sortino undefined) or `max_drawdown == 0` (Calmar undefined), return that ratio `null`, NOT the `0.0` the raw helper would emit — gate before calling, and do not let the helpers' internal NaN→`0.0` clamp leak through.

**KPI computation:**
- **Trade-derived (from the canonical set — fully exchange-independent):** `net_pnl` (sum of `COALESCE(net_pnl,0)`), `realized_pnl_gross` (gross `realized_pnl` sum, reference only), `total_return_pct` (= `window Σ net_pnl / D * 100`; numerator and `D` are clearly both defined — `D` is the scope starting equity per §3, NOT `Σ base_capital` over trades; labeled "Return (recorded history)"; `null` when `D ≤ 0`), `win_rate`, `win_count`, `loss_count`, `profit_factor`, `expectancy`, `avg_win`, `avg_loss`, `avg_win_loss_ratio`, `best_trade`/`worst_trade` (single best/worst trade `net_pnl` — per-TRADE, not per-day), `max_consecutive_wins`/`max_consecutive_losses` (**fed the per-trade win/loss sequence ordered by `closed_at, id`** — each trade classified win/loss/breakeven per the canonical rule; NOT the forward-filled daily series, whose no-trade `0`s would falsely break streaks; breakeven/null trades break a streak), `avg_hold_time_hours` (mean of `closed_at − opened_at` over trades with non-null `opened_at`), `total_trades`. **Win definition is `net_pnl > 0` everywhere** (matches `signal_performance.is_win`, so Overview and Signals agree).
- **Curve-derived (over the selected window):** `max_drawdown_pct` (negative %; or `max_drawdown_abs` when `D` null), `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` (via the daily-bucketed percentage series; Calmar uses `abs(max_drawdown_pct)`), `drawdown_duration_days` — the duration of the **single deepest** drawdown episode (the one containing `max_drawdown_pct`): from the running-peak point that precedes its trough to the first later point that reclaims that peak; value = `(recovery.closed_at − peak.closed_at)` in days, **rounded down to a whole day** (`floor`, an integer field). If that episode never recovers within the window, duration = `(last-in-window trade.closed_at − peak.closed_at)` floored and `drawdown_recovered: false`. (NOT `portfolio_stats.calc_drawdown_duration`, which counts snapshot *periods*.)
- **Live-overlay (best-effort cosmetic, from `get_dashboard` aggregation, NOT trades):** `total_equity`, `unrealized_pnl`, `open_count`. Marked `live_sourced`. If the live fetch fails OR any in-scope account is degraded, these return `null` (UI "—" + "live data unavailable") while the entire curve and every trade-derived/curve-derived KPI still render. **No curve point and no KPI depends on a live read.**

**Consistency rule — window scope:** the curve slice, `max_drawdown_pct`, the risk ratios, AND the `total_return_pct` numerator are ALL over the **same selected window**; only `D` (the denominator) is the all-history starting equity. This is stated so an implementer never mixes a windowed numerator with an all-time denominator inconsistently — `total_return_pct` is explicitly "this window's P&L as a % of starting equity," labeled accordingly in the UI.

**Helper-reuse reality (corrects the overstated "reuse" framing):** the genuinely reusable pure functions in `portfolio_stats.py` are: `calc_sharpe`/`calc_sortino`/`calc_calmar` — fed the **daily-bucketed percentage return series** (per the daily-return-bucketing block above); and `max_consecutive` — fed the **per-trade win/loss sequence ordered by `closed_at, id`** (NOT the daily series; the daily series' no-trade `0`s would falsely break streaks). Plus the win/profit-factor/expectancy arithmetic pattern (reimplemented over the canonical set). Do NOT call `accounts_service.get_pnl_summary` on the hot path — it wraps the DB `get_closed_pnl_summary` but first triggers a **live Bybit fetch** (`accounts_service.py:721`). `calc_drawdown_duration` is NOT reused (snapshot-period semantics). Cumulative-P&L + drawdown derivation from trades does not exist anywhere and is built fresh.

**All numeric outputs are JSON numbers (float/int), never strings**, coerced at this service boundary. Sum in `Decimal`, coerce to float only at the JSON boundary, to avoid `NUMERIC→float` precision drift. Null-safe: missing/undefined metrics return `null`, never `"NaN"` or `0.0`-as-unknown; every divisor (`D`, prior-day equity, loss totals) is guarded against zero.

**Caveat — `strategy_kind` legacy backfill:** migration 44 backfilled `'trend'` for all pre-existing trades, so per-strategy splits mislabel historical data. The Trades tab notes this; the split uses trade-level `strategy_kind` (not account-level `strategy_cohort`) and surfaces a "legacy data approximate" hint when pre-migration trades are in range.

### 4.2 New router — `backend/routers/performance.py`

Mounted at `/api/v1/performance` per §4.5 (do not double-prefix).

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/performance/overview` | `scope`, `timeframe` | `{ kpis, kpis_prev, equity_curve[], equity_now?, drawdown_series[], daily_pnl[], monthly_pnl[], meta }` |
| GET | `/performance/trades-breakdown` | `scope`, `timeframe` | `{ by_symbol[], by_strategy[], by_close_reason[], pnl_distribution[], hold_time_buckets[], meta }` |
| GET | `/performance/trades` | `scope`, `timeframe`, `sort`, `dir`, `cursor`, `limit` | `{ rows[], cursor, has_more }` — paginated raw trade rows for the per-trade table |
| GET | `/performance/live` | `scope` | `{ positions[], account_tiles[], sector_concentration[], degraded }` |

**Note — breakdown vs rows:** `trades-breakdown` returns bounded GROUP BY aggregates (no pagination needed). The sortable/paginated per-trade table is a **separate** `/performance/trades` endpoint with an opaque cursor = `(sort_value, id)` — you cannot cursor-paginate aggregate buckets, so the two concerns are split (fixes the earlier "paginate the aggregates" incoherence).

**Scope semantics (single param):** `scope` is ONE string token: `all` (every account with `include_in_analytics`), `live` (all live accounts), `demo` (all demo accounts), or an **account id** (single account). The UI exposes exactly one scope control (an `AccountSelector`-style dropdown: All / Live / Demo, then individual accounts) — no separate Live/Demo toggle. `timeframe ∈ {1D, 1W, 1M, 3M, YTD, 1Y, ALL}`; unknown tokens → HTTP 422.

**Timeframe→window resolution (pin exactly so windowed KPIs are deterministic):** the window is `[start, anchor)` where `anchor` = the request's current instant in UTC (`now`), and `start` is computed from `anchor` as: `1D` = `anchor − 24h` (rolling, not "today"); `1W` = `anchor − 7d`; `1M` = `anchor − relativedelta(months=1)` (calendar month, not 30d); `3M` = `anchor − relativedelta(months=3)`; `1Y` = `anchor − relativedelta(years=1)`; `YTD` = `Jan 1 of anchor's UTC year 00:00:00Z`; `ALL` = no lower bound (`start = −∞`, the first recorded trade). A trade is in-window iff `start ≤ closed_at < anchor`. `kpis_prev`'s prior window is `[start − (anchor − start), start)` for fixed-length timeframes, and for `YTD` the equal day-count immediately before `Jan 1`. `ALL` has no prior window (`kpis_prev = null`).

**Signals scope mapping (resolves the live/demo gap):** the existing `/signal-analytics/*` endpoints take a single optional `account_id`. The Performance Signals hooks map scope→signals as: `all`→ no `account_id` (all accounts); `<account_id>`→ that id; **`live`/`demo`→ the frontend fans out one request per account of that type and merges client-side** (or, if added in the plan, a new multi-id param). This mapping is an explicit deliverable of the Signals phase, not an assumption.

`kpis_prev` powers hero delta chips. **For `timeframe=ALL` there is no prior window → `kpis_prev` is `null` and the hero hides delta chips. For `YTD`, the prior window is the equal day-count immediately before Jan 1.** `kpis_prev` is computed over the prior window using the SAME trade-derived method and carries its own `total_trades`; when that count `< 3` the UI hides the (noisy) chip. `kpis_prev.total_equity` is the prior-window *realized* equity proxy (`D + cum_pnl` at window end), explicitly a realized figure (the live `total_equity` has no historical analog) — the Total-Equity delta therefore compares "live now" vs "realized at prior-window end" and is labeled an approximate change.

The `overview` `meta` object: `{ currency: "USDT", grouping_tz: "UTC", trading_days: int, starting_equity: float|null, return_basis: "recorded_history", live_equity_available: bool, live_sourced: ["total_equity","unrealized_pnl","open_count"], degraded: bool }`. `starting_equity` is `D`; `live_equity_available` tells the UI whether to show the cosmetic live-equity marker/right-hand axis.

**Pydantic response models** defined in `backend/schemas/__init__.py` (v2), so the contract is typed and validated — unlike the current analytics router which returns raw dicts. Each model documents units (USD vs pct vs ratio).

**Signals tab** reuses the existing `/api/v1/signal-analytics/*` endpoints (`summary`, `win-rate`, `calibration`, `benchmarks`, `regime`, `decay-alerts`) — all verified to exist and accept optional `account_id` (`signal_analytics.py:28-146`). See §4.4 for the critical data-availability precondition (this table can be empty).

**Live tab** is served by the new `GET /performance/live`. Account tiles (`equity`, `today_pnl`, `positions_count`, `account_type`) come from `accounts_service.get_dashboard()` aggregation. **Per-position rows come from `get_positions()` per account** — note `get_dashboard`/`_fetch_card` returns only `positions_count`, NOT position rows (verified `accounts_service.py:765`), so the positions table requires a separate per-account `get_positions` call. Both are live Bybit calls and MUST be fail-soft (§4.3).

### 4.3 Performance, exchange dependency & safety

- **Exchange independence (the headline reliability property):** the Overview and Trades/Trades-breakdown tabs read ONLY the `trades` table — cumulative-P&L curve, drawdown, and every trade-derived KPI render fully **even if Bybit is completely down**. The optional live overlay metrics (`total_equity`/`unrealized_pnl`/`open_count`, the "now" marker, the absolute-equity secondary axis) degrade to "—" without blanking anything. Only the Live tab is exchange-bound. This is what makes the page reliably work — the original bug was a hard dependency on an unpopulated store; v1 has no hard external dependency for its core.
- **Caching:** historical aggregations over `trades` compute on-the-fly — at this app's scale (tens of trades) no cache is needed. A `# TODO: add (scope,timeframe)-keyed TTL cache when trade volume grows` marker suffices; building the cache now is YAGNI. The partial index below is the one cheap durability investment.
- **Index:** existing indexes are account-leading (`idx_trades_account_closed`); `scope=all` ordering across accounts has no covering index. Add partial index `idx_trades_closed_at (closed_at) WHERE status='closed'` via `_MIGRATIONS` — one line, harmless, future-proofs portfolio-wide ordering.
- **Live tab is exchange-bound:** `get_dashboard` issues ~N×3 live Bybit calls and `get_positions` adds one per account. The new `/performance/live` MUST: (a) wrap each account in try/except so one failing account cannot 500 the endpoint (current `get_positions` raises unguarded — verified `accounts_service.py:666-676`), (b) apply a per-account timeout, (c) return partial results with `degraded: true` + per-account `error`, (d) be server-side throttled/cached (~10s) so multiple browser tabs don't multiply exchange load.
- **Empty data:** zero qualifying closed trades → historical endpoints return empty arrays + null KPIs (HTTP 200) → frontend shows "no closed trades yet" + CTA. If open positions exist, the optional live "now" marker may still appear, but the cumulative-P&L curve is legitimately empty (no closed P&L yet) — shown as an empty chart with the marker, not a misleading line.
- **Unredacted:** REST routers return full numbers (redaction is MCP-only). No `financial_detail` flag needed.
- **Single settlement currency (v1):** no per-trade `settle_coin` column, so cross-account P&L summation assumes USDT. v1 filters/validates scope to USDT-settled accounts and labels "USDT"; mixed-settlement portfolios are a documented out-of-scope limitation, not a silent wrong sum.

### 4.4 Signals tab data precondition (prevents repeating the snapshot bug)

The `signal_performance` table is populated **only** when a trade has a linked `scan_result_id` (`trade_service.py:336,444`); manual, external, and unlinked cycle trades produce NO rows, and **no backfill exists**. For users who trade manually or via cycles, the Signals surface can be as empty as snapshots were.

Mitigations (mandatory):
1. **Implementation-time check:** run `SELECT count(*) FROM signal_performance` for the target accounts BEFORE building the five visualizations.
2. **Coverage-gated build:** if coverage is ~0, ship ONLY the rolling win-rate view + the honest empty card; defer calibration/benchmark/regime/decay until coverage is confirmed nontrivial. Don't build five charts for empty data.
3. **Honest empty state:** zero signals → explanatory card ("Signal analytics become available once trades are placed from scanner signals"), never a blank/0.0 surface.
4. **Win definition parity:** `signal_performance.is_win` uses `net_pnl > 0`; Overview uses the same (§4.1), so win rates agree.
5. **Scope mapping:** live/demo scope fans out per-account signal requests merged client-side (§4.2).
6. **Phasing:** Signals is **Phase 4**, gated on the coverage check (§12) — it never blocks the core Overview fix.

### 4.5 Router mounting (exact pattern — avoids double-prefix)

`/api/v1` is applied **per-router** at include time (`main.py:736-758`). Define the new router as `APIRouter(prefix="/performance", tags=["performance"])` and register it with `app.include_router(performance_router, prefix="/api/v1")` → yields `/api/v1/performance/*`. Do NOT put `/api/v1` inside the router's own `prefix` (that double-prefixes to `/api/v1/api/v1/performance`).

**Pydantic models** go in `backend/schemas/__init__.py` (confirmed Pydantic v2, `ConfigDict(extra="forbid")`). No existing `Performance*` class — name them `Performance*` (e.g. `PerformanceOverviewResponse`, `PerformanceKpis`, `PerformanceLiveResponse`) to avoid confusion with the neighboring `TradeStatsResponse`/`StrategyDirectionStats`.

---

## 5. Frontend Design

### 5.1 Component structure

The 604-line `AnalyticsDashboard.tsx` is replaced by a focused composition. New/changed files under `frontend/src/components/analytics/`:

| File | Purpose |
|---|---|
| `PerformanceDashboard.tsx` (new top-level) | Orchestrates ControlBar + HeroStrip + Tabs; owns scope/timeframe state (persisted to `localStorage`). Named to avoid colliding with the existing `PerformancePage` wrapper in `route-tree.tsx`. |
| `PerformanceControlBar.tsx` | **Single** scope selector (All / Live / Demo / individual account, via an `AccountSelector`-style dropdown) + timeframe picker. No separate Live/Demo toggle. |
| `PerformanceHeroStrip.tsx` | 5 sticky KPI cards w/ AnimatedNumber + delta-vs-prior-window chip + sparkline (only where a series exists — see note) |
| `tabs/OverviewTab.tsx` | EquityCurve, Drawdown, DailyPnl, MonthlyHeatmap, KpiGrid |
| `tabs/TradesTab.tsx` | per-symbol, per-strategy, close-reason, P&L distribution, hold-time |
| `tabs/SignalsTab.tsx` | rolling win-rate, calibration, benchmark, regime, decay alerts (honest empty state — §4.4) |
| `tabs/LiveTab.tsx` | open positions table, account tiles, sector concentration |
| `hooks/usePerformance.ts` | TanStack Query hooks: `usePerformanceOverview`, `useTradesBreakdown`, `usePerformanceLive`, plus per-endpoint signal-analytics hooks (new — none exist today, see note) |

**Rewrite vs reuse (corrects the earlier "restyle only" framing — these are real rewrites, not cosmetic):**
- **Charts are prop-interface rewrites, not restyles.** All four existing charts (`EquityCurveChart`/`DrawdownChart`/`DailyPnlChart`/`MonthlyPnlGrid`) currently take `snapshots: DailySnapshot[]` and read snapshot-specific fields (`snapshot_date`, `equity`, `peak_equity`, `drawdown_pct`, `realised_pnl`); `MonthlyPnlGrid` buckets to months client-side. The new API shapes (§7) use different field names (`t`, `pnl`, etc.) and pre-bucket server-side. Each chart's props must change; budget this as rewrite work, keep only the Recharts visual scaffolding.
- **`KpiCards.tsx` is a rewrite.** It currently binds `PerformanceAnalytics` fields (`total_pnl` string, `best_day_pct`, `snapshot_count`…) that don't match the new numeric `kpis`. Nearly every binding changes; new fields (`total_equity`, `unrealized_pnl`, `avg_hold_time_hours`, `open_count`) are added; snapshot-era fields (`snapshot_count`, `recovery_time_days`) are dropped.
- **4 existing test files break and must be migrated/rewritten:** `analytics/__tests__/Charts.test.tsx`, `DailyPnlChart.test.tsx`, `KpiCards.test.tsx`, `MonthlyPnlGrid.test.tsx` feed the old shapes. The plan explicitly budgets updating/replacing these alongside the component rewrites (not just adding new tests).
- **Signal-analytics client work is NOT free.** There are no per-endpoint client functions today; `SignalAnalyticsPage` uses one bulk query with a static key and **no `account_id`**. Scope-aware Signals hooks (`usePerformance.ts`) must be built new, and the existing signal-analytics endpoints must be confirmed to honor `account_id` end-to-end.
- **Shared formatters — MERGE, do not move (a `lib/format.ts` already exists).** `frontend/src/lib/format.ts` already exists with `formatDuration`/`formatDurationBetween`/`formatDateTimeLabel` (and its own test). `backtest/format.ts` has a different export set (`formatUsd`/`formatPct`/`formatRatio`/`formatHours`/`formatDateTime`/`formatInt`/`formatCloseReason`/`signOf`/`pnlColorClass`). The plan must **merge** the backtest formatters INTO the existing `lib/format.ts` (reconciling the near-duplicate `formatDateTime` vs `formatDateTimeLabel`), then update the **7 importers** of `backtest/format` (`BacktestAnalysisTab`, `BacktestComparePage`, `BacktestListPage`, `BacktestResultsPage`, `MetricsGrid`, `TradeListTable`, + the backtest format test). A naive create/move would clobber the existing module and break its consumers.
- **Genuinely reusable as-is (no rewrite):** `ui/animated-number.tsx`, `ui/skeleton.tsx`; `layout/PageHeader.tsx`; `backtest/MetricsGrid.tsx` as a visual pattern.
- **Needs extension, not as-is reuse:** `ui/AccountSelector.tsx` is currently 2-way (`portfolio` | `<account_id>`, verified `AccountSelector.tsx:6-135`) and cannot express the 4-way scope. It must be extended with `Live`/`Demo` group options (the data exists — `DashboardCard.account_type`), or a small dedicated `ScopeSelector` built. Do not assume drop-in reuse.
- **Tab primitive — standardize on `NeuTabs`.** The embedding host `AccountDetailView` already uses `NeuTabs` from `@/design-system/neumorphism` (not `ui/tabs.tsx`). To keep one neumorphic system (a stated goal) the Performance page uses `NeuTabs` too; `ui/tabs.tsx` is NOT used here.
- **Naming:** a local `function PerformancePage()` already exists in `route-tree.tsx`. The new top-level component should be named `PerformanceDashboard` (file `PerformanceDashboard.tsx`) to avoid a symbol collision when wired into the route; the route file keeps its thin wrapper.
- `CleanupDialog.tsx` — retained (snapshot cleanup still valid as a secondary action, de-emphasized).

**Hero delta/sparkline data source (resolves the "no data for deltas" gap):** the `overview` endpoint returns `kpis_prev` — the same metrics over the immediately preceding equal-length window — so each card shows a delta vs the prior period. **For `timeframe=ALL`, `kpis_prev` is `null` and delta chips are hidden** (no prior window exists); for `YTD` the prior window is the equal day-count before Jan 1. Delta chips are also hidden when the prior window has too few trades to be meaningful (`< 3`), to avoid authoritative-looking noise on a young account. The **Total Equity** card is special: its current value is live (`total_equity`), but `kpis_prev.total_equity` is a *realized* prior-window figure, so its delta is labeled an approximate change (live-now vs realized-then). Sparklines render only for the two cards backed by a series — the **Total Equity** card draws the `equity_curve` (cumulative-P&L) trajectory, and the **Net P&L** card draws `daily_pnl`; Win Rate / Sharpe / Max DD show the delta chip only.

The old `AnalyticsDashboard.tsx` is also embedded in `AccountDetailView` via `<AnalyticsDashboard accountId={accountId} embedded />` (verified `AccountDetailView.tsx:434`, signature `AnalyticsDashboard({ accountId, embedded = false })`). The new `PerformanceDashboard` must preserve this exact two-prop contract (when `embedded`: hide the page header/scope selector, force `scope = accountId`, optionally condense the hero). An explicit regression test covers it.

### 5.2 Page layout

```
┌─ CONTROL BAR ─────────────────────────────────────────────┐
│ Scope:[ All ▾]                     1D 1W 1M 3M YTD 1Y ALL  │
│   (All / Live / Demo / <account>)                          │
├─ HERO STRIP (sticky) ─────────────────────────────────────┤
│ Total Equity │ Net P&L │ Win Rate │ Sharpe │ Max DD        │
│  $199.02 ▴   │ +$12.50 ▲│  62.5%   │  1.8   │ -4.2%         │
│  (sparkline) │(sparkln)│ (delta)  │(delta) │ (delta)       │
├─ TABS ────────────────────────────────────────────────────┤
│ [ Overview ] [ Trades ] [ Signals ] [ Live ]              │
├───────────────────────────────────────────────────────────┤
│ (active tab content)                                       │
└───────────────────────────────────────────────────────────┘
```
*Total Equity is the only live-sourced hero metric (open positions + wallet), labeled "now" and degrading to "—" if Bybit is down; the other four are historical/trade-derived and always render. Sparklines appear on Total Equity and Net P&L only; the other three show a delta-vs-prior-window chip. Delta chips hide for `timeframe=ALL` and on accounts with a too-thin prior window.*

### 5.3 Tab content detail

**Overview** — big **Cumulative P&L** gradient area chart (cumulative since first trade; a timeframe slices the x-axis, not rebases; primary y-axis is "Cumulative P&L", with an absolute-equity secondary axis + live "now" marker shown when live data is available, falling back to the cumulative-P&L axis alone when Bybit is down); drawdown underwater chart; daily P&L emerald/red bars; monthly P&L heatmap; full KPI grid grouped Returns / Risk / Quality / Consistency. The chart renders fully from trade data even when Bybit is down.

**Trades** — per-symbol leaderboard; per-strategy split (trend vs mean-reversion, with the "legacy `strategy_kind` approximate" hint when pre-migration trades are in range) as paired cards; close-reason donut (display buckets mapped from real `close_reason` literals per the §7 taxonomy note — Take Profit / Stop Loss / Liquidation / ADL / External / Manual / Rule / Cycle; no invented Trailing/Breakeven slices, unmapped literals shown raw not dropped); P&L distribution histogram; hold-time buckets — all from `/performance/trades-breakdown` (bounded aggregates). The **raw per-trade table** below them is **server-side sorted + cursor-paginated** via the separate `/performance/trades` endpoint (default sort = net P&L desc, page size 50), so large histories don't ship everything to the client.

**Signals** — rolling win-rate line; confidence calibration curve (predicted vs realized by tier); benchmark comparison (system vs buy-and-hold vs random); win rate by market regime; active decay alerts list. Surfaces the existing `/signal-analytics` data — **with the honest empty state from §4.4** when the scope has no linked signals.

**Live** — open positions table (symbol, side, size, leverage, entry, live unrealized P&L, color-coded); account equity tiles (live vs demo, equity, today's P&L, positions count); sector concentration horizontal bars. A `degraded` banner appears if any account's live fetch failed (partial data shown, not a blank tab).

### 5.4 Timeframe, scope & query behavior

- Timeframes: **1D / 1W / 1M / 3M / YTD / 1Y / ALL** — all backed by trade history, none dead. Sub-day buckets removed. Server resolves each token to a `[start, anchor)` UTC window per the exact rules in §4.2; unknown token → 422.
- Default timeframe: **ALL**. Default scope: **All**. (ALL is the default because the target account has few trades over a short span — defaulting to 1M would show a near-empty window and read as "still broken." ALL shows the full history immediately.)
- **Low-data UX (the real target account has roughly a dozen-plus trades over only a few trading days — the page must still look complete, not sparse; the §7 example numbers are an illustrative larger scope, not this account):**
  - When `meta.live_equity_available`, the Overview chart **shows the absolute-equity secondary (right-hand) axis prominently** — same `D + cum_pnl` series, just an equity-framed read-out alongside the primary "Cumulative P&L" axis — plus the live "now" marker; it falls back to the cumulative-P&L axis alone when live data is down. (The primary y-axis is always "Cumulative P&L"; the equity axis is the secondary read, per §3/§6.)
  - When Sharpe/Sortino/Calmar are `null` (<10 trading days), **collapse the Risk group into a single "needs ≥10 trading days" notice** rather than three bare "—" tiles.
  - Lead the KPI grid with the metrics that ARE populated at low volume (Net P&L, Win Rate, Profit Factor, Best/Worst trade, Avg Win/Loss), so the first screen looks substantive.
  - Hide (don't dim) delta chips when `kpis_prev` is null/thin, so the hero looks intentional, not broken.
- Scope + timeframe persisted to `localStorage` (`performance-filters`) and encoded into TanStack Query keys so caching is per-view (no abort races — fixes the old manual-fetch fragility).
- **Per-query cache policy (must override the global 30-min `staleTime` + `PersistQueryClientProvider` set in `App.tsx`):**
  - Historical (`overview`, `trades-breakdown`): `staleTime` ~60s, normal caching/persistence.
  - Live (`/performance/live`): `refetchInterval` ~15s **only while the Live tab is mounted/visible**, `staleTime: 0`. **Excluded from sessionStorage persistence via a `shouldDehydrateQuery` predicate** in the `persistOptions` at `App.tsx` (TanStack v5 cannot opt a single hook out of persistence — it requires the provider-level predicate, where dehydrate logic already exists for the LLM-key case). A restored stale unrealized-P&L number would mislead. Inactive tabs do not poll.
- Tab switches reuse cached data (no forced refetch); the Live tab starts its interval on mount and clears it on unmount.

### 5.5 States, formatting & responsive

- **Loading:** card-shaped skeletons matching final layout (reuse `ui/skeleton.tsx`).
- **Empty:** distinct per tab — Overview/Trades show "no closed trades yet" + CTA to Scanner/Auto-trade (never the old "take a snapshot" dead-end); Signals shows the §4.4 explanatory empty card; Live shows "no open positions."
- **Error:** inline error card per query with a retry button; one failing tab (or a degraded Live fetch) does not blank the whole page.
- **Numeric safety:** all values coerced to numbers at the hook boundary; `null`/missing → em-dash "—", never `NaN` or a misleading `0.0`.
- **Formatting:** money via shared `formatUsd` (2 dp, thousands sep), pct via `formatPct` (1–2 dp), ratios via `formatRatio` (2 dp); all from the promoted `lib/format.ts`. Daily/monthly groupings labeled "UTC".
- **Accessibility:** profit/loss is not color-only — pair each colored value with a sign (`+`/`−`) and an `aria-label`; charts get accessible titles/summaries; the page is keyboard-navigable.
- **Responsive:** the app has a mobile dock, so the hero strip wraps to a 2-row grid on narrow widths, tabs become horizontally scrollable, and tables switch to stacked cards or horizontal scroll below the `md` breakpoint.

---

## 6. Visual Design (Refined Neumorphic)

Stays native to the existing design system — `--neu-*` tokens (`frontend/src/design-system/neumorphism/styles.css`), Geist Variable font, warm orange accent `oklch(0.58 0.16 28)`, raised dual-shadow cards, 12/16/22px radii, pill chips. Light "clay" base + graphite dark mode both supported.

- **Hero strip:** 5 raised neu-cards, each = label + `AnimatedNumber` value + delta-vs-prior-window chip (▲ emerald / ▼ red, hidden when `kpis_prev` null/thin). Sparkline on Total Equity (draws the `equity_curve` cumulative-P&L trajectory) and Net P&L (draws `daily_pnl`). Sticky on scroll.
- **Charts:** Recharts (already installed `^3.8.1`) — visual treatment: the main chart is the cumulative-P&L curve (primary y-axis "Cumulative P&L"); when `meta.live_equity_available` it adds an **absolute-equity secondary right-hand axis** (`D + cum_pnl`, the "your equity" read-out) plus a dashed live-"now" marker, falling back to the cumulative-P&L axis alone when live data is down — same underlying series either way (gradient area, accent → transparent); drawdown = red-tinted underwater area (% via `equity_proxy`); daily P&L = emerald/red bars; monthly = neu heat-grid. All colors from CSS vars so both themes work. (The chart components are rewritten for the new prop shapes per §5.1 — this section describes only appearance.)
- **KPI grid:** soft raised tiles, color-coded (emerald good / red bad / amber caution), grouped by category.
- **Tabs:** `NeuTabs` from the neumorphism design system (the same primitive `AccountDetailView` uses) — NOT `ui/tabs.tsx` — with an inset-shadow active state.
- **Tables:** neu-surface rows, monospace numbers for alignment, hover lift, color-coded P&L.
- **Motion:** framer-motion KPI count-ups + gentle stagger-in on tab switch; skeletons match card shapes.
- **Consistency cleanup:** the page uses **only** neumorphism tokens (the old page mixed shadcn + neu inconsistently).

Color convention (app-wide): emerald = profit, red/destructive = loss, amber = caution.

---

## 7. API Contract (response shapes)

Illustrative shapes; exact Pydantic models finalized in the plan. All money in **USDT** (single-settlement assumption, §4.3). All numbers are JSON numbers (never strings). Any metric that cannot be computed is `null` (rendered "—"), never `0.0` or `"NaN"`. `_pct` fields are percentages, `_ratio` fields are ratios, `_abs` fields are absolute USDT. Example numbers are mutually consistent: starting equity `D`=174.00, all-time cumulative net P&L=26.62 → realized equity now=200.62; live `total_equity`=199.02 differs by `unrealized_pnl`=−1.60 (the honest open-position gap). The 1M window contributed net_pnl=12.50 → `total_return_pct`=12.50/174.00=7.2%.

```jsonc
// GET /api/v1/performance/overview?scope=all&timeframe=1M
{
  "kpis": {
    // live-overlay (best-effort cosmetic from get_dashboard; ALL null together if Bybit degraded)
    "total_equity": 199.02, "unrealized_pnl": -1.60, "open_count": 1,
    // trade-derived (canonical closed set; exchange-independent; net_pnl fee-netted; WINDOW-scoped)
    "net_pnl": 12.50, "realized_pnl_gross": 14.10, "total_return_pct": 7.2,
    "win_rate": 62.5, "win_count": 10, "loss_count": 6, "profit_factor": 1.9,
    "expectancy": 0.78, "avg_win": 2.64, "avg_loss": -2.31, "avg_win_loss_ratio": 1.14,
    // ^ reconciles: gross win 10×2.64=26.4, gross loss 6×2.31=13.9, net≈12.5, PF=26.4/13.9≈1.9, exp=12.5/16≈0.78
    "best_trade": 5.1, "worst_trade": -3.3,
    "max_consecutive_wins": 4, "max_consecutive_losses": 2,
    "total_trades": 16, "avg_hold_time_hours": 8.4,
    // curve-derived over the selected window (ratios null when <10 trading days or D null)
    "max_drawdown_pct": -4.2, "max_drawdown_abs": null,
    "drawdown_duration_days": 3, "drawdown_recovered": true,
    "sharpe_ratio": 1.8, "sortino_ratio": 2.4, "calmar_ratio": 1.1
  },
  // prior equal-length window — powers hero delta chips. null for timeframe=ALL.
  // carries total_trades so UI hides the chip when <3; total_equity here is the prior-window REALIZED proxy.
  "kpis_prev": { "total_equity": 188.1, "net_pnl": 7.1, "win_rate": 58.0,
                 "sharpe_ratio": 1.4, "max_drawdown_pct": -5.0, "total_trades": 6 },
  // PRIMARY curve = cumulative net P&L since FIRST trade (NOT rebased). A timeframe slices the x-axis,
  // so the 1M window shows the all-time line's last month: cum_pnl runs 14.12 -> 26.62 here.
  // One point PER TRADE at its closed_at (not an end-of-day series).
  "equity_curve":   [{ "t": "2026-05-15T08:42:11Z", "cum_pnl": 14.12, "peak": 14.12 }],
  // cosmetic live marker; omitted when degraded. May differ from D+cum_pnl by unrealized/flows.
  "equity_now":     { "t": "2026-06-14T12:00:00Z", "equity": 199.02 },
  "drawdown_series":[{ "t": "2026-05-15T08:42:11Z", "drawdown_pct": 0.0 }],  // per-trade; % uses equity_proxy=D+cum_pnl, peak seeded at D
  "daily_pnl":      [{ "date": "2026-05-15", "pnl": 2.3 }],   // pnl = net_pnl, UTC day
  "monthly_pnl":    [{ "month": "2026-05", "pnl": 8.1, "return_pct": 4.7 }], // return_pct = month_pnl / D
  "meta": { "currency": "USDT", "grouping_tz": "UTC", "trading_days": 14,
            "starting_equity": 174.00, "return_basis": "recorded_history",
            "live_equity_available": true,
            "live_sourced": ["total_equity","unrealized_pnl","open_count"],
            "degraded": false }
}

// GET /api/v1/performance/trades-breakdown?scope=all&timeframe=1M   (bounded aggregates, no pagination)
{
  "by_symbol":      [{ "symbol": "BTCUSDT", "trades": 5, "win_rate": 60.0, "pnl": 7.2 }],
  "by_strategy":    [{ "strategy": "trend", "trades": 11, "win_rate": 63.6, "pnl": 9.8 },
                     { "strategy": "mean_reversion", "trades": 5, "win_rate": 60.0, "pnl": 2.7 }],
  "by_close_reason":[{ "reason": "take_profit", "count": 8, "pnl": 18.4 }],  // see taxonomy note below
  "pnl_distribution":[{ "bucket": "0 to 2%", "count": 4 }],
  "hold_time_buckets":[{ "bucket": "<1h", "count": 3, "win_rate": 66.7 }],
  "meta": { "strategy_legacy_approximate": true }  // pre-migration-44 trades in range
}

// GET /api/v1/performance/trades?scope=all&timeframe=1M&sort=net_pnl&dir=desc&cursor=&limit=50
// default sort net_pnl desc; ORDER BY COALESCE(net_pnl,'-inf') DESC, id DESC with the SAME
// expression encoded in the cursor so NULLs and ties never skip/duplicate rows under live inserts.
{
  "rows": [{ "id": "...", "symbol": "BTCUSDT", "side": "Buy", "net_pnl": 3.1,
             "net_pnl_pct": 1.6, "close_reason": "take_profit",  // net_pnl_pct = net_pnl / trade.base_capital * 100
             "opened_at": "...", "closed_at": "...", "hold_hours": 6.2 }],
  "cursor": "eyJ2IjozLjEsImlkIjoiLi4uIn0=",   // opaque (sort_value, id)
  "has_more": true
}

// GET /api/v1/performance/live?scope=all
{
  "positions": [{ "account_id": "...", "symbol": "ETHUSDT", "side": "Buy",
                  "size": 0.1, "leverage": 20, "entry": 2950.0,
                  "unrealized_pnl": -1.6, "unrealized_pnl_pct": -2.7 }],
  "account_tiles": [{ "account_id": "...", "label": "Main (Live)", "type": "live",
                      "equity": 120.0, "today_pnl": 1.2, "positions_count": 1,
                      "error": null }],   // per-account error when that account's fetch failed
  "sector_concentration": [{ "sector": "L1", "exposure_pct": 45.0, "positions": 2 }],
  "degraded": false   // true if any account fetch failed; partial data still returned
}
```

**Close-reason taxonomy (match real DB values, not invented buckets):** the actual `close_reason` literals include `take_profit`, `stop_loss`, `external`, `liquidation`, `adl`, `manual_single`, `manual_close_all`, `rule_triggered`, `cycle_target`, `cycle_drawdown` (the `trades.close_reason` CHECK constraint is the source of truth — enumerate it at implementation time). There is **no `trailing` or `breakeven` literal** — trailing/breakeven exits are recorded as `take_profit`/`stop_loss`. The breakdown does `GROUP BY close_reason` (so every literal sums correctly) and maps to display buckets: **Take Profit / Stop Loss / Liquidation / ADL / External / Manual** (folding `manual_single`+`manual_close_all`→Manual) **/ Rule / Cycle** (folding `rule_triggered`→Rule, `cycle_target`+`cycle_drawdown`→Cycle), with any unmapped literal shown under its raw label rather than dropped. Do NOT show empty "Trailing"/"Breakeven" slices.

**Signals tab contract:** the Signals tab consumes the existing `/api/v1/signal-analytics/{summary,win-rate,calibration,benchmarks,regime,decay-alerts}` endpoints (shapes owned by those routers, not redefined here). The plan must (a) confirm each honors `account_id`, (b) implement the live/demo→multi-account fan-out (§4.2), and (c) pin the exact fields each of the five sub-views needs before building them, gated on the §4.4 coverage check.

---

## 8. Testing Strategy (TDD — non-negotiable per project rules)

### Backend (`tests/backend/`, pytest + pytest-asyncio)

- **Canonical trade-set filter:** partial-close child rows ARE summed; `partially_closed` parents and `exit_price=0`/`external` rows excluded; **NO `parent_trade_id IS NULL` clause** (a test asserts a copied-from-old-query version would undercount); curve and KPIs use the identical set (one fixture asserts both agree).
- **NULL-safety:** a fixture with `net_pnl IS NULL` legacy closed rows → `COALESCE(...,0)` keeps the curve/sums from raising; the win predicate (`net_pnl IS NOT NULL AND net_pnl > 0`) excludes them.
- **Cumulative-P&L curve:** known `net_pnl` fixtures → expected curve using **`net_pnl`** (not gross), accumulated from the FIRST recorded trade (origin 0); a timeframe **slices** the x-axis (zoom) and does NOT rebase y-values (a fixture asserts the 1M slice's `cum_pnl` equals the all-time line over that month, not a from-0 window). Ordered by `closed_at`.
- **Starting-equity denominator `D`:** `D` = Σ per-account earliest **non-null** `trading_cycles.initial_equity` (fallback first-trade `base_capital`), computed **per-account-then-summed** — a fixture with 2 accounts × 2 cycles each asserts no double-counting (D = sum of two values, not four) and that `D` is NOT `Σ base_capital` over trades; `COALESCE`-guarded; `D ≤ 0`/missing → that account's `%`/ratios `null`, no divide-by-zero.
- **Aggregate null-D rule:** a multi-account scope containing one null-D account (manual, no cycle, null base_capital) with positive P&L → that account is excluded from BOTH numerator and denominator of scope `%`/ratio metrics (its profit is NOT divided by other accounts' capital); a fixture asserts the scope `total_return_pct` is not inflated, and that all-null-D scope → `%`/ratios "—" while dollar metrics still render.
- **Exchange independence + determinism:** with the live dashboard fetch mocked to **raise/timeout**, `overview` still returns the full curve + ALL trade-derived AND curve-derived KPIs (including Sharpe/Sortino/Calmar, since they use DB `D` not live equity), `live_sourced` fields `null`, `meta.live_equity_available=false`, `equity_now` omitted; a second test asserts the risk ratios are **identical** whether or not the live fetch succeeds (determinism).
- **Drawdown units:** with `D` present, `drawdown_pct` uses `equity_proxy = D + cum_pnl` (true %); with `D` null, `max_drawdown_abs` is populated and `max_drawdown_pct` is `null` — never dollars under a `_pct` key.
- **Daily bucketing & ratios:** UTC-day **percentage** returns from `equity_proxy` before Sharpe/Sortino/Calmar (Calmar uses pct, not dollars); `<10` trading days → those three `null`, not `0.0`; `drawdown_duration_days` is real day-deltas.
- **KPI math** vs hand-computed values: win_rate (`win_count/total_trades`), profit_factor, expectancy, avg_win/avg_loss, avg_win_loss_ratio, `best_trade`/`worst_trade` (per-trade max/min `net_pnl`), `total_return_pct` (`window Σ net_pnl / D`, window numerator + all-history `D` denominator stated), `realized_pnl_gross` distinct from `net_pnl`.
- **Win/loss/breakeven classification:** a fixture with a winner, a loser, a `net_pnl=0` breakeven, and a `net_pnl IS NULL` row asserts win_count and loss_count each exclude the breakeven AND the null (win+loss < total_trades), win_rate divides by total_trades, and avg_loss divides by loss_count only.
- **max_consecutive input series:** a fixture with wins separated by a no-trade calendar day asserts `max_consecutive_wins` is computed over the **per-trade** `closed_at`-ordered sequence (streak preserved across the gap), NOT the forward-filled daily series (which would break it); a breakeven/null trade between two wins breaks the streak.
- **drawdown_duration_days:** computed for the single deepest episode (peak-before-trough → reclaim), floored to an integer; unrecovered episode → `drawdown_recovered: false`, duration = peak→last-in-window.
- **Daily-return series construction:** forward-filled UTC-calendar-day series (no-trade days = 0% return), first day seeded at `D` (`return[d0]=cum_pnl[d0]/D`); Calmar fed `abs(max_drawdown_pct)` → positive; degenerate ≥10-day cases (zero variance, zero drawdown) → ratio `null` not `0.0`; a fixture asserts the calendar-fill series differs from a sparse trading-days series and that the calendar one is used.
- **Drawdown peak seed:** an **early-losing-streak** fixture (account goes underwater before ever exceeding `D`) asserts the running peak is seeded at `D` → first losing trade registers real drawdown; a test proves seeding at `equity_proxy[0]` instead would understate `max_drawdown_pct` and inflate `calmar_ratio` (guards against the naive `cummax` implementation). Drawdown/equity series are per-trade at `closed_at` (not end-of-day). Unrecovered window → `drawdown_recovered: false`, duration = peak→last-in-window trade.
- **Window scoping:** curve slice, `max_drawdown_pct`, risk ratios, and `total_return_pct` numerator are ALL over the same selected window; only `D` is all-history (a fixture pins this so no windowed/all-time mix slips in).
- **kpis_prev windows:** prior window correct for 1D…1Y; **`null` for ALL**; YTD prior = equal day-count before Jan 1; `kpis_prev.total_trades < 3` → flagged so UI hides the chip; `kpis_prev.total_equity` = realized proxy at prior-window end.
- **Win-definition parity:** Overview win_rate matches `signal_performance.is_win` (`net_pnl > 0`) on a shared fixture.
- **Breakdowns + rows:** aggregates bounded; close-reason `GROUP BY close_reason` over REAL literals (`take_profit/stop_loss/liquidation/adl/external/manual_single/manual_close_all/rule_triggered/cycle_target/cycle_drawdown`) mapped to display buckets, unmapped literal shown raw, no empty Trailing/Breakeven; `/performance/trades` paginates by opaque cursor with `ORDER BY COALESCE(net_pnl,'-inf') DESC, id DESC` — a fixture inserts a new closed trade mid-pagination and asserts no row is skipped or duplicated, and that NULL-`net_pnl` rows order deterministically.
- **Scope & currency:** `scope ∈ {all, live, demo, <account_id>}` resolves via the account join; `include_in_analytics`/`deleted_at` honored; non-USDT accounts excluded/validated; live/demo multi-account resolution correct.
- **Empty & edge:** zero qualifying trades → empty arrays + null trade KPIs (200); open positions but zero closed trades → empty curve + optional `equity_now` only; unknown timeframe → 422.
- **Timeframe window resolution:** `1M = anchor − relativedelta(months=1)` (calendar, not 30d), `1D` = trailing 24h (not "today"), `YTD` = Jan 1 UTC; a trade with `closed_at` exactly at `start` is in-window and one at `anchor` is not (`[start, anchor)`); `kpis_prev` prior window is the equal-length span immediately before `start` (null for ALL). A boundary fixture asserts a trade straddling the cutoff lands in exactly one window.
- **Live endpoint fail-soft:** one account raising → still 200, `degraded:true`, that account's `error` set, others present; per-account timeout honored; positions come from per-account `get_positions` (mocked).
- **Numbers-not-strings invariant**; **Decimal→float only at JSON boundary**.
- **Router mounting:** resolves to `/api/v1/performance/*` (no double prefix); partial index migration applies cleanly.

### Frontend (`frontend/src/components/analytics/__tests__/`, Vitest)

- **Migrate the 4 existing test files** (`Charts.test.tsx`, `DailyPnlChart.test.tsx`, `KpiCards.test.tsx`, `MonthlyPnlGrid.test.tsx`) to the new prop shapes — these break with the chart/KpiCards rewrites and are part of scope, not afterthoughts.
- Hooks: query-key composition per scope/timeframe; numeric coercion; null → "—"; Live query excluded from persistence and polling only while mounted.
- Hero: delta chips computed from `kpis_prev` with correct sign/color; sparklines render only for Total Equity + Net P&L; live-sourced values labeled "now".
- Tabs: each renders with mock data; Overview single-point "now" marker when curve empty but equity present; Trades table sort + pagination controls; Signals honest empty state when zero signals; Live `degraded` banner + per-account error.
- States: loading skeletons; per-tab empty states (no snapshot dead-end); per-query error + retry; one failing tab doesn't blank the page.
- A11y: profit/loss carries sign + aria-label (not color-only). Responsive: hero wraps, tables adapt below `md`.
- Regression: `embedded`/`accountId` mode hides header/selector and scopes to one account (account-detail embedding still works).

### Verification

- Backend: `python -m pytest tests/backend/ -x -q`.
- Frontend: `cd frontend && npx tsc --noEmit && npm run build`.
- Manual: load `/analytics` against a DB with real trades → cumulative-P&L curve renders, KPIs populated, all tabs functional, no `NaN`; with the backend's Bybit calls disabled, the Overview still renders fully (only live-overlay values show "—").

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Curve coupling to live equity re-introduces the blank-page bug during a Bybit outage | **Primary curve is cumulative net P&L, DB-sourced — zero live data needed.** Live equity is a cosmetic overlay that degrades to "—". Explicit "exchange-down still renders, ratios deterministic" test. |
| No stored per-account starting-capital column exists | Use `D` = Σ per-account earliest `trading_cycles.initial_equity` (fallback first-trade `base_capital`), ONE value per account — NOT `Σ base_capital` over trades. `D≤0`/null → % metrics show "—", no divide-by-zero. Labeled "recorded history". |
| % metrics (return, drawdown%, Sharpe) flip with Bybit availability | All use the DB denominator `D`, never live equity → deterministic regardless of exchange state; determinism test. |
| `trades`/cycle history predates account (untracked early P&L) | Cumulative-P&L curve and dollar KPIs always correct; only `total_return_pct`'s `D` reflects "recorded history", labeled. |
| Drawdown in dollars rendered under a `_pct` key | With `D`: true `%` via `equity_proxy`. Without `D`: populate `max_drawdown_abs`, leave `_pct` null — never dollars under `_pct`. |
| Curve overstates P&L because `realized_pnl` is gross | Use **`net_pnl`** (fee-netted) everywhere. |
| `net_pnl` NULL on legacy closed rows → TypeError | `COALESCE(net_pnl,0)` for sums; `net_pnl IS NOT NULL AND > 0` for wins; fixture covers it. |
| Partial-close child/parent rows double-count or drop P&L; copying old queries undercounts | Canonical filter includes children, excludes `partially_closed` + `exit_price=0`, and **omits `parent_trade_id IS NULL`**; a test guards against the copy-old-query trap. |
| Deposits/withdrawals untracked | Documented v1 limitation; cumulative-P&L curve + dollar KPIs immune (flows aren't in `net_pnl`); only the cosmetic live marker shows the gap, honestly. |
| `/performance/trades` keyset skips/dupes rows under NULL `net_pnl` or live inserts | `ORDER BY COALESCE(net_pnl,'-inf') DESC, id DESC` with the same expression in the cursor; mid-pagination-insert test. |
| Close-reason donut shows empty Trailing/Breakeven, drops liquidation/adl | Taxonomy uses real literals (TP/SL/Liquidation/ADL/External/Manual); §7 note. |
| Mixed settlement currencies sum into nonsense | v1 restricts scope to USDT-settled accounts, labels "USDT"; mixed out of scope. |
| Page looks sparse on a low-data account (Sharpe "—", thin deltas) | Default timeframe ALL; emphasize the absolute-equity secondary axis when live data is available (primary y-axis stays "Cumulative P&L"); collapse empty Risk group to one notice; lead KPI grid with populated metrics; hide (not dim) absent chips (§5.4). |
| Signals tab empty for users without scanner-linked trades (repeats original bug) | §4.4: coverage check, coverage-gated build (win-rate + empty card first), honest empty state, Phase-4 gating. |
| Win rate differs between Overview and Signals | Single definition `net_pnl > 0` across both. |
| Sharpe/Sortino/Calmar invalid/`0.0` on sparse days; Calmar unit mix | Daily **percentage** returns from `equity_proxy`; `null` (show "—" + hint) below 10 trading days. |
| `kpis_prev` undefined for ALL/YTD | `null` for ALL (chips hidden); YTD prior = equal day-count before Jan 1; thin prior window hides chip. |
| Live tab hangs/500s on a bad Bybit account | Per-account try/except + timeout + `degraded`; positions via per-account `get_positions`; historical tabs unaffected. |
| Live thundering-herd | Single `/performance/live`, server-throttled ~10s, polls only while visible, excluded from query persistence via `shouldDehydrateQuery`. |
| `compute_analytics`/`get_pnl_summary` reuse re-introduces snapshot/Bybit coupling | Do NOT use on the hot path; reimplement arithmetic over the canonical set; reuse only pure `portfolio_stats` funcs — ratios after daily-bucketing, `max_consecutive` over the per-trade sequence. |
| Charts/KpiCards are rewrites, not restyles; 4 tests break | Budgeted as rewrites (§5.1); existing tests migrated (§8). |
| `lib/format.ts` already exists → naive move clobbers it | **Merge** backtest formatters into existing `lib/format.ts`; update 7 importers; reconcile duplicate date formatter. |
| Portfolio-wide ordering has no covering index | Add partial index `idx_trades_closed_at WHERE status='closed'`. |
| Precision drift NUMERIC→float | Sum in `Decimal`, coerce at JSON boundary; reconciliation test uses tolerance. |
| Breaking the `AccountDetailView` embedding | Preserve `embedded`/`accountId` API; regression test. |
| `strategy_kind` legacy backfill mislabels trades as `'trend'` | Surface `strategy_legacy_approximate`; hint in Trades tab. |

---

## 10. File Change Summary

**New backend:**
- `backend/services/performance_service.py`
- `backend/routers/performance.py` (`APIRouter(prefix="/performance")`, mounted `prefix="/api/v1"`) — endpoints: `overview`, `trades-breakdown`, `trades` (paginated rows), `live`
- `Performance*` Pydantic models in `backend/schemas/__init__.py`
- Router mount in `backend/main.py`
- DB migration: partial index `idx_trades_closed_at (closed_at) WHERE status='closed'` (`async_persistence.py` `_MIGRATIONS`)
- Tests in `tests/backend/`

**New/changed frontend:**
- `frontend/src/components/analytics/PerformanceDashboard.tsx` (new top-level; avoids the existing `PerformancePage` symbol)
- `PerformanceControlBar.tsx`, `PerformanceHeroStrip.tsx` (new)
- `tabs/OverviewTab.tsx`, `tabs/TradesTab.tsx`, `tabs/SignalsTab.tsx`, `tabs/LiveTab.tsx` (new)
- `hooks/usePerformance.ts` (new; new scope-aware signal-analytics hooks + live/demo fan-out)
- **Rewrite (prop-interface change, not restyle):** `EquityCurveChart.tsx`, `DrawdownChart.tsx`, `DailyPnlChart.tsx`, `MonthlyPnlGrid.tsx`, `KpiCards.tsx`
- **Extend** `ui/AccountSelector.tsx` to a 4-way scope (add Live/Demo group options) OR add a new `ScopeSelector.tsx` (it is currently 2-way only)
- **Merge** `backtest/format.ts` into existing `frontend/src/lib/format.ts` (reconcile `formatDateTime` vs `formatDateTimeLabel`); update the 7 `backtest/format` importers
- `App.tsx`: **extend the existing** `dehydrateOptions.shouldDehydrateQuery` predicate (already present for the LLM-key case) to also exclude `performance-live` queries from persistence
- New client functions (`performanceApi`) + `Performance*` types in `frontend/src/api/client.ts`
- Route wiring in `frontend/src/routes/route-tree.tsx` (thin `PerformancePage` wrapper renders `PerformanceDashboard`)
- `AccountDetailView` embedding update (render `PerformanceDashboard accountId embedded`)
- Migrate 4 existing tests + new tests in `frontend/src/components/analytics/__tests__/`

**Retained:** `CleanupDialog.tsx` (de-emphasized). Old `AnalyticsDashboard.tsx` removed once embedding migrated.

---

## 11. Open Questions for Planning

*(Former baseline AND denominator questions RESOLVED in §3/§4.1: cumulative-P&L curve sliced by timeframe; starting-equity denominator `D` = Σ per-account earliest `trading_cycles.initial_equity` (fallback first-trade `base_capital`). Remaining questions are genuinely deferrable and do not block internal consistency.)*

1. Exact in-memory cache TTL/threshold if/when trade volume grows (current scale needs none — a TODO marker, not built).
2. Whether the Signals surface also gets its own sidebar nav entry, or lives only inside Performance.
3. Sector-concentration source for the Live tab: `sector_service` exposes no GET endpoint today — add a small read endpoint vs compute inline from open positions + `symbol_sectors` (this gates Phase 5 only).
4. Whether live/demo Signals scope is served by client-side fan-out (default) or a new multi-id param on `/signal-analytics/*`.
5. Edge case for `D`: an account whose first activity is a manual trade with NULL `base_capital` and no cycle → `D` is `null` for that account; it's excluded from scope `%`/ratios per the aggregate null-D rule (§3) and its single-account card shows "—". Confirm during planning whether to add a coarser fallback (e.g. earliest wallet value) or accept "—" for these accounts.

---

## 12. Phasing (de-risked delivery order)

The core fix (Overview) is independently shippable and not blocked by the exchange-dependent or data-conditional tabs. Each phase has its own TDD + review gate per project rules. **The Phase 1–2 cut-line is a hard gate: merge, confirm "the page now works" on the real DB, then plan 3–5.**

- **Phase 1 — Backend foundation:** `performance_service` (canonical filter incl. NULL-safety + no-`parent_trade_id` trap, cumulative-P&L curve, daily-bucketed % KPIs, exchange-independent core + best-effort live overlay), `/performance/overview`, schemas, index migration, full backend tests incl. the exchange-down test. No frontend.
- **Phase 2 — Overview UI + reliability (the user's primary ask):** `PerformanceDashboard`, control bar (single scope), hero strip (`kpis_prev` deltas, ALL/thin-window handling), TanStack Query hooks, chart/KpiCards rewrites + test migration, `lib/format.ts` merge, states/a11y/responsive, embedding preserved. **This alone makes the page work and look good.**
- **Phase 3 — Trades tab:** `/performance/trades-breakdown` + `/performance/trades` (paginated rows) + TradesTab (aggregates, sortable/paginated raw table, legacy-strategy hint). Pure trade data, no exchange/empty-table risk — recommended to ship with 1–2 as the "minimum that fully satisfies."
- **Phase 4 — Signals tab:** gated on the §4.4 coverage check; if coverage ~0, ship rolling win-rate + honest empty card only; scope-aware hooks + live/demo fan-out.
- **Phase 5 — Live tab:** resolve the sector-concentration source (§11 Q3) first; `/performance/live` (fail-soft per-account Bybit aggregation, throttled), LiveTab (positions, tiles, sector concentration, degraded banner). First cut candidate if scope must shrink — it duplicates the Positions page and adds the page's only exchange dependency.

If scope must be cut, Phases 1–2 are the minimum viable fix; 3–5 are additive.
