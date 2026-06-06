# Backtesting System — Technical Specification

## Document Info
- **Feature:** Comprehensive Backtesting System
- **Version:** 1.0
- **Status:** Draft
- **Author:** Claude (AI-assisted development)
- **Date:** 2026-06-05
- **Dependencies:** Requirements doc (305 reqs), Architecture doc

---

## 1. Executive Summary

Build a backtesting subsystem that replays historical scheduled market scan results through the full auto-trade cycle (signal filtering → position opening → close rule evaluation → position closure) using cached kline data. The system produces TradingView-quality metrics and visualizations with <1% deviation from real trading results.

**Non-goals (Phase 1):** Parameter optimization (grid search, Bayesian, Monte Carlo), AI Manager simulation, multi-user isolation.

---

## 2. Functional Requirements

### FR-001: Backtest Configuration

The user configures a backtest with these parameters:

**Backtest-Specific Fields:**
| Field | Type | Default | Validation |
|-------|------|---------|------------|
| starting_capital | Decimal | Required | > 0, <= 100,000,000 |
| date_range_start | datetime | Required | Not in future |
| date_range_end | datetime | Required | After start, max 365 days span |
| scan_source | ScanSource | Required | Valid mode + IDs |
| simulation_interval | Literal | "5m" | One of: 5m, 15m, 1h, 4h |
| fee_rate_pct | Decimal | 0.055 | >= 0, <= 1.0 |
| slippage_bps | int | 2 | >= 0, <= 50 |
| funding_rate_model | Literal | "none" | "none" or "fixed_8h" |
| funding_rate_fixed_pct | Decimal | 0.01 | >= -0.5, <= 0.5 |

**AutoTradeConfig Fields (all trade-decision params):**
| Field | Type | Default | Validation |
|-------|------|---------|------------|
| direction | Literal | "straight" | "straight" or "reverse" |
| leverage | int | 20 | 1-125 |
| capital_pct | float | 5.0 | 0.1-100 |
| take_profit_pct | float | 150.0 | 0.1-1000 |
| stop_loss_pct | float | 100.0 | 0.1-1000 |
| min_score | float | 0.0 | -10 to 10 |
| confidence_filter | Literal | "any" | any/high/moderate/low |
| signal_sides | Literal | "both" | both/buy/sell |
| max_trades | int | 999 | 1-999 |
| execution_mode | Literal | "batch" | immediate/batch |
| fill_to_max_trades | bool | False | |
| skip_if_positions_open | bool | False | |
| max_same_direction | int? | None | 1-100 if set |
| max_same_sector | int? | None | 1-50 if set |
| symbol_blacklist | list[str]? | None | |
| symbol_whitelist | list[str]? | None | |
| max_drawdown_pct | float | 100.0 | 0.1-100 |
| smart_drawdown_close | bool | False | |
| breakeven_timeout_hours | float? | None | 0.1-720 if set |
| max_trade_duration_hours | float? | None | 0.1-720 if set |
| trailing_profit_pct | float? | None | 0.1-50 if set |
| close_on_profit_pct | float? | None | 0.1-100 if set |
| adaptive_blacklist_enabled | bool | False | |
| adaptive_blacklist_min_trades | int | 5 | 1-100 |
| adaptive_blacklist_max_win_rate | float | 30.0 | 0-100 |
| adaptive_blacklist_lookback_hours | int | 48 | 1-720 |
| max_price_drift_pct | float? | None | 0.1-50 if set |

### FR-002: Scan Source Selection

Three modes for selecting which historical signals to replay:

1. **By Schedule** (default): `{mode: "schedule", schedule_id: "uuid", date_range: {start, end}}`
   - Loads all scans triggered by the specified scheduled scanner within the date range
2. **By Date Range**: `{mode: "date_range", date_range: {start, end}}`
   - Loads ALL scans within the date range regardless of source
3. **By Explicit IDs**: `{mode: "explicit", scan_ids: ["uuid1", "uuid2", ...]}` (max 500 IDs, UUID format validated)
   - Loads only the specified scan runs

### FR-003: Simulation Engine

The engine processes scan results chronologically, applying the full auto-trade filter chain and close rules:

