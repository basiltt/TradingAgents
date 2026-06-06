# Backtesting System — Requirements Document

## Feature Summary

Build a comprehensive backtesting system that simulates the full auto-trade cycle (scan results → signal filtering → trade placement → close rule evaluation → position closure) using historical scheduled market scan data. Must produce TradingView-level metrics and visualizations with <1% deviation from real trading results.

## Key Constraints

- Uses real scan results from DB as signal source (not re-analyzing)
- Same parameters as Scheduled Market Scanner (all AutoTradeConfig fields)
- No account configs — user provides fresh capital, TP/SL, leverage, etc.
- Enforces auto-trade cycle rules (no new trades while previous cycle running)
- All close rules: EQUITY_RISE_PCT, EQUITY_DROP_PCT, SMART_DRAWDOWN, BREAKEVEN_TIMEOUT, MAX_DURATION, TRAILING_PROFIT
- Super fast execution (seconds, not minutes) with cached kline data
- TradingView-quality results (equity curve, drawdown chart, all standard metrics)
- NO AI Manager feature (deferred)
- <1% deviation from real trading results

---

## Requirements — Round 1

### Trading Domain (REQ-TD)

**REQ-TD-001: Core Return Metrics** — Must calculate: total return %, annualized return %, CAGR, total PnL (absolute), average trade return %, best/worst trade return %, average winning trade vs average losing trade size. All returns computed both gross (before fees) and net (after fees/funding).

**REQ-TD-002: Risk-Adjusted Return Metrics** — Must produce: Sharpe ratio (risk-free rate = 4.5% stablecoin yield), Sortino ratio, Calmar ratio, Omega ratio. All ratios annualized using √365 for crypto 24/7 markets.

**REQ-TD-003: Drawdown Analytics** — Track: max drawdown % (peak-to-trough), max drawdown duration, average drawdown %, per-position drawdown. Validates EQUITY_DROP_PCT close rule behavior.

**REQ-TD-004: Win/Loss Distribution Metrics** — Win rate %, profit factor, payoff ratio, expectancy per trade, max consecutive wins/losses, win rate by direction (LONG vs SHORT).

**REQ-TD-005: Trade Duration & Frequency Metrics** — Average/median trade duration, time between trades, trades per period, exposure time %. Validates BREAKEVEN_TIMEOUT and MAX_DURATION accuracy.

**REQ-TD-006: Fee Model (Maker/Taker + Funding)** — Taker 0.055% on entry (market), taker 0.055% on SL exits, maker 0.02% on TP exits. Funding rates every 8h. Fees deducted from realized PnL.

**REQ-TD-007: Slippage Model** — Configurable slippage (default 0.05% large-cap, 0.15% small-cap). Entry slippage worsens fill. TP = favorable (limit-like). SL = unfavorable (market-like).

**REQ-TD-008: Leverage-Adjusted Position Sizing** — qty = (capital × capital_pct × leverage) / entry_price. Track used margin vs free margin. Reject if margin > available.

**REQ-TD-009: TP/SL Price Level Calculation** — TP: entry ± (entry × tp_pct / leverage / 100). SL: entry ∓ (entry × sl_pct / leverage / 100). Must match AutoTradeExecutor exactly.

**REQ-TD-010: Liquidation Price Simulation** — liq_price = entry × (1 − 1/leverage + MMR). Check before TP/SL each candle. Liquidation fee 0.06%.

**REQ-TD-011: Gap-Through-Stop Execution** — When kline low/high breaches SL, close at breach price (worst within candle), not candle close.

**REQ-TD-012: Maximum Leverage Cap Enforcement** — Cap to per-symbol max leverage. Default 25x for unknowns.

**REQ-TD-013: Funding Rate Impact** — Apply funding at 00:00, 08:00, 16:00 UTC. Use historical rates where available; configurable average otherwise.

**REQ-TD-014: Symbol Delisting/Trading Halt** — Force-close at last available price with warning flag. Track as "forced exits."

**REQ-TD-015: Cycle Lock Enforcement** — No new trades while cycle active (positions open). Subsequent scan signals IGNORED until cycle complete.

**REQ-TD-016: Signal Timing & Fill Delay** — Entry at next kline open after scan timestamp. Configurable fill_delay_seconds (default 5s).

**REQ-TD-017: Filter Chain Replication** — All 18 steps from AutoTradeExecutor replicated exactly.

**REQ-TD-018: TRAILING_PROFIT Mechanics** — Activates at activation_pct, tracks peak, exits at 50% peak drawdown. Per-candle evaluation.

**REQ-TD-019: BREAKEVEN_TIMEOUT Rule** — Force close if not profitable within timeout_hours.

**REQ-TD-020: Close Rule Priority** — Liquidation > SL > EQUITY_DROP_PCT > TRAILING > BREAKEVEN > MAX_DURATION > TP > EQUITY_RISE_PCT.

**REQ-TD-021: Deviation Benchmark Framework** — Reproduce historical trades with <1% PnL deviation. Deviation report per matched trade.

**REQ-TD-022: Kline Resolution** — 5-min minimum for close rule evaluation. 1-min preferred for TRAILING_PROFIT accuracy.

**REQ-TD-023: Capital Compounding vs Fixed** — Support both modes. Default = compounding (matches production).

