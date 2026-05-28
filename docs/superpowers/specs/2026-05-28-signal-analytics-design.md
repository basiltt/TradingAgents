# Signal Analytics & Performance Tracking System

## Overview

A signal performance tracking system that materializes trade outcomes against their originating scanner signals, enabling win-rate tracking, confidence calibration, benchmark comparison, regime-aware analysis, decay detection with alerts, and a fixed feedback loop based on actual trade durations.

**Approach:** Event-driven materialization. When a trade closes, a background task computes and stores its analytics record. A dedicated frontend page reads from materialized data.

**Throttling policy:** Alert-only. The system surfaces degradation metrics and fires alerts but does not automatically reduce position size or pause trading.

---

## Data Model

### Table: `signal_performance`

One row per closed trade that originated from a scanner signal.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | PK |
| `trade_id` | UUID | FK → trades (unique) |
| `account_id` | TEXT | For filtering |
| `symbol` | VARCHAR(30) | Traded asset |
| `direction` | VARCHAR(4) | buy/sell |
| `confidence_score` | INTEGER | Raw 1-10 from signal |
| `confidence_tier` | VARCHAR(10) | high/moderate/low |
| `signal_source` | VARCHAR(10) | trader/pm/hybrid |
| `regime_at_entry` | VARCHAR(15) | trending_up/trending_down/ranging/volatile |
| `regime_confidence` | NUMERIC(4,2) | LLM confirmation score 0-1 |
| `entry_price` | NUMERIC(20,8) | |
| `exit_price` | NUMERIC(20,8) | |
| `hold_duration_minutes` | INTEGER | Actual hold time |
| `realized_pnl_pct` | NUMERIC(12,4) | % return |
| `net_pnl` | NUMERIC(20,8) | After fees |
| `fees` | NUMERIC(20,8) | |
| `close_reason` | VARCHAR(20) | take_profit/stop_loss/timeout/manual/rule_triggered/liquidation/etc |
| `benchmark_bnh_pnl_pct` | NUMERIC(12,4) | Buy-and-hold return over same hold period |
| `benchmark_random_expected_pnl` | NUMERIC(12,4) | Expected return from random entry with same TP/SL/leverage |
| `is_win` | BOOLEAN | net_pnl > 0 |
| `opened_at` | TIMESTAMPTZ | |
| `closed_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | Default now() |

Indexes:
- `idx_sp_account_closed` on (account_id, closed_at DESC)
- `idx_sp_symbol_closed` on (symbol, closed_at DESC)
- `idx_sp_confidence` on (confidence_score)
- `idx_sp_regime` on (regime_at_entry)
- Unique constraint on `trade_id`

### Table: `regime_snapshots`

Periodic regime classification per symbol.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | SERIAL | PK |
| `symbol` | VARCHAR(30) | |
| `regime` | VARCHAR(15) | trending_up/trending_down/ranging/volatile |
| `adx` | NUMERIC(8,4) | Trend strength (0-100) |
| `atr_pct` | NUMERIC(8,4) | ATR as % of price |
| `bb_width_pct` | NUMERIC(8,4) | Bollinger Band width as % of price |
| `llm_confirmed` | BOOLEAN | Whether LLM agreed with indicator classification |
| `llm_regime` | VARCHAR(15) | LLM's classification (may differ from indicator-based) |
| `classified_at` | TIMESTAMPTZ | |

Indexes:
- `idx_rs_symbol_time` on (symbol, classified_at DESC)

### Table: `decay_alerts`

Fired when metrics breach thresholds.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | SERIAL | PK |
| `alert_type` | VARCHAR(30) | win_rate_drop/confidence_miscalibration/losing_streak/regime_mismatch/negative_alpha |
| `severity` | VARCHAR(10) | warning/critical |
| `message` | TEXT | Human-readable description |
| `metric_value` | NUMERIC(12,4) | Current metric value |
| `threshold` | NUMERIC(12,4) | What triggered it |
| `window_trades` | INTEGER | How many trades in the evaluation window |
| `acknowledged` | BOOLEAN | Default false |
| `created_at` | TIMESTAMPTZ | |

---

## Backend Services

### 1. Signal Performance Materializer

**File:** `backend/services/signal_performance_service.py`

**Trigger:** Called when a trade transitions to `closed` status (hook into existing trade status change flow in trade_service.py).

**Linkage prerequisite:** Add a `scan_result_id` INTEGER column (nullable) to the `trades` table. When auto_trade_service executes a signal, store the `scan_results.id` from the result dict on the trade record. This provides a direct FK from trade → scan_result without fragile ticker+time matching.

**Logic:**
1. Check trade has a non-null `scan_result_id` (only scanner-originated trades get tracked)
2. Fetch the scan_result row directly via `scan_result_id` to get confidence_score, signal_source, direction
3. Look up regime_snapshots for the symbol closest to trade.opened_at
4. Compute benchmark_bnh_pnl_pct: fetch Bybit kline for the asset at opened_at and closed_at, calculate (close_price - open_price) / open_price * 100
5. Compute benchmark_random_expected_pnl: `(tp_distance / (tp_distance + sl_distance)) * tp_pct - (sl_distance / (tp_distance + sl_distance)) * sl_pct` — the geometric expected value of a random entry with same TP/SL distances
6. Write signal_performance row
7. Trigger decay detection check

**Edge cases:**
- Trade has no matching scan_result (manual trade tagged as scanner): skip, log warning
- Regime snapshot doesn't exist for the symbol at entry time: store regime_at_entry = NULL
- Trade closed without exit_price (cancelled/failed): skip

### 2. Regime Classifier

**File:** `backend/services/regime_classifier.py`

**Schedule:** Every 15 minutes via existing scheduler infrastructure.

**Symbols:** All symbols with active scheduled scans or open positions.

**Indicator calculation:**
- Fetch 4h klines (last 50 candles) from Bybit
- ADX(14): measures trend strength
- ATR(14) as % of current price: measures volatility
- Bollinger Band width (20, 2σ) as % of middle band: measures compression/expansion

**Classification rules:**
- `trending_up`: ADX > 25 AND price > EMA(20)
- `trending_down`: ADX > 25 AND price < EMA(20)
- `ranging`: ADX < 20 AND BB width < 30-period median BB width
- `volatile`: ATR% > 1.5x its own 30-period moving average

Priority: volatile > trending > ranging (if multiple conditions match, highest priority wins).

**LLM confirmation:**
- Lightweight call with indicator values + last 12 candles OHLC summary
- Prompt: "Given these indicators [ADX, ATR%, BB width, price vs EMA] and recent price action, classify this market as trending_up/trending_down/ranging/volatile. Respond with your classification and a confidence score 0-1."
- Store both indicator-based and LLM classifications
- Final regime = LLM classification if confidence > 0.7, else indicator-based

**Rate management:** Use existing BybitRateLimiter. LLM calls use configured model from app settings.

### 3. Decay Detector

**File:** `backend/services/decay_detector.py`

**Trigger:** Called after each signal_performance row is written.

**Alert conditions (rolling windows):**

| Alert Type | Window | Condition | Severity |
|------------|--------|-----------|----------|
| `win_rate_drop` | Last 20 trades | win_rate < 40% | warning |
| `win_rate_drop` | Last 20 trades | win_rate < 30% | critical |
| `losing_streak` | Recent consecutive | 5+ consecutive losses | warning |
| `losing_streak` | Recent consecutive | 8+ consecutive losses | critical |
| `confidence_miscalibration` | Last 30 high-confidence (7-10) trades | win_rate < 50% | warning |
| `regime_mismatch` | Last 15 trades in current regime | win_rate < 35% | warning |
| `negative_alpha` | Last 30 trades | cumulative PnL < cumulative benchmark_bnh | warning |

**Deduplication:** Don't fire the same alert_type + severity if an unacknowledged alert of the same type already exists.

### 4. Signal Analytics Query Service

**File:** `backend/services/signal_analytics_service.py`

Provides aggregated data for the frontend:

- `get_summary(account_id?, date_range)` → overall KPIs
- `get_rolling_win_rate(account_id?, window=20)` → time series of rolling win rate
- `get_calibration_curve(account_id?)` → confidence buckets vs actual win rate
- `get_benchmark_comparison(account_id?, date_range)` → cumulative PnL series for system vs benchmarks
- `get_regime_breakdown(account_id?)` → win rate and avg PnL per regime
- `get_current_regimes()` → latest regime per active symbol
- `get_decay_alerts(acknowledged=False)` → active alerts
- `get_performance_trades(filters, pagination)` → paginated signal_performance rows

All queries hit `signal_performance` table directly — no live computation except for the summary stats.

---

## API Endpoints

**Router:** `backend/routers/signal_analytics.py`

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/signal-analytics/summary` | KPIs: total trades, win rate, avg PnL%, Sharpe, current streak, active alert count |
| `GET` | `/signal-analytics/win-rate` | Rolling 20-trade win rate time series, optionally grouped by confidence tier |
| `GET` | `/signal-analytics/calibration` | Confidence score buckets (1-3, 4-6, 7-10) with actual win rate per bucket |
| `GET` | `/signal-analytics/benchmarks` | Cumulative PnL vs buy-and-hold vs random — time series arrays |
| `GET` | `/signal-analytics/regime` | Win rate + avg PnL grouped by regime_at_entry |
| `GET` | `/signal-analytics/regime/current` | Latest regime_snapshot per actively traded symbol |
| `GET` | `/signal-analytics/decay-alerts` | Active unacknowledged alerts |
| `POST` | `/signal-analytics/decay-alerts/{id}/acknowledge` | Mark alert as dismissed |
| `GET` | `/signal-analytics/trades` | Paginated signal_performance rows with filters (symbol, confidence_tier, regime, date_range, is_win) |