**Interface:** `BacktestEngine.run(config, signals, klines, cancel_event=None, on_progress=None, instrument_info=None) -> SimulationResult`
- `cancel_event`: `threading.Event` checked every 100 candles. Raises `BacktestCancelled` if set. This is the single impurity allowed in the otherwise pure engine.
- `on_progress`: `Callable[[int], None]` for % updates (0-100).
- `instrument_info`: optional `{symbol: {qty_step, min_qty, tick_size, max_leverage}}` resolved by the service from the Bybit instrument cache; used to round qty to the real lot step, reject below min qty, round TP/SL to the tick, and cap leverage. Absent → no-op defaults (see Known Modeling Approximations §6).

**Input:** Config + list of scan signals (chronological) + kline DataFrames per symbol
**Output:** List of simulated trades + equity curve + raw metrics

**Core loop** (see Architecture §4.3 for full evaluation order):
1. Iterate candles in chronological order
2. At each candle: evaluate funding → liquidation → TP/SL → equity rules → trailing → time rules
3. At scan timestamps: if cycle not active, apply filter chain → open positions
4. Track equity at each step

**Exit price rules:**
- Slippage is **round-trip**: `slippage_bps` is applied adversely on the exit FILL as well
  as the entry fill, because production closes positions via Bybit market reduce-only orders
  that fill worse than the trigger/close price. The close side is the inverse of the position
  side (a long sells to close → fills lower; a short buys to close → fills higher).
- TP hit: trigger at tp_price (anchored to the un-slipped mark), exit fills at
  `tp_price × (1 ∓ slippage_bps/10000)` (taker fee 0.055%)
- SL hit: trigger at sl_price (anchored to the un-slipped mark), exit fills at
  `sl_price × (1 ∓ slippage_bps/10000)` (taker fee 0.055%)
- Liquidation: realized_pnl = -(initial_margin + entry_fee). User loses FULL margin on liquidation (Bybit isolated). No exit slippage (forced full-margin loss, not a market fill).
- ALL other closes (TRAILING, MAX_DURATION, EQUITY_RISE/DROP, close_on_profit_pct): trigger at
  candle.close, exit fills at `candle.close × (1 ∓ slippage_bps/10000)` (taker fee 0.055%)