**REQ-TD-024: Equity Curve with Drawdown Overlay** — Time-series chart with entry/exit markers, linear/log scale toggle.

**REQ-TD-025: Monthly Returns Heatmap** — Calendar heatmap showing returns by month (green/red), row totals.

### Performance Engineering (REQ-PE)

**REQ-PE-001: Columnar Binary Cache** — Store kline data in numpy/Arrow/Feather format, memory-mapped at simulation time.

**REQ-PE-002: Tiered Cache (L1/L2/L3)** — L1 = in-process numpy, L2 = memory-mapped files, L3 = PostgreSQL. Simulation reads only L1.

**REQ-PE-003: Append-Only Cache with Gap Detection** — Append new candles, fetch only delta. Metadata index for instant gap check.

**REQ-PE-004: Partitioned Storage by Month** — Monthly chunks for parallel reads and bounded file sizes.

**REQ-PE-005: Scan-Aligned Time Index** — Sorted index mapping scan_timestamp → signals. O(1) lookup, fits in memory.

**REQ-PE-006: Pre-Materialized Price Matrices** — 2D numpy array (candles × symbols) for vectorized operations.

**REQ-PE-007: Timestamp Normalization** — UTC Unix ms, uniform spacing, forward-filled gaps. O(1) time-to-index.

**REQ-PE-008: Vectorized Close-Rule Evaluation** — numpy arrays for all rules. Target <1μs per position per tick.

**REQ-PE-009: Event-Driven Sparse Simulation** — Only process symbols with open positions. 99%+ tick reduction.

**REQ-PE-010: Struct-of-Arrays Position State** — Parallel numpy arrays for positions, eliminates object overhead.

**REQ-PE-011: Branch-Free Trailing Update** — np.maximum for running max, vectorized comparison.

**REQ-PE-012: Lazy Loading with LRU Eviction** — Only load symbols that fire signals. 2GB ceiling.

**REQ-PE-013: Float32 Precision** — Halves memory. Sufficient for crypto prices (7 significant digits).

**REQ-PE-014: Streaming Equity Curve with Downsampling** — Pre-allocated array, downsample to ~720 points before API transfer.

**REQ-PE-015: Process Pool for Parameter Optimization** — multiprocessing.Pool, read-only mmap. 100 variations in <30s on 8 cores.

**REQ-PE-016: Concurrent Kline Download** — asyncio + semaphore (15 req/s). Priority: scan-result symbols first.

**REQ-PE-017: Background Cache Warming** — First-time download ~5.7 min for full universe. Background job with progress.

**REQ-PE-018: GIL-Free Simulation Loop** — numpy ops release GIL. Optional Numba JIT with nogil=True.

**REQ-PE-019: Incremental Sync with Resume** — Per-symbol checkpoint. Resume on crash without re-download.

**REQ-PE-020: Prioritized Download Queue** — Signals symbols first (80-150), then background fill remaining universe.

**REQ-PE-021: Delta-Only API Calls** — Watermark per symbol. Repeat runs = 0 API calls.

**REQ-PE-022: Staleness-Tolerant Design** — Closed candles are immutable. Never cache current candle.

**REQ-PE-023: Symbol Lifecycle Tracking** — Listing/delisting dates. Frozen cache for dead symbols.

**REQ-PE-024: Compressed Results API** — Gzip + delta encoding for equity curve. Paginated trade list.

**REQ-PE-025: SSE for Long Backtests** — Stream progress for parameter optimization. Direct results for single runs.

### UX/Visualization (REQ-UX)

**REQ-UX-001: Multi-Section Configuration Form** — Collapsible sections: Capital & Leverage, Entry Filters, Close Rules, Scan Source Selection. Same neumorphic card pattern.

**REQ-UX-002: Scan Source Picker with Date Range** — Calendar + presets (7d/30d/90d/All). Sparkline preview of scan density.

**REQ-UX-003: Parameter Preset Save/Load** — Named presets with "Duplicate & Tweak." Persist per-user.

**REQ-UX-004: Real-Time Validation Preview** — Inline warnings: estimated trades, data coverage, liquidation risk.

**REQ-UX-005: Tabbed Results Dashboard** — Overview | Equity Curve | Trade List | Analysis | Comparison. Sticky summary header with 4 hero metrics.

**REQ-UX-006: Overview Performance Grid** — Profitability, Risk, Trade Statistics, Timing groups. 3-4 column responsive grid.

**REQ-UX-007: Monthly Returns Heatmap** — Calendar heatmap, toggle monthly/weekly, hover for exact figures.

**REQ-UX-008: Interactive Equity Curve** — Area chart + drawdown overlay, log/linear toggle, crosshair, zoom, buy/sell markers.

**REQ-UX-009: Trade Entry/Exit Connectors** — Green/red connector lines on equity curve. Click for trade detail popover.

**REQ-UX-010: P&L Distribution Histogram** — Bucketed histogram with normal curve overlay, zero-line separator.

**REQ-UX-011: Trade Duration Distribution** — Duration histogram, color-coded by win/loss.

**REQ-UX-012: Win/Loss Streak Chart** — Bar chart of consecutive streaks + frequency distribution.

**REQ-UX-013: Underwater (Drawdown) Chart** — Dedicated full-width drawdown area chart, annotated top 3 deepest.

**REQ-UX-014: Sortable/Filterable Trade Table** — TanStack Table with symbol/direction/PnL/duration/close-rule columns. CSV export.