Query parameters shared across endpoints:
- `account_id` (optional): filter to specific account
- `start_date`, `end_date` (optional): date range, default last 90 days

---

## Frontend

**New route:** `/signal-analytics` with dedicated nav entry.

**Page layout (top to bottom):**

1. **Alert Banner** — Dismissible warning/critical bar if active decay_alerts exist. Shows severity color + message + acknowledge button.

2. **KPI Cards Row** — Total Signals Traded | Win Rate % | Avg PnL% | Alpha vs Buy-and-Hold | Current Streak (W/L) | Sharpe Ratio

3. **Calibration Chart** — Bar chart with confidence buckets (Low 1-3, Moderate 4-6, High 7-10) on x-axis, actual win rate on y-axis. Diagonal reference line shows "perfect calibration" (where confidence matches outcome probability).

4. **Rolling Win Rate Chart** — Line chart showing 20-trade rolling win rate over time. Horizontal reference line at 50%. Optional toggle to split by confidence tier.

5. **Benchmark Comparison Chart** — Multi-line chart: your cumulative PnL (blue), buy-and-hold (gray dashed), random expected (red dashed). All start at 0. X-axis is trade number or date.

6. **Regime Breakdown** — Grouped bar chart: regimes on x-axis, win rate + avg PnL% as paired bars. Color-coded by regime type.