**Equity reference for EQUITY_RISE/DROP/SMART rules:**
- `ref` = cycle_start_equity, re-anchored EVERY (non-skipped) scan to the AVAILABLE
  balance = `wallet_balance + Σ(unrealised_pnl of open positions) − Σ(locked_margin)`.
  This mirrors production's `totalAvailableBalance = totalWalletBalance + totalPerpUPL
  − totalInitialMargin`, which production reads each scan and uses as the
  EQUITY_DROP/RISE `reference_value` AND as the new-position sizing basis (so the
  backtest derives both from this one value too). The carried unrealised PnL is marked
  to the candle at/just-before the scan timestamp (no look-ahead). The evaluated equity
  is `wallet_balance + Σ(unrealized_pnl)` (≈ production `totalEquity`). On an empty book
  (no carried positions) uPnL=0 and locked=0 → the reference reduces to the full wallet.
  The skip_if_positions_open=True path (open book) preserves the prior anchor, matching
  production's only no-recreate case.
- For EQUITY_DROP_PCT_SMART: ref resets to current equity immediately after closing losing positions

**Price drift check:**
- If `max_price_drift_pct` is set: `drift = (candle.close - signal.analysis_price) / signal.analysis_price × 100`
  (SIGNED, direction-aware — matches production). Reject only when the price has already
  moved too far IN the signal's direction (the move is "consumed"/chasing):
  - buy/long signal → skip if `drift > max_price_drift_pct`
  - sell/short signal → skip if `drift < -max_price_drift_pct`
- A favorable adverse move (e.g. a buy whose price has dropped below analysis) is ADMITTED —
  it is a better entry, exactly as production trades it.

**Kline cache concurrency:**
- All inserts use `ON CONFLICT (symbol, interval, open_time) DO NOTHING`
- Coverage table uses `ON CONFLICT DO UPDATE SET candle_count = EXCLUDED.candle_count`

**Execution model:**
- Engine is synchronous (all data pre-loaded as numpy arrays / lists)
- Runs via `loop.run_in_executor(thread_pool, engine.run, ...)` using a bounded `ThreadPoolExecutor(max_workers=3)`
- `on_progress` callback is thread-safe (posts to asyncio Queue consumed by service layer)
- Concurrency gate: `asyncio.Semaphore(3)` in BacktestService. 4th request gets 503 immediately.
- Single-worker uvicorn deployment (in-process semaphore sufficient)
- 429 = per-user rate limit (max 10 creates/hour). 503 = global capacity full (3 slots taken).
- **Timeout enforcement:** `threading.Timer(120, cancel_event.set)` started before executor call. Engine raises `BacktestTimeout` (distinct from `BacktestCancelled`). Status → `failed` with `error_message='Execution timeout (120s)'`.
- **Memory budget:** Pre-compute max candle count (`date_range_days × 288` for 5m). Reject configs with >105,120 candles (365d). Equity curve pre-allocated as fixed-size array. Open positions capped at `max_trades`.

**Startup recovery:**
- On app startup: `UPDATE backtest_runs SET status='failed', error_message='Server restarted' WHERE status IN ('running', 'pending')`

**Intra-candle wallet_balance update ordering:**
- After each close event (TP/SL/liquidation) within a single candle, wallet_balance is IMMEDIATELY updated with realized PnL before evaluating the next tier (equity rules)
- This means: Position A hits SL → wallet_balance reduced → equity rules see reduced equity → may cascade into closing Position B

### FR-004: Close Rules (Complete Specification)

| Rule | Trigger Condition | Action | Evaluation Frequency |
|------|-------------------|--------|---------------------|
| TP (long) | candle.high >= tp_price | Close at tp_price | Every candle |
| TP (short) | candle.low <= tp_price | Close at tp_price | Every candle |
| SL (long) | candle.low <= sl_price | Close at sl_price | Every candle |
| SL (short) | candle.high >= sl_price | Close at sl_price | Every candle |
| EQUITY_RISE_PCT | (equity - ref) / ref × 100 >= threshold | Close ALL positions | Every candle |
| EQUITY_DROP_PCT | (ref - equity) / ref × 100 >= threshold | Close ALL positions | Every candle |
| EQUITY_DROP_PCT_SMART | Same as above | Close only LOSING positions; reset reference | Every candle |
| BREAKEVEN_TIMEOUT | elapsed >= timeout_hours | Modify TP to: Buy=entry×(1+1/(lev×100)), Sell=entry×(1-1/(lev×100)) | Every candle |
| MAX_DURATION | elapsed >= max_hours | Close position | Every candle |
| TRAILING_PROFIT | per_unit_pnl < peak × 0.5 (after price_move% >= trailing_profit_pct) | Close position | Every candle |
| LIQUIDATION | candle extreme breaches liq_price | Close at liq_price | Every candle (wicks) |
| close_on_profit_pct | cycle PnL >= threshold | Close ALL cycle positions | Every candle |

**TP/SL Ambiguity (both hit same candle):** Pessimistic — assume SL hit first.

**Cycle lock:** No new trades while ANY position from current cycle is open.

### FR-005: Trade Execution Formulas

```
# Side determination
side = "Buy" if (signal=="buy" AND direction=="straight") OR (signal=="sell" AND direction=="reverse")
side = "Sell" otherwise
direction_sign = +1 if side == "Buy" else -1

# Position sizing (uses DYNAMIC sizing_capital — refreshed to wallet_balance at each cycle start, matching production)
sizing_capital = wallet_balance  # refreshed at cycle start (= starting_capital + Σ realized_pnl - Σ fees)
intended_margin = sizing_capital × capital_pct / 100
available_balance = wallet_balance - Σ(locked_margin_i)  # for sufficiency check only
# locked_margin_i = (qty_i × entry_price_i) / leverage_i  (= the margin allocated at open)
if intended_margin > available_balance: SKIP trade (insufficient margin)
# qty is sized off the UN-SLIPPED mark price (candle.close), matching production
# (qty = usdt_amount × leverage / mark_price) — NOT the slipped fill.
mark_price = candle.close
qty = (intended_margin × leverage) / mark_price
qty = floor(qty / qty_step) × qty_step  # Round to instrument precision
if qty < min_qty: SKIP trade