**REQ-UX-015: Trade Replay Card** — Expanded detail with mini price chart, close rule annotations, evaluation timeline.

**REQ-UX-016: Side-by-Side Comparison** — 2-4 runs, overlaid equity curves, highlighted best metrics.

**REQ-UX-017: Parameter Diff Highlighter** — Shows ONLY differing params between compared runs.

**REQ-UX-018: Synchronized Crosshair** — Hover on one chart updates all others to same timestamp.

**REQ-UX-019: Date Range Brush Selector** — Miniature overview for sub-range zoom. Metrics recalculate.

**REQ-UX-020: Animated Progress** — Progress bar + live trade counter + real-time equity animation.

**REQ-UX-021: Multi-Format Export** — PDF report, CSV trades, JSON results, PNG/SVG charts.

**REQ-UX-022: Responsive Stacking** — Desktop side-by-side, tablet/mobile vertical stack with simplified charts.

**REQ-UX-023: Empty/Error/Loading States** — Illustrated empty state, skeleton loading, error with fix suggestions.

**REQ-UX-024: Backtest History Sidebar** — Previous runs list with sparkline equity, star/pin, delete.

**REQ-UX-025: Keyboard Shortcuts** — R=re-run, C=compare, ←→=tabs, Esc=close, E=export.

### Data Accuracy (REQ-DA)

**REQ-DA-001: TP/SL Trigger on Wicks** — Evaluate against candle high/low, not just close. Fill at trigger price.

**REQ-DA-002: Same-Candle TP/SL Ambiguity** — When both could trigger: use open-proximity heuristic. Configurable: pessimistic/optimistic/open-proximity.

**REQ-DA-003: Full-Fill Only** — No partial fills. Position fills entirely or not.

**REQ-DA-004: Market Order Slippage** — Fill at open + slippage_bps. Modes: fixed_bps, volume_adjusted, zero.

**REQ-DA-005: Mark Price for Entry** — Use mark price (candle open as proxy). Document accuracy when unavailable.

**REQ-DA-006: Stop-Market Fill Slippage** — Trigger at stop price, apply 1-5 bps fill slippage beyond trigger.

**REQ-DA-007: Taker Fee on Entry/Exit** — 0.055% × notional for market, 0.02% for limit TP.

**REQ-DA-008: Fee Deduction from Wallet** — Immediate deduction. Entry fee reduces available capital.

**REQ-DA-009: Fee Impact on Liquidation** — Cumulative fees bring liquidation closer. Track accurately.

**REQ-DA-010: 8-Hour Funding Application** — At exact timestamps. Position open at 07:59 closed at 08:01 DOES pay.

**REQ-DA-011: Historical Funding Data** — Use actual Bybit historical rates. Flat average introduces >5% deviation.

**REQ-DA-012: Funding Compounding** — Each payment adjusts wallet balance, affecting equity calculations.

**REQ-DA-013: Candle-Granularity Rule Evaluation** — Rules evaluated at every candle boundary. Document time deviation per resolution.

**REQ-DA-014: Equity Rule Frequency** — EQUITY_RISE/DROP evaluated every candle across ALL positions.

**REQ-DA-015: Trailing Peak on Intra-Candle** — Peak = max(peak, high-entry) for longs. Candle-close-only underestimates.

**REQ-DA-016: Liquidation Modeling** — Check before TP/SL each candle. 0.06% liquidation fee.

**REQ-DA-017: Gap Moves** — If candle opens beyond SL/TP, fill at open (not trigger price).

**REQ-DA-018: Multiple Positions Same Cycle** — Enforce capital_pct × num ≤ available. Sequential margin deduction.

**REQ-DA-019: Zero-Volume Candle** — Skip execution evaluation. Time-based rules still advance.

**REQ-DA-020: Mark Price for PnL** — unrealized_pnl = (mark - entry) × qty × direction.

**REQ-DA-021: Mark vs Last Price Divergence** — Document as known deviation source. ±0.1% tolerance for liquid pairs.

**REQ-DA-022: Real Trade Replay Validation** — Replay known trades, compare PnL. Threshold ≤1% or ≤$0.01.

**REQ-DA-023: Per-Component Deviation Decomposition** — Break into: entry, exit, fee, funding, timing deviations.

**REQ-DA-024: Statistical Validation** — Validate over ≥50 trades. Acceptable: mean ≤0.5%, p95 ≤1.0%.

**REQ-DA-025: Exchange-Matched Decimal Precision** — Use Decimal arithmetic. Per-symbol price/qty precision. ROUND_HALF_EVEN.

### Backend Architecture (REQ-BA)

**REQ-BA-001: Backtest Creation Endpoint** — `POST /api/v1/backtests`. Returns backtest_id + status PENDING.

**REQ-BA-002: Status & Results Endpoint** — `GET /api/v1/backtests/{id}`. Full results when complete, lightweight status for polling.

**REQ-BA-003: List with Filtering** — `GET /api/v1/backtests`. Paginated, sortable by metrics.

**REQ-BA-004: Cancellation Endpoint** — `DELETE /api/v1/backtests/{id}`. Sets cancellation flag checked between cycles.

**REQ-BA-005: Cache Warmup Endpoint** — `POST /api/v1/backtests/warmup-cache`. Pre-fetch klines before run.