7. **Trade Table** — Sortable, filterable table of signal_performance records. Columns: Date, Symbol, Direction, Confidence, Regime, PnL%, Hold Duration, Close Reason, vs B&H. Pagination.

**Charting:** Recharts (already in project). Follows existing AnalyticsDashboard patterns.

---

## Feedback Loop Fix

### What changes

The existing `memory_log` / `Reflector` system (5-day forward returns, prose reflections) is **deprecated for crypto perpetuals**. It remains available for stock analysis.

### New feedback injection

When the trading graph runs for a crypto symbol, `create_initial_state()` injects real trade outcome data from `signal_performance`:

**Injection point 1 — Trader Agent (Pass 1, directional decision):**

```
Recent signal performance for {symbol}:
- {time_ago}: {DIRECTION}, confidence {score}, regime={regime} → {WIN/LOSS} {pnl_pct}% (held {duration}min, closed: {reason})
- ... (last 5 trades for this symbol)

Rolling stats for {symbol}: {wins}/{total} wins ({win_rate}%), avg hold {avg_hold}min
Best regime: {regime} ({win_rate}%), Worst regime: {regime} ({win_rate}%)
Overall system win rate (all symbols): {overall_win_rate}% over last {n} trades
```

**Injection point 2 — Risk Manager:**

Same data, framed for risk: "Recent performance in current regime ({current_regime}) for this symbol: {X}/{Y} wins. System-wide: {overall}% win rate. Consider this track record when assessing position risk."

### Regime injection into analysts

When scanner analysis runs, before analyst agents execute:

```
Current market regime for {symbol}: {regime}
Indicators: ADX={adx} (trend strength), ATR%={atr_pct} (volatility), BB Width={bb_width}%
LLM confirmed: {yes/no} (LLM classified as: {llm_regime})

Adjust analysis: trend-following signals carry more weight in trending regimes, mean-reversion signals in ranging regimes. In volatile regimes, widen expected ranges and lower confidence unless conviction is very high.
```

Injected into the state dict consumed by all analyst nodes via `create_initial_state()`.

---

## Integration Points

1. **Trade close hook:** In `trade_service.py` where trade status transitions to 'closed', call `signal_performance_service.materialize(trade)` asynchronously (fire-and-forget, non-blocking to close flow).

2. **Scheduler:** Add regime_classifier to existing `SnapshotScheduler` with 15-minute interval.

3. **Trading graph:** Modify `trading_graph.py` `create_initial_state()` to query `signal_performance` for the symbol and inject formatted context.

4. **WebSocket:** Broadcast new decay_alerts via existing account WebSocket channel so frontend can show real-time alert banners without polling.

5. **Migration:** New migration file adds the 3 tables with indexes.

---

## What This Does NOT Do

- No automated throttling or position size reduction
- No backtesting framework (future work)
- No signal replay / paper-trade simulation
- No cross-symbol correlation analysis (future work)
- No Kelly criterion sizing (future work)
- Does not modify existing trade execution flow — purely observational + context injection