# Entry FILL price (no look-ahead) — the order fills at the slipped price (production
# fills a market order at avgPrice). This slipped fill is used for PnL, entry fee,
# locked margin, and the liquidation anchor.
entry_price = mark_price × (1 + slippage_bps/10000) for Buy
entry_price = mark_price × (1 - slippage_bps/10000) for Sell

# TP/SL TRIGGERS — anchored to the UN-SLIPPED mark, matching production
# (tp = mark_price × (1 ± tp_pct/leverage/100)). The exit then fills with adverse
# slippage (see Exit price rules above).
tp_price = mark_price × (1 + tp_pct / leverage / 100) for Buy
tp_price = mark_price × (1 - tp_pct / leverage / 100) for Sell
sl_price = mark_price × (1 - sl_pct / leverage / 100) for Buy
sl_price = mark_price × (1 + sl_pct / leverage / 100) for Sell

# Liquidation price (isolated margin, tier 1 MMR=0.5%) — anchored to the SLIPPED entry
# fill (Bybit liquidates off the average fill price / avgPrice).
liq_price = entry × (1 - (1/leverage - 0.005)) for Buy
liq_price = entry × (1 + (1/leverage - 0.005)) for Sell

# Priority: If SL closer to entry than liquidation, SL triggers first
# For Buy: if sl_price > liq_price, SL wins on same candle
# For Sell: if sl_price < liq_price, SL wins on same candle

# Unrealized PnL
upnl = (current_price - entry) × qty for Buy  (direction_sign = +1)
upnl = (entry - current_price) × qty for Sell  (direction_sign = -1)

# Equity
equity = wallet_balance + Σ(upnl_i for all open positions)

# Fees (ALL exits use taker fee — Bybit defaults tpOrderType=Market)
entry_fee = qty × entry_price × fee_rate_pct / 100  (taker on entry)
exit_fee = qty × exit_price × fee_rate_pct / 100    (taker on ALL exits: TP, SL, market close)

# Realized PnL (on close)
realized_pnl = (exit_price - entry_price) × qty × direction_sign - entry_fee - exit_fee

# Funding (at 00:00, 08:00, 16:00 UTC boundaries)
funding_payment = qty × candle.close × funding_rate_fixed_pct / 100  # use current price, not entry
# Positive rate: long pays (deduct from wallet), short receives (add to wallet)
# Negative rate: short pays, long receives

# Trailing Profit Activation (PRICE movement %, NOT leverage-adjusted ROI%)
# CRITICAL GUARD: Only trail PROFITABLE positions. If upnl <= 0: clear peak, skip.
if upnl <= 0: clear_peak(position); skip trailing evaluation entirely
activation_condition = abs(current_price - entry_price) / entry_price × 100 >= trailing_profit_pct
# After activation: track peak per_unit_pnl = upnl / qty
# Close when: per_unit_pnl < peak × 0.5
# If upnl drops to 0 after activation: clear peak, deactivate trailing (re-activation needed)

# close_on_profit_pct
cycle_pnl_pct = ((equity - cycle_start_equity) / cycle_start_equity) × 100
# Trigger when cycle_pnl_pct >= close_on_profit_pct → close ALL cycle positions