**REQ-BA-006: Backtest Runs Table** — UUID PK, status enum, config_snapshot JSONB, date range, progress, timestamps.

**REQ-BA-007: Results Table** — equity_curve JSONB, trades JSONB, metrics JSONB. Top-level numerics for sorting.

**REQ-BA-008: Kline Cache Table** — (symbol, interval, open_time) composite PK. Partitioned by month.

**REQ-BA-009: Migration Versioning** — Add to existing _MIGRATIONS list. Idempotent.

**REQ-BA-010: BacktestService** — Orchestration: validate → check cache → enqueue → persist results.

**REQ-BA-011: Pure Simulation Engine** — Stateless. Zero DB/API access. All data passed in. Trivially testable.

**REQ-BA-012: Kline Cache Service** — Read/write/gap-check. Batch fetch with rate limiting.

**REQ-BA-013: Trade Cycle Simulator** — Core loop mirrors AutoTradeExecutor + CloseRuleEvaluator in memory.

**REQ-BA-014: Config Validation** — Check scan data availability, bounds, sane defaults. 422 on failure.

**REQ-BA-015: Config Parity with AutoTradeConfig** — Every decision-affecting field included. Add starting_capital, fees.

**REQ-BA-016: Missing Kline Handling** — Skip trade, log warning, continue. Include data_gaps in results.

**REQ-BA-017: Simulation Determinism** — Identical inputs = identical outputs. No datetime.now(), no random.

**REQ-BA-018: Zero-Trade Scenario** — Return COMPLETED with empty metrics + warnings explaining why.

**REQ-BA-019: Async Task with Progress** — asyncio.Task, progress updates in DB, in-memory handle for cancel.

**REQ-BA-020: Concurrent Limit** — Max 3 concurrent backtests. Semaphore gate. Queue depth in status.

**REQ-BA-021: Full Result Persistence** — Store complete results (50-500KB per run). No recomputation needed.

**REQ-BA-022: Comparison Endpoint** — `GET /api/v1/backtests/compare?ids=`. Rebased equity + side-by-side metrics.

**REQ-BA-023: Injected Clock** — Engine accepts time_provider parameter. Never calls time.time().

**REQ-BA-024: Scan Result Query Integration** — Reuses existing DB queries for scan results.

**REQ-BA-025: Validation Endpoint** — Dev-only endpoint comparing simulated vs actual PnL.

---

## Brainstorm Tracking

| Round | Agents | Requirements Added | Total |
|-------|--------|-------------------|-------|
| 1 | TD, PE, UX, DA, BA | 125 | 125 |
| 2 | GAP, QA, SEC, OPS, OPT | 95 | 220 |
| 3 | TV, Consolidation, Crypto, DB, ERR | 59 | 279 |
| 4 | MVP-completeness, Workflow | 25 | 304 |
| 5 | Clean-round audit | 1 (near-clean) | 305 |

---

## Requirements — Round 5 (Final)

### Simulation Event Order (REQ-FINAL)

**REQ-FINAL-001: Intra-Candle Event Priority Order** — Within each time step (candle), process events in this canonical order:
1. Apply funding rate (if 8-hour boundary crossed during this candle)
2. Check liquidation against candle's extreme (low for LONG, high for SHORT)
3. Check TP/SL on wicks (high ≥ TP for LONG, low ≤ SL for LONG)
4. Check equity-based close rules (EQUITY_RISE/DROP on current unrealized PnL)
5. Check trailing profit (update peak, check 50% drawdown)
6. Check time-based rules (BREAKEVEN_TIMEOUT, MAX_DURATION)
7. After all closes processed → recalculate available capital
8. If no active cycle → evaluate new signals from current scan batch
9. If new positions opened → create their close rules (initial state)

This order ensures earlier events (liquidation, SL) take priority over later ones (new signals), matching real system behavior.

---

## Requirements — Round 4

### MVP Completeness (REQ-MVP)

**REQ-MVP-001: Backtest-Specific Config Fields** — starting_capital (required), date_range_start/end, fee_rate_pct (default 0.055%), slippage_bps (default 2), funding_rate_model (NONE/FIXED_8H/HISTORICAL).

**REQ-MVP-002: Scan Source Selection** — Three modes: by schedule_id + date range (default), by date range only (all scanners), by explicit scan_id list.

**REQ-MVP-003: Entry Price = Candle Close at Signal Time + Slippage** — No look-ahead. Use close of candle at T_signal.

**REQ-MVP-004: Capital Pct = Percentage of INITIAL Capital** — Fixed sizing, matches real AutoTradeExecutor behavior.

**REQ-MVP-005: Insufficient Capital Guard** — Skip signal if available_margin < required_size. Log reason.

**REQ-MVP-006: Force-Close at Backtest End** — All open positions closed at last kline close. close_reason = "BACKTEST_END".

**REQ-MVP-007: Equity Curve Per-Candle Resolution** — One point per kline. LTTB downsample to max 2000 for API.

**REQ-MVP-008: Multi-Position Equity Formula** — equity = starting_capital + Σ(realized_pnl) + Σ(unrealized_pnl) - Σ(fees).

**REQ-MVP-009: Buy & Hold = BTC/USDT** — Benchmark comparison using BTC price over backtest period.

**REQ-MVP-010: Fee Deduction at Entry + Exit** — Immediately deduct from available capital. Included in equity curve.

**REQ-MVP-011: Close Rules Evaluated Per-Candle-Close** — Exception: liquidation checked on wicks (candle low/high).

**REQ-MVP-012: Trailing Profit State Machine** — Activate → track peak → trigger at 50% drawdown from peak → close.

**REQ-MVP-013: No Look-Ahead Bias** — Signal at T can only use data ≤ T. Engine enforces strict temporal ordering.

**REQ-MVP-014: Cycle Lock Replication** — No new signals processed while any position from current cycle is open.

**REQ-MVP-015: Kline Completeness Pre-Check** — Verify coverage before simulation. Fetch gaps. Abort on >3-interval gaps.

### User Workflow (REQ-FLOW)

**REQ-FLOW-001: Quick Backtest Mode** — Sensible defaults (20x, 5%, 150% TP, 100% SL). Only select scanner + capital to run.

**REQ-FLOW-002: Clone & Edit** — One-click duplicate of previous config. Modify + re-run.

**REQ-FLOW-003: Kline Readiness Indicator** — Show cache status before run. Pre-fetch on date selection.

**REQ-FLOW-004: Backtest from Scanner Context** — "Backtest These Settings" on scan detail + schedule pages.

**REQ-FLOW-005: Confidence Indicators** — Trade count badge, data coverage %, slippage note.

**REQ-FLOW-006: Export** — PDF report, CSV trades, JSON full, PNG chart.

**REQ-FLOW-007: Navigation** — Top-level "Backtesting" nav item. Routes: /backtest, /backtest/new, /backtest/$id.

**REQ-FLOW-008: Run History & Comparison** — Table of past runs. Sort by metrics. Multi-select compare.

**REQ-FLOW-009: Parameter Sensitivity Hints** — Post-hoc analysis showing which params had near-threshold trades.

**REQ-FLOW-010: Graceful Empty States** — Guide users to scan data, offer partial-data runs, no dead ends.


---

## Requirements — Round 2

### Gap Analysis (REQ-GAP)

**REQ-GAP-001: Multi-Scan Time Stepping** — Iterate through all historical scan timestamps chronologically. Produce signals at each step. Advance clock scan-by-scan, evaluating positions between intervals.

**REQ-GAP-002: Cycle Lock State Machine** — Check whether previous cycle is active at each scan. If skip_if_positions_open=true and positions remain, discard entire scan. Log as "cycle-locked."

**REQ-GAP-003: Cycle Completion Between Scans** — Evaluate close rules at candle granularity between scans. Cycle complete only when ALL positions closed.

**REQ-GAP-004: close_on_profit_pct Termination** — Close ALL positions when cumulative P&L exceeds threshold. Triggers mid-candle. Frees cycle lock.

**REQ-GAP-005: Batch Mode Pipeline** — Collect → deduplicate by ticker → rank by score → apply filters → select top-N.

**REQ-GAP-006: Immediate Mode Pipeline** — Process signals one-at-a-time in order. No cross-signal dedup.

**REQ-GAP-007: Score Deduplication** — Same ticker multiple times → keep highest score only.

**REQ-GAP-008: fill_to_max_trades Relaxed Pass** — Second pass bypasses min_confidence/min_score. Still enforces blacklist/sector limits.

**REQ-GAP-009: Relaxed Pass Tagging** — Tag entries with "strict_pass" vs "relaxed_fill." Report comparative performance.

**REQ-GAP-010: post_scan_recheck** — _Corrected after verifying production source._ Production's `post_scan_recheck` (auto_trade_service.py) runs ONCE per scan, synchronously at scan completion — scanner_service calls it immediately after `execute_batch`, and the method is a single non-looping pass. It is NOT an iterative loop that fills freed slots as positions close over the scan window. Because the backtest anchors each scan to its `completed_at` instant (the same instant production runs the recheck), the per-scan open branch already models the post-recheck state. The residual real trigger — a position closing in the sub-second gap between batch-skip and the recheck call — is far below the 5-minute candle resolution and is therefore not separately modeled. Documented in spec "Known Modeling Approximations."

**REQ-GAP-011: Recheck Timing** — _Superseded by the REQ-GAP-010 correction._ The original "max recheck iterations (default 3)" assumed an iterative-fill model that production does not implement. There is no per-window recheck loop; re-trading a scan's signals does not recur as its positions close. The next opportunity to trade is the next scheduled scan with its own signals. No `max_recheck_iterations` config field is exposed.

**REQ-GAP-012: Backtest-Internal Blacklist** — Compute adaptive blacklist from backtest-internal performance only.

**REQ-GAP-013: Blacklist Warm-Up** — Configurable warm-up scans (no blacklist applied). Optional seed from real DB history.

**REQ-GAP-014: SMART Drawdown Selective Close** — Close only losing positions. Profitable ones remain. Reference resets.

**REQ-GAP-015: SMART Drop Reference Tracking** — Rolling reference_equity that resets after each SMART close event.

**REQ-GAP-016: Multi-Config Batch Execution** — Accept array of configs (up to 20). Execute independently, return comparison matrix.

**REQ-GAP-017: Parameter Sensitivity Grid** — 1-2 params with ranges → cartesian product → metric heatmap.

**REQ-GAP-018: Position State Continuity** — Full position state carries across scan boundaries (entry, PnL, peaks, timers).