# Instrument info
# qty_step, min_qty, tick_size, max_leverage from cached instrument_info
# Source: Bybit GET /v5/market/instruments-info (cached alongside klines)
```

### FR-006: Metrics Computation

**TradingView-Parity Metrics:**

| Category | Metrics |
|----------|---------|
| Profitability | Net profit ($/%), gross profit, gross loss, profit factor, recovery factor, CAGR |
| Risk | Max drawdown ($/%), avg drawdown %, max drawdown duration, Sharpe, Sortino, Calmar |
| Trades | Total, winners, losers, win rate, avg trade, avg win, avg loss, largest win/loss |
| Duration | Avg duration, avg winner duration, avg loser duration, max duration |
| Streaks | Max consecutive wins/losses (count and $) |
| Per-Trade | MFE, MAE, cumulative PnL, close reason |
| Comparison | Buy & Hold return (BTC/USDT), excess return, total commission paid |
| Split | All metrics split into All/Long/Short columns |

**Metric Formulas:**
- **Sharpe:** `mean(daily_returns) / std(daily_returns) × √365` (risk-free = 0, annualized for crypto 24/7)
- **Sortino:** `mean(daily_returns) / downside_deviation × √365` (only negative returns in denominator)
- **Calmar:** `CAGR / max_drawdown_%`
- **CAGR:** `(final_equity / initial_capital)^(365/backtest_days) - 1`
- **Recovery Factor:** `net_profit_$ / max_drawdown_$`
- **Profit Factor:** `gross_profit / abs(gross_loss)`
- **Expectancy:** `(win_rate × avg_win_$) - (loss_rate × avg_loss_$)`
- **Buy & Hold:** `(btc_price_end - btc_price_start) / btc_price_start × 100%`

**Edge Cases:**
- Zero trades: Return `status=completed` with `warnings=['no_trades_matched']`. All ratios = null. Equity = flat line.
- One trade: Sharpe/Sortino = null (insufficient data). Other metrics computed normally.
- All wins or all losses: Profit factor = null (no losses → "∞"/"N/A" in UI) or 0. Sortino = null when there are no downside periods (downside deviation undefined → "∞"/"N/A"), consistent with the profit-factor convention. *(Revised during Phase 4 review: returning null is JSONB-safe and avoids emitting a meaningless giant ratio from an arbitrary 0.0001 floor.)*

### FR-007: Kline Cache

- Store as DOUBLE PRECISION in PostgreSQL (native float return)
- Partition by month (RANGE on open_time)
- Coverage tracking table for O(1) gap detection
- Fetch from Bybit public API on cache miss (15 concurrent, 200/page)
- Only cache symbols that appear in scan results for the backtest
- Retention: 180 days (drop old partitions monthly)

### FR-008: Results Dashboard

- **Overview tab:** 4 hero metrics (Net Profit, Win Rate, Max Drawdown, Sharpe) sticky header + full metrics grid
- **Equity Curve tab:** Interactive area chart + drawdown overlay + Buy & Hold line
- **Trade List tab:** Sortable/filterable table with entry/exit/PnL/duration/close-rule
- **Analysis tab:** Monthly heatmap + P&L distribution + duration distribution
- **Comparison tab:** Side-by-side 2-4 runs with metric diff + overlaid equity curves

### FR-009: Frontend UX States & Interactions

**UX States per page:**
| State | /backtest (list) | /backtest/new (config) | /backtest/$id (results) |
|-------|-----------------|----------------------|------------------------|
| Empty | "No backtests yet" + CTA to create | N/A | N/A |
| Loading | Skeleton table rows | N/A | Progress bar + live % from progress_pct |
| Running | Row shows spinner + progress_pct | N/A | Progress bar + Cancel button |
| Completed | Row shows metric badges | N/A | Full results dashboard |
| Failed | Row shows error badge | N/A | Error card + message + "Retry" button |
| Cancelled | Row shows cancelled badge | N/A | Partial results (if any) + "Re-run" |

**Polling pattern:**
- TanStack Query with `refetchInterval: 2000` while `status === "running"`
- Transitions to `refetchInterval: false` once `status !== "running"`
- On completion: toast notification if user navigated away

**Cancel flow:**
1. User clicks Cancel → confirmation dialog ("Cancel this backtest?")
2. POST /cancel → button shows "Cancelling..." (disabled)
3. Next poll returns `status: "cancelled"` → show cancelled state

**Config form structure:**
- **Quick mode (default):** starting_capital + date_range + scan_source + leverage + TP/SL (7 fields)
- **Advanced toggle:** reveals 4 collapsible sections (Signal Filtering, Trade Sizing, Close Rules, Adaptive Blacklist)
- **Close Rules section:** Each rule has enable toggle → reveals threshold input when enabled
- **Presets:** localStorage-based save/load for Phase 1

**Navigation guards:**
- `useBlocker` on dirty form state (unsaved config changes)
- `beforeunload` handler while form has changes

**Comparison selection flow:**
- List view: checkbox column on each row (disabled after 4 selected)
- "Compare Selected" button enabled when 2-4 rows checked
- Navigates to `/backtest/compare?ids=uuid1,uuid2,...`
- Comparison page: overlaid equity curves (color-coded) + metric diff table (green/red deltas)
- Each run result page: "Add to comparison" secondary action (sessionStorage basket, max 4)

---

## 3. Non-Functional Requirements

| NFR | Requirement | Target |
|-----|-------------|--------|
| NFR-001 | Single 30-day backtest (warm cache) | <3 seconds |
| NFR-002 | Single 30-day backtest (cold cache) | <60 seconds |
| NFR-003 | PnL deviation from real trading | <1% |
| NFR-004 | Concurrent backtests | Max 3 simultaneous |
| NFR-005 | Memory per backtest | <256 MB |
| NFR-006 | Execution timeout | 120 seconds |
| NFR-007 | API response (cached results) | <100 ms |
| NFR-008 | Date range limit | 365 days max |
| NFR-009 | Equity curve API points | Max 1000 (LTTB downsampled) |
| NFR-010 | Kline cache retention | 180 days |

---

## 4. API Contract

### POST /api/v1/backtests
- **Request:** BacktestCreateRequest (see FR-001)
- **Response:** `{id: uuid, status: "pending", created_at: datetime}`
- **Status codes:** 201 (created), 422 (validation), 429 (rate limit), 503 (queue full)

### GET /api/v1/backtests/{id}
- **Response:** Full run + results (if complete): `{id, status, progress_pct, config, results?, warnings[]}`
- **Status codes:** 200, 404

### GET /api/v1/backtests
- **Query params:** `status`, `sort_by: Literal["created_at","net_profit","win_rate","max_drawdown","sharpe"]`, `page`, `limit`
- **Response:** `{backtests: [{id, status, config_summary, metrics_summary, created_at}], total}`
- **Validation:** `sort_by` must be from allowlist (prevents SQL injection via ORDER BY). Default: `created_at`.

### GET /api/v1/backtests/{id}/trades
- **Query params:** `page=1`, `limit=50`, `sort_by: Literal["entry_time","pnl","duration"]`, `side: Literal["Buy","Sell"]?`, `close_reason?`
- **Response:** `{trades: [BacktestTrade], total, page}`
- **Purpose:** Paginated trade list for the Trade List tab. Separated from main result to keep GET /{id} fast.

### POST /api/v1/backtests/{id}/cancel
- **Response:** `{status: "cancelled"}`
- **Status codes:** 200, 404, 409 (already completed)

### DELETE /api/v1/backtests/{id}
- **Response:** 204 No Content
- **Status codes:** 204 (deleted), 404, 409 (cannot delete running backtest)
- **Behavior:** Cascades to backtest_results and backtest_trades

### GET /api/v1/backtests/compare?ids=uuid1,uuid2
- **Validation:** 2-4 run IDs required. All must be `completed` status. 422 if <2 or >4, 404 if any missing.
- **Response:** `{runs: [{id, config, metrics, equity_curve_downsampled}]}`

### POST /api/v1/backtests/warmup-cache
- **Request:** `{symbols: [str], interval: str, date_range: {start, end}}`
- **Validation:** max 200 symbols, each matching `^[A-Z0-9]{2,20}$`
- **Response:** `{task_id: str, estimated_seconds: int}`

### GET /api/v1/backtests/cache-status
- **Response:** `{total_symbols: int, cached_symbols: int, coverage_pct: float, size_mb: float}`

---

## 5. Database Schema

See Architecture §3.1 for complete DDL. Tables:
- `kline_cache` (partitioned, DOUBLE PRECISION)
- `kline_cache_coverage` (gap detection)
- `backtest_runs` (lifecycle)
- `backtest_results` (metrics + equity JSONB)
- `backtest_trades` (normalized, indexed)

---

## 6. Phasing

### Phase 1 (MVP)
- Core simulation engine with all close rules
- Kline cache service (fetch + store + gap detection)
- REST API (CRUD + cancel + compare)
- Frontend: config form + results dashboard (equity curve, metrics, trade list)
- Shared `trading_rules.py` module
- Tests: unit (engine) + integration (full pipeline)

### Phase 2
- Parameter optimization (grid search, sensitivity analysis)
- Historical funding rate fetching
- 1-minute kline resolution option
- Walk-forward analysis
- Monte Carlo confidence intervals
- Advanced comparison features

---

## 7. Acceptance Criteria

| AC | Criteria | Verification |
|----|----------|-------------|
| AC-001 | Backtest completes in <3s (warm cache, 30 days) | Performance benchmark |
| AC-002 | All 10 close rules produce correct results (TP, SL, EQUITY_RISE, EQUITY_DROP, SMART, BREAKEVEN, MAX_DURATION, TRAILING, LIQUIDATION, close_on_profit_pct) | Golden-set tests |
| AC-003 | Filter chain matches AutoTradeExecutor exactly | Shared module + unit tests |
| AC-004 | Per-trade PnL deviation <1% AND total portfolio PnL deviation <0.5% (validated on ≥20 historical trades). For breakeven trades (|real_pnl| < $0.01): use absolute diff |sim-real| < $0.10 | Deviation test: max(|sim_pnl_i - real_pnl_i| / max(|real_pnl_i|, 0.01)) for each trade |
| AC-005 | Equity curve renders correctly with 30+ days data | E2E test + visual |
| AC-006 | Config form includes all AutoTradeConfig params | UI test |
| AC-007 | Multiple consecutive scans respected with cycle lock | Integration test |
| AC-008 | Kline cache survives across runs (no re-download) | Regression test |
| AC-009 | Cancel button stops running backtest within 200 candles | Threading.Event + unit test |
| AC-010 | Comparison view shows overlaid equity curves | E2E test |

---

## Known Modeling Approximations

These are intentional, documented deltas from live trading — surfaced here (and, where
user-visible, via result warnings or field labels) so results are not silently misread.
None individually exceeds the <1% deviation budget for typical configs.

1. **Sharpe / Sortino annualization.** Returns are resampled to daily and annualized by
   √365. TradingView's Strategy Tester reports a non-annualized, per-period Sharpe, so the
   backtest's Sharpe is several× larger than TV shows for the same run — the *ranking* is
   consistent, but do not expect bit-for-bit TV parity on the absolute number. On gap-heavy
   or sub-day windows the daily resampling is approximate.

2. **`max_signal_age_minutes` is a near-no-op in replay.** Production measures age as
   `now − completed_at` (real execution latency); the backtest executes at the scan
   timestamp, so age ≈ 0 and the filter rarely rejects. The per-ticker `completed_at` is not
   stored in `scan_results`, so a faithful per-signal age cannot be reconstructed. A config
   relying on a tight age filter will admit more signals in backtest than in production.

3. **`max_same_sector` is not enforced** (the sector service is IO-bound and the engine is
   pure/synchronous). Surfaced via the `max_same_sector_not_enforced` warning and the form
   field label "Max Same Sector (not simulated)".

4. **Batch ranking tie-break.** Production ranks tied-score signals by `completed_at`; the
   backtest ranks by `abs(score)` only (stable/insertion order on ties). At the `max_trades`
   boundary with coarse integer scores, a different tied signal may be admitted.

5. **Scan-boundary candle.** A candle whose `open_time` equals an interior scan timestamp is
   excluded from both the preceding and following close-rule windows, so a TP/SL/funding that
   would land exactly on that one candle is deferred one candle. One candle per interior
   boundary (sub-1% at 5m granularity).

6. **`qty_step` / `min_qty` / `tick_size` / `max_leverage`** come from a best-effort Bybit
   instrument cache; on a refresh failure or an unlisted symbol they fall back to no-op
   defaults (no lot rounding, no tick rounding, no leverage cap) rather than imposing a
   possibly-wrong constraint.

7. **`slippage_bps` is a round-trip cost** applied adversely on both the entry and exit fill
   (production closes via market reduce-only orders that slip). This overrides the original
   spec's exact-exit-fill wording.