**REQ-GAP-019: Trailing High-Water Mark** — Per-position highest PnL tracked at candle granularity between scans.

**REQ-GAP-020: Signal Collision Tiebreaker** — Same ticker same timestamp → highest score wins. Deterministic.

**REQ-GAP-021: Close Ordering Within Candle** — Deterministic priority: liquidation > SL > EQUITY_DROP > BREAKEVEN > TP > TRAILING > MAX_DURATION.

**REQ-GAP-022: Funding Between Scans** — Accumulate funding at each 8h interval. Affects equity rule triggers.

**REQ-GAP-023: Per-Scan Breakdown Report** — Scan-by-scan: signals generated, filtered, entered, cycle status, P&L contribution.

**REQ-GAP-024: Filter Funnel Visualization** — Waterfall chart: Total → Dedup → Confidence → Blacklist → Sector → MaxTrades → Entered.

**REQ-GAP-025: Cycle Timeline Visualization** — Gantt chart: position durations, close events, cycle-lock periods, scan timestamps.

### QA/Testing (REQ-QA)

**REQ-QA-001: Deterministic PnL Tests** — Bit-for-bit identical results across runs with identical inputs.

**REQ-QA-002: Close Rule Isolation Tests** — Each rule tested independently with synthetic klines triggering exactly that rule.

**REQ-QA-003: Cycle Lock Tests** — Verify engine refuses new positions during active cycle.

**REQ-QA-004: Historical Replay Integrity** — Load ≥100 real scan results, verify correct chronological consumption.

**REQ-QA-005: Kline Cache Consistency** — Verify cached data matches Bybit API golden reference.

**REQ-QA-006: Golden-Result Snapshots** — ≥5 frozen scenarios, CI fails if any metric deviates >0.1%.

**REQ-QA-007: Behavioral Diff** — Structured diff report on engine changes.

**REQ-QA-008: Zero-Volume/Illiquid Candles** — Test handling of volume=0, flat, massive-spread candles.

**REQ-QA-009: Delisted Symbol Mid-Position** — Force-close, warn, don't corrupt state.

**REQ-QA-010: Extreme Leverage Liquidation Boundary** — 100x leverage, exact threshold testing.

**REQ-QA-011: Equity Non-Negativity Invariant** — Property-based testing, ≥10,000 scenarios per CI run.

**REQ-QA-012: Conservation of Value** — realized_pnl - fees = balance_delta for every trade.

**REQ-QA-013: Execution Time Budget** — Full backtest ≤10s on CI. Fail if p95 exceeds budget.

**REQ-QA-014: Memory Ceiling** — Peak RSS ≤512MB. Fail CI if breached.

**REQ-QA-015: Synthetic Kline Generator** — Fixture factory: trend/volatility/gaps/seed parameterized.

**REQ-QA-016: Mock Scan Result Factory** — Configurable signal direction/confidence/timestamp fixtures.

**REQ-QA-017: Per-Trade Deviation Audit** — ≥20 real trades, <1% deviation each. <0.5% aggregate.

**REQ-QA-018: Slippage Model Validation** — Compare sim fills vs actual fills. Quantify systematic bias.

**REQ-QA-019: Equity Curve Rendering** — Unit test chart component with known data points.

**REQ-QA-020: Full Pipeline E2E** — API → Engine → Results in <30s with fixture data.

### Security (REQ-SEC)

**REQ-SEC-001: Result Ownership** — User ID scoping on all queries.

**REQ-SEC-002: Scan Data Scoping** — Only access own scanner data.

**REQ-SEC-003: Config Sanitization** — Reject injection characters in all string fields.

**REQ-SEC-004: Numeric Strict Typing** — Reject NaN, Infinity, -0.

**REQ-SEC-005: Date Range Ceiling** — Max 365 days. Reject with clear error.

**REQ-SEC-006: Concurrent Throttling** — Max 2 simultaneous per user.

**REQ-SEC-007: Symbol Count Limit** — Max 200 symbols per run.

**REQ-SEC-008: Cache Integrity Verification** — Checksum on write, verify on read.

**REQ-SEC-009: Cache Source Attribution** — Store fetch metadata for audit.

**REQ-SEC-010: Endpoint Rate Limiting** — Max 10 runs/user/hour.

**REQ-SEC-011: Credential Stripping** — Zero access to ACCOUNTS_ENCRYPTION_KEY in backtest path.

**REQ-SEC-012: Export Sanitization** — No internal paths/hostnames/tokens in exports.

**REQ-SEC-013: Leverage Bounds** — 1x–125x. Reject ≤0 or above max.

**REQ-SEC-014: Capital Sanity Checks** — Positive, below $100M. TP/SL within (0%, 1000%].

**REQ-SEC-015: Contradictory Config Rejection** — Reject degenerate rule combinations.

### Operations (REQ-OPS)

**REQ-OPS-001: Cache Size Budget** — 5GB ceiling. LRU eviction. Periodic check.

**REQ-OPS-002: Cache TTL** — 7-day TTL for closed candles. Never cache current candle.

**REQ-OPS-003: Run Status Tracking** — QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED in DB.

**REQ-OPS-004: Memory Ceiling** — 512MB per run. Chunked kline loading.

**REQ-OPS-005: Partial Results on Failure** — Commit trades up to failure point. Flag partial=true.

**REQ-OPS-006: Structured Logging** — Trace ID per run. JSON structured. Phase/symbol/timestamp.

**REQ-OPS-007: Warmup Graceful Degradation** — Retry → stale cache → skip symbol. Never fail entire run.

**REQ-OPS-008: Migration Safety** — IF NOT EXISTS. Never ALTER existing production tables.

**REQ-OPS-009: Concurrent Limiting** — Max 3 runs. Queue or 429.

**REQ-OPS-010: Config Version Pinning** — JSONB snapshot. Reject unknown fields.

**REQ-OPS-011: Execution Timeout** — 120s wall-clock default. asyncio.wait_for.

**REQ-OPS-012: Shared Rate Limiting** — Kline fetch shares rate budget with live scanner.

**REQ-OPS-013: Health Check Integration** — Report active runs, cache size, queue depth.

**REQ-OPS-014: Idempotent Deduplication** — Same config+range within 1h → return cached result.

**REQ-OPS-015: Vacuum & Index Maintenance** — Monthly partitions. Weekly ANALYZE.

### Parameter Optimization (REQ-OPT)

**REQ-OPT-001: Grid Search** — Exhaustive search over user-defined ranges/steps.

**REQ-OPT-002: Space Definition UI** — Min/max/step form. Show permutation count + estimated time.

**REQ-OPT-003: Objective Selection** — Maximize: net profit, Sharpe, profit factor, win rate. Minimize: drawdown.

**REQ-OPT-004: Walk-Forward Optimization** — In-sample/out-of-sample splits. Walk-forward efficiency ratio.

**REQ-OPT-005: Holdout Validation** — Auto-reserve 20% recent data. Compare IS vs OOS.

**REQ-OPT-006: Bayesian Optimization** — GP surrogate + EI acquisition for >5000 permutations.

**REQ-OPT-007: Genetic Algorithm** — Tournament selection, crossover, mutation. Configurable.

**REQ-OPT-008: Multi-Objective Pareto** — 2-3 competing objectives. Interactive Pareto frontier.

**REQ-OPT-009: Monte Carlo Confidence Intervals** — 1000 bootstrapped iterations. 90/95/99% CIs.

**REQ-OPT-010: Sensitivity Analysis** — Partial dependence + 2D heatmaps per parameter pair.

**REQ-OPT-011: Neighborhood Robustness Score** — Evaluate ±1 step neighbors. Flag fragile solutions.

**REQ-OPT-012: Overfitting Warnings** — WF efficiency <0.5, IS Sharpe >3, boundary clustering, OOS degradation >50%.

**REQ-OPT-013: Deflated Sharpe Ratio** — Correct for multiple testing bias.

**REQ-OPT-014: Regime Stability** — Report per-regime performance. Flag regime-dependent params.

**REQ-OPT-015: Parameter Heatmap** — Interactive 2D heatmaps for metric vs param pairs.

**REQ-OPT-016: 3D Surface Plot** — Interactive 3D visualization of objective landscape.

**REQ-OPT-017: Top-N Results Table** — Top 20 ranked, all metrics, robustness/overfit flags.

**REQ-OPT-018: Parallel Execution** — Multi-process. 1000 permutations < 60s on 8 cores.

**REQ-OPT-019: Incremental Cache** — Reuse prior results for overlapping parameter ranges.

**REQ-OPT-020: Run Persistence & Comparison** — Store optimization runs. Compare how optima shift over time.

---

## Requirements — Round 3

### TradingView Parity (REQ-TV)

**REQ-TV-001: Buy & Hold Return** — Show what holding the primary asset from first entry to end would return ($ and %).

**REQ-TV-002: Buy & Hold Equity Curve** — Overlay line on equity chart showing passive hold performance.

**REQ-TV-003: Max Run-up** — Highest equity peak above initial capital during backtest ($ and %).

**REQ-TV-004: Open P&L** — Unrealized P&L on positions still open at backtest end (mark-to-market).

**REQ-TV-005: Total Commission Paid** — Sum of all trading fees across all trades.

**REQ-TV-006: Max Contracts Held** — Peak position count at any point.

**REQ-TV-007: Total Open Trades** — Count of positions still open at conclusion.

**REQ-TV-008: Avg Winning Trade** — Mean profit on winners ($ and %).

**REQ-TV-009: Avg Losing Trade** — Mean loss on losers ($ and %).

**REQ-TV-010: Ratio Avg Win / Avg Loss** — Payoff ratio.

**REQ-TV-011: Largest Winning Trade** — Single best trade ($ and %).

**REQ-TV-012: Largest Losing Trade** — Single worst trade ($ and %).

**REQ-TV-013: Avg Bars in Winning Trades** — Mean duration of winners.

**REQ-TV-014: Avg Bars in Losing Trades** — Mean duration of losers.

**REQ-TV-015: Margin Calls** — Count of liquidation/margin events.

**REQ-TV-016: Max Consecutive Wins ($)** — Dollar profit during best win streak.

**REQ-TV-017: Max Consecutive Losses ($)** — Dollar loss during worst loss streak.

**REQ-TV-018: Cumulative Profit per Trade** — Running total P&L in trade list.

**REQ-TV-019: Trade Run-up (MFE)** — Max Favorable Excursion per trade.

**REQ-TV-020: Trade Drawdown (MAE)** — Max Adverse Excursion per trade.

**REQ-TV-021: Long/Short Split** — All metrics broken into All / Long / Short columns.

**REQ-TV-022: Recovery Factor** — Net Profit / Max Drawdown.

**REQ-TV-023: CAGR** — Compound Annual Growth Rate.

**REQ-TV-024: Calmar Ratio** — CAGR / Max Drawdown %.

**REQ-TV-025: Average Drawdown %** — Mean of all drawdown periods.

**REQ-TV-026: Average Drawdown Duration** — Mean time in drawdown.

**REQ-TV-027: Max Drawdown Duration** — Longest underwater period.

**REQ-TV-028: Expectancy** — (win_rate × avg_win) − (loss_rate × avg_loss).

### Crypto-Specific (REQ-CRYPTO)

**REQ-CRYPTO-001: Trading Fee Deduction** — Taker 0.055% on entry/exit. Deduct from wallet immediately.

**REQ-CRYPTO-002: Funding Rate Settlement** — Apply at 00:00/08:00/16:00 UTC. Use historical rates.

**REQ-CRYPTO-003: Instrument Precision** — Enforce qty_step, min_qty, tick_size, max_qty, max_leverage per symbol.

**REQ-CRYPTO-004: Mark Price for TP/SL Triggers** — TP/SL evaluated against mark price candles.

**REQ-CRYPTO-005: Slippage Model** — Configurable bps (default 2). Always unfavorable direction.

**REQ-CRYPTO-006: Isolated Margin Liquidation** — Check each candle. Close at liq_price. 0.5% MMR Tier 1.

**REQ-CRYPTO-007: Kline Type Specification** — Cache both trade and mark kline types when available.

**REQ-CRYPTO-008: Entry Price Determination** — Enter at open of candle AFTER scan timestamp (no look-ahead).

**REQ-CRYPTO-009: Intra-Candle TP/SL Ordering** — Default pessimistic (SL wins ties). Configurable.

### Database Design (REQ-DB)

**REQ-DB-001: Range-Partition by Month** — kline_cache partitioned by open_time monthly.

**REQ-DB-002: Composite Covering Index** — (symbol, interval, open_time) INCLUDE OHLCV for index-only scans.

**REQ-DB-003: Scan Results Index** — (scan_id, started_at DESC) for date-range + config lookup.

**REQ-DB-004: Normalized Result Storage** — Separate tables: backtest_runs, backtest_equity_curves, backtest_trades.

**REQ-DB-005: GIN Index for Comparisons** — jsonb_path_ops on summary_metrics for containment queries.

**REQ-DB-006: Two-Phase Load (No SQL Join)** — Load signals first, then batch-load klines by symbol.

**REQ-DB-007: Separate Connection Pools** — Backtest pool (max 8, 120s timeout) isolated from live pool.

**REQ-DB-008: Coverage Tracking Table** — kline_cache_coverage for O(1) gap detection.

**REQ-DB-009: COPY for Bulk Insert** — Use copy_records_to_table for kline backfill.

**REQ-DB-010: Aggressive Autovacuum** — 1% scale factor on kline_cache. Prevent planner degradation.

### Error Handling (REQ-ERR)

**REQ-ERR-001: Kline Gap Handling** — Forward-fill ≤3 candles. Flag >3 candles. Skip >24h gaps.

**REQ-ERR-002: Unknown Symbol** — Skip signals, threshold abort at >20% unfetchable.

**REQ-ERR-003: Duplicate Signal Dedup** — By (symbol, timestamp, direction). Keep earliest scan_id.

**REQ-ERR-004: Cache Corruption Recovery** — Checksum verify, atomic writes, re-fetch on mismatch.

**REQ-ERR-005: Timeout with Partial Results** — 120s limit. Save partial. Return completed_through timestamp.

**REQ-ERR-006: OOM Prevention** — Streaming processing, memory budget, pre-flight check.

**REQ-ERR-007: DB Connection Failure** — 3 retries + exponential backoff + in-memory fallback.

**REQ-ERR-008: Cancellation Cleanup** — Cancel token, preserve partial cache, release resources.

**REQ-ERR-009: Symbol Rename** — Mapping table. Auto-detect. Continuous position across rename.

**REQ-ERR-010: Zero-Price / Coin Death** — Total loss capped at margin. Force-close at last price.

**REQ-ERR-011: Rate Limit Handling** — 10 concurrent, 100ms gap, progressive backoff, priority queue.

**REQ-ERR-012: Precision Drift** — Decimal for money. Per-trade validation. Never cumulative multiply.

### Consolidation Decisions

**DECISION-001: Numeric Precision (Resolves PE-013 vs DA-025)** — float64 for price arrays (not float32). Decimal for PnL/equity/fees.

**DECISION-002: Cache Strategy (Resolves PE-001 vs BA-008)** — PostgreSQL as primary store. In-memory DataFrame for simulation. Parquet deferred to Phase 2.

**DECISION-003: Evaluation Granularity** — Default 5-min candles for MVP. 1-min optional for accuracy. Trailing uses candle High as peak.

**DECISION-004: MVP Scope** — All REQ-OPT (parameter optimization) deferred to Phase 2. Core simulation + results dashboard in Phase 1.

**DECISION-005: Duplicates Resolved** — GAP-021 retired (covered by TD-020). DA-011/012 merged into TD-013. BA-020/SEC-006 merged into OPS-009.



