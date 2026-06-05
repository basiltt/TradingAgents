# Backtesting System — Implementation Plan

## Overview

**Phases:** 6 implementation phases + 1 integration phase
**Estimated Total Tasks:** ~45 tasks
**Approach:** TDD (test first, then implement)

---

## Phase 1: Shared Trading Rules Module + DB Migrations

**Goal:** Extract shared logic, create database tables, establish foundation.

### Task 1.1: Create `trading_rules.py` shared module
- **File:** `backend/services/trading_rules.py`
- **Test:** `tests/backend/test_trading_rules.py`
- **Functions:**
  - `compute_tp_sl(entry: float, side: str, tp_pct: float, sl_pct: float, leverage: int) -> tuple[float, float]`
  - `compute_position_size(sizing_capital: float, capital_pct: float, leverage: int, price: float, qty_step: float, min_qty: float, available_balance: float) -> float | None` — sizes from DYNAMIC sizing_capital (refreshed per cycle start from wallet_balance, matching production). Validates qty × price / leverage <= available_balance.
  - `compute_liquidation_price(entry: float, side: str, leverage: int, mmr: float = 0.005) -> float`
  - `compute_liquidation_pnl(initial_margin: float, entry_fee: float) -> float` — returns -(margin + fee), full margin loss on liq
  - `compute_unrealized_pnl(entry: float, current: float, qty: float, side: str) -> float`
  - `check_equity_rise(equity: float, reference: float, threshold: float) -> bool`
  - `check_equity_drop(equity: float, reference: float, threshold: float) -> bool`
  - `check_trailing_trigger(per_unit_pnl: float, peak: float, ratio: float = 0.5) -> bool`
  - `check_trailing_activation(current_price: float, entry_price: float, threshold_pct: float, upnl: float) -> bool` — returns False if upnl <= 0 (guard)
  - `determine_side(signal_direction: str, trade_direction: str) -> str`
  - `apply_slippage(price: float, side: str, slippage_bps: int) -> float`
  - `compute_fee(qty: float, price: float, fee_rate_pct: float) -> float`
  - `compute_breakeven_price(entry: float, side: str, leverage: int) -> float` — formula: entry × (1 ± 1/(leverage×100))
  - `check_close_on_profit(equity: float, cycle_start_equity: float, close_on_profit_pct: float, target_goal_value: float) -> bool` — Real formula: `effective_threshold = (close_on_profit_pct / 100) * target_goal_value`; triggers when `pnl_pct >= effective_threshold`
  - `lttb_downsample(points: list[dict], target_n: int) -> list[dict]` — Largest-Triangle-Three-Buckets
  - `compute_locked_margin(qty: float, entry_price: float, leverage: int) -> float` — returns (qty × entry) / leverage

### Task 1.2: Database migrations for backtesting tables
- **File:** `backend/async_persistence.py` (add to _MIGRATIONS list as **callable migration** — NOT string SQL)
- **Format:** `(38, _create_backtest_tables)` — async def callable, matching pattern of migration 33 (`_add_ai_manager_tables`)
- **CRITICAL:** Must be callable (not string SQL) because `PARTITION BY RANGE` + `DO $$ ... END $$` blocks break the `sql.split(";")` parser
- **Test:** Migration applies without error on test DB + `information_schema` assertions
- **Tables + columns:**
  - `kline_cache`: `symbol TEXT, interval TEXT, open_time TIMESTAMPTZ, open/high/low/close/volume DOUBLE PRECISION` — PK (symbol, interval, open_time), PARTITION BY RANGE (open_time). Create DEFAULT partition + months ±6 from now.
  - `kline_cache_coverage`: `symbol TEXT, interval TEXT, date DATE, candle_count SMALLINT, fetched_at TIMESTAMPTZ` — PK (symbol, interval, date)
  - `backtest_runs`: `id UUID PK DEFAULT gen_random_uuid(), status TEXT CHECK(...), config JSONB, scan_source JSONB, progress_pct SMALLINT DEFAULT 0, error_message TEXT, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now()`
  - `backtest_results`: `run_id UUID PK FK→backtest_runs ON DELETE CASCADE, metrics JSONB, equity_curve JSONB, summary JSONB, warnings JSONB DEFAULT '[]'`
  - `backtest_trades`: `id BIGINT GENERATED ALWAYS AS IDENTITY PK, run_id UUID FK→backtest_runs ON DELETE CASCADE, symbol TEXT, side TEXT CHECK('Buy','Sell'), entry_price NUMERIC(20,8), exit_price NUMERIC(20,8), qty NUMERIC(20,8), leverage SMALLINT, entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ, pnl NUMERIC(20,8), pnl_pct NUMERIC(8,4), fees_paid NUMERIC(20,8), close_reason TEXT, mfe_pct NUMERIC(8,4), mae_pct NUMERIC(8,4), signal_score SMALLINT, signal_confidence TEXT, scan_id TEXT, metadata JSONB DEFAULT '{}'`
- **Additional migration (39):** `ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS analysis_price NUMERIC(20,8)` — needed for signal entry price reference
- **Indexes:** `idx_backtest_runs_status` (partial: WHERE status IN ('pending','running')), `idx_backtest_runs_created` (created_at DESC), `idx_backtest_trades_run` (run_id)
- **Partition management:** `ensure_partition_exists(month)` — called by KlineCacheService BEFORE each INSERT batch. Creates month partition if not exists. Also creates DEFAULT partition as safety net.
- **ON CONFLICT:** kline inserts `DO NOTHING`; coverage `DO UPDATE SET candle_count=EXCLUDED.candle_count, fetched_at=now()`
- **Service wiring:** BacktestService initialized in UNCONDITIONAL section of main.py lifespan (alongside scanner_service). Must implement `.shutdown()` async method wired via `_safe_shutdown("backtest_service", ...)` in teardown.

### Task 1.3: Pydantic schemas for backtest
- **File:** `backend/schemas/backtest_schemas.py`
- **Test:** `tests/backend/test_backtest_schemas.py` (validation edge cases)
- **Models:** `BacktestCreateRequest`, `BacktestRunResponse`, `BacktestResultsResponse`, `BacktestTradeResponse`, `ScanSource`, `BacktestCompareResponse`, `SimulationResult`
- **BacktestCreateRequest must include:** All fields from spec FR-001 tables INCLUDING `target_goal_type` and `target_goal_value` (needed for close_on_profit_pct effective threshold formula). Default `target_goal_value=100.0` if not provided (makes close_on_profit_pct work as direct %).
- **SimulationResult dataclass:** `trades: list[dict]`, `equity_curve: list[dict]`, `metrics: dict`, `warnings: list[str]`, `filter_stats: dict` (signals processed/filtered/entered counts)
- **Validation:** Cross-field validators: SL% < 100% × leverage (prevent beyond-liquidation SL), breakeven_timeout < max_duration (if both set), leverage ≤ 125
- **Result persistence (in BacktestService after engine returns):**
  - `SimulationResult.metrics` → `backtest_results.metrics` (JSONB)
  - `SimulationResult.equity_curve` → `backtest_results.equity_curve` (JSONB, downsampled via LTTB to max 10K points)
  - `SimulationResult.filter_stats` → `backtest_results.summary` (JSONB — contains signals processed/filtered/entered counts per scan + filter funnel data)
  - `SimulationResult.warnings` → `backtest_results.warnings` (JSONB array)
  - `SimulationResult.trades` → `backtest_trades` (bulk INSERT, one row per trade)
  - `backtest_runs.status` → 'completed', `backtest_runs.completed_at` → now()

### Task 1.4: Signal loading query (scan_results → engine input)
- **File:** `backend/services/backtest_service.py` (internal method `_load_signals`)
- **Test:** `tests/backend/test_backtest_signal_loading.py`
- **CRITICAL DATA ACCESS:** `scan_results` has NO timestamp and NO `analysis_price` column. Must:
  - JOIN with `scans` table: `JOIN scans s ON sr.scan_id = s.scan_id` to get `s.started_at` (TEXT, ISO 8601) as signal timestamp
  - Parse `s.started_at::timestamptz` for chronological ordering
  - For `analysis_price`: either use migration 39's new column (if backfilled), OR parse from `report_sections` where `section='_trader_signal'` (JSON contains `entry_price` field). Fallback: use kline close price at scan time.
  - Filter: `sr.status='completed'`, `sr.direction IN ('buy','sell')` (exclude 'hold')
- **Query pattern:**
  ```sql
  SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
         s.started_at::timestamptz AS signal_time, s.scan_id
  FROM scan_results sr
  JOIN scans s ON sr.scan_id = s.scan_id
  WHERE s.schedule_id = $1 AND s.started_at::timestamptz BETWEEN $2 AND $3
    AND sr.status = 'completed' AND sr.direction IN ('buy','sell')
  ORDER BY s.started_at::timestamptz, ABS(sr.score) DESC
  ```

---

## Phase 2: Kline Cache Service

**Goal:** Fetch, store, and serve kline data with gap detection.

### Task 2.1: KlineCacheService core
- **File:** `backend/services/kline_cache_service.py`
- **Test:** `tests/backend/test_kline_cache_service.py`
- **Methods:**
  - `async get_klines(symbol, interval, start, end) -> list[dict]` — read from DB
  - `async store_klines(symbol, interval, klines: list[dict]) -> int` — bulk insert (COPY)
  - `async get_coverage_gaps(symbols, interval, start, end) -> dict[str, list[tuple]]`
  - `async ensure_coverage(symbols, interval, start, end) -> dict` — fetch missing, return stats

### Task 2.2: Bybit kline fetcher (public API, no auth)
- **File:** `backend/services/kline_cache_service.py` (internal method)
- **Test:** Integration test with mock/recorded responses
- **Endpoint:** `GET https://api.bybit.com/v5/market/kline?category=linear&symbol={}&interval={}&start={}&end={}&limit=200`
- **Response format:** `result.list` → arrays `[timestamp_ms, open, high, low, close, volume, turnover]` (7 STRING elements). **Order: DESCENDING (newest first).** Must REVERSE to ascending before storage.
- **Pagination:** End-pointer based — set `end = min_timestamp_in_batch - 1` to get older data. Max 5 pages × 200 = 1000 candles per call.
- **Rate limiting:** Use shared `asyncio.Semaphore(15)` — must NOT exceed Bybit's 120 req/5s public limit. Share budget with live scanner if running concurrently.
- **HTTP client:** Use `httpx.AsyncClient` (NOT the sync `requests.Session` from `bybit_data.py`)
- **Retry:** 3 attempts with exponential backoff (1s, 2s, 4s) on 429/5xx errors
- **Returns:** List of `{open_time: datetime, open: float, high: float, low: float, close: float, volume: float}` dicts (parsed from string arrays, reversed to ascending order)
- **`ensure_partition_exists(month)`** called BEFORE bulk INSERT for each distinct month in the fetched data

### Task 2.3: Instrument info cache
- **File:** `backend/services/kline_cache_service.py` (or separate)
- **Test:** `tests/backend/test_instrument_cache.py`
- **Data:** `qty_step, min_qty, tick_size, max_leverage` per symbol
- **Storage:** In-memory dict with 1-hour refresh from Bybit public API

---

## Phase 3: Simulation Engine (Core)

**Goal:** Pure simulation engine with all close rules.

### Task 3.1: Engine skeleton + state management
- **File:** `backend/services/backtest_engine.py`
- **Test:** `tests/backend/test_backtest_engine.py`
- **Class:** `BacktestEngine` with `run(config, signals, klines, cancel_event=None, on_progress=None) -> SimulationResult`
- **Constraint:** Engine is SYNCHRONOUS (all data pre-loaded). Runs in ThreadPoolExecutor. cancel_event is threading.Event checked every 100 candles. on_progress is Callable[[int], None] for % updates.
- **State:** `SimulationState` dataclass (wallet_balance, open_positions, equity_curve, closed_trades)

### Task 3.2: Signal processing + filter chain (Batch AND Immediate modes)
- **File:** `backend/services/backtest_engine.py`
- **Test:** Tests verifying filter chain matches AutoTradeExecutor (filter-parity test: identical input → identical output for both code paths)
- **Logic — TWO MODES (mirrors production):**
  - **Batch mode:** Collect all signals at scan time → deduplicate by ticker (keep LAST occurrence via dict overwrite, matching production) → rank deduplicated set by abs(score) desc → apply strict filter chain → select top-N up to max_trades
  - **Immediate mode:** Process signals one-at-a-time in scan order → no cross-signal dedup → first qualifying signal per symbol wins
  - **fill_to_max_trades relaxed pass:** After strict pass, if remaining slots: bypass min_score + confidence_filter, keep blacklist/sector/direction limits. Tag entries as "relaxed_fill"
- **Filter chain (17 steps — matches production `_try_trade` exactly):** status_check → ticker_validity → blacklist → whitelist → existing_position → signal_age(strict only) → hold_skip → max_same_direction → sector_limit → adaptive_blacklist → signal_sides → min_score(strict only) → confidence(strict only) → max_trades → target_goal → balance_check → price_drift
- **NOTE:** There is NO "direction" filter step — `config.direction` (straight/reverse) is used only for side determination at execution time, never for signal rejection
- **Signal age in backtest context:** `signal_age = current_simulation_time - signal.signal_time`. For normal scan processing, signals are evaluated at their generation time (age ≈ 0, filter is effectively a no-op). During `post_scan_recheck` (Task 3.9b), re-processed signals have non-zero age and the `max_signal_age_minutes` filter APPLIES — matching production behavior where rechecks happen minutes/hours after the original scan.
- **Score deduplication:** In batch mode, deduplicate by ticker keeping **LAST occurrence** (dict overwrite, matching production), THEN rank deduplicated set by abs(score) desc
- **Adaptive blacklist within backtest:** Computed from backtest's OWN completed trade history (win rate per symbol). Uses config's `adaptive_blacklist_lookback_hours` in **simulated time**: only trades with `exit_time >= current_simulation_time - lookback_hours` are counted toward per-symbol win-rate. Symbols with win_rate < `adaptive_blacklist_max_win_rate` AND trade_count >= `adaptive_blacklist_min_trades` are blacklisted for that scan event.
- **Uses:** `trading_rules.py` shared functions
- **Parity test:** Run same signals through both AutoTradeExecutor (mocked accounts) and engine, assert same accept/reject decisions for both batch and immediate modes

### Task 3.3: TP/SL evaluation (wick-based)
- **File:** `backend/services/backtest_engine.py`
- **Test:** Synthetic klines that hit TP, SL, both, gap-through
- **Logic:** Check candle H/L vs levels. Pessimistic on ambiguity.

### Task 3.4: Equity-based close rules + rule deactivation cascade
- **File:** `backend/services/backtest_engine.py`
- **Test:** Scenarios triggering RISE, DROP, SMART separately + `test_cascade_sl_triggers_equity_drop_same_candle` + `test_smart_no_losers_resets_ref` + `test_non_smart_deactivates_all_siblings`
- **EQUITY_RISE_PCT / EQUITY_DROP_PCT (non-SMART):** When triggered → close ALL positions → DEACTIVATE ALL other close rules for this cycle (trailing, breakeven, max_duration all killed). Cycle terminates.
- **EQUITY_DROP_PCT_SMART:** (a) If losing positions exist → close ONLY losers, keep other rules ACTIVE (trailing/breakeven survive). (b) If NO losers → reset reference_equity to current equity, close nothing (prevents re-trigger). (c) SMART NEVER deactivates sibling rules.
- **Intra-candle ordering:** After each TP/SL/liq close within a single candle, wallet_balance is IMMEDIATELY updated with realized PnL before equity rules evaluate. Test: Position A hits SL → wallet reduced → EQUITY_DROP fires on remaining positions → cascade close.
- **Equity computation:** `equity = wallet_balance + Σ(unrealized_pnl)` using candle.close for all open positions.

### Task 3.5: Trailing profit state machine
- **File:** `backend/services/backtest_engine.py`
- **Test:** Activation, peak tracking, trigger, reset-on-loss, peak-preservation-below-activation, stale-peak-guard
- **Full state machine (matches production `_evaluate_trailing_profit` EXACTLY):**
  1. If `upnl <= 0` → CLEAR peak entirely, skip (position underwater)
  2. Compute `profit_pct = abs(mark - entry) / entry × 100` (uses abs() for both long/short)
  3. If `profit_pct < activation_pct` → skip but DO NOT clear peak (peak preserved from prior activation)
  4. Compute `per_unit_pnl = upnl / qty`
  5. Stale-peak guard: if `stored_peak > per_unit_pnl * 100` → reset peak (data corruption safety)
  6. If `per_unit_pnl > stored_peak` → UPDATE peak (new high), continue
  7. If `per_unit_pnl < peak * 0.5` → CLOSE position at candle.close
- **Key subtlety:** Peak is ONLY cleared on `upnl <= 0`. When profitable but below activation threshold, old peak is PRESERVED — re-activation uses historical peak, not fresh one.
- **Breakeven interaction:** If BREAKEVEN_TIMEOUT fires for a position that is actively trailing → SKIP breakeven modification (trailing takes priority). Task 3.6 handles this check.
- **MFE/MAE tracking:** Per candle, update `max_favorable_price = max(prev, candle.high for long / candle.low for short)` and `max_adverse_price = min(prev, candle.low for long) / max(prev, candle.high for short)`. These feed into Task 4.1 MFE/MAE metrics.

### Task 3.6: Time-based rules (BREAKEVEN_TIMEOUT, MAX_DURATION)
- **File:** `backend/services/backtest_engine.py`
- **Test:** Time elapsed triggers, BREAKEVEN modifies TP (not close), `test_breakeven_skipped_if_trailing_active`
- **BREAKEVEN_TIMEOUT:** If elapsed >= timeout_hours → modify TP to breakeven price: `entry × (1 + 1/(leverage×100))` for Buy. **CRITICAL: If position is in active trailing state → SKIP breakeven modification (trailing takes priority), reset rule to active.** This matches production `_handle_breakeven_timeout` which checks `actively_trailing` set.
- **MAX_DURATION:** If elapsed >= max_hours → force close at candle.close (taker fee).

### Task 3.7: Liquidation check
- **File:** `backend/services/backtest_engine.py`
- **Test:** Extreme leverage + price move → liquidation fires before SL
- **Logic:** Check each candle. Liquidation overrides all. Priority: SL wins if closer.

### Task 3.8: Funding rate application
- **File:** `backend/services/backtest_engine.py`
- **Test:** Position spanning 8h boundary → funding deducted/added
- **Logic:** At 00:00/08:00/16:00 boundaries, apply to wallet_balance.
- **Data:** For Phase 1 "fixed_8h" model, use config's fixed rate. No external data needed.

### Task 3.8b: close_on_profit_pct rule
- **File:** `backend/services/backtest_engine.py`
- **Test:** Cycle PnL accumulates across positions, triggers at effective threshold, closes ALL
- **Formula:** Uses `trading_rules.check_close_on_profit(equity, cycle_start_equity, close_on_profit_pct, target_goal_value)`. Real formula: `effective_threshold = (close_on_profit_pct / 100) * target_goal_value`; triggers when `pnl_pct >= effective_threshold`
- **`target_goal_value` source:** From backtest config field `target_goal_value` (user-provided, same as AutoTradeConfig). If not set: use 100.0 as default (meaning close_on_profit_pct is used directly as the % target).
- **Behavior:** When triggered → close ALL cycle positions at candle.close → cycle ends → sizing_capital refreshes for next cycle

### Task 3.9: Cycle lock enforcement (CONDITIONAL)
- **File:** `backend/services/backtest_engine.py`
- **Test:** `test_skip_if_positions_open_true_blocks`, `test_skip_if_positions_open_false_allows_accumulation`
- **Logic:** Cycle lock is CONDITIONAL on `skip_if_positions_open` config flag:
  - When `True`: No new signals accepted while ANY position from current cycle is open. Scan signals at that time are skipped entirely.
  - When `False` (default): New positions CAN be opened alongside existing ones. Each scan can add more positions up to max_trades.
- **CRITICAL:** Do NOT assume universal cycle lock. Most configs have `skip_if_positions_open=False` — they accumulate positions across multiple scans.
- **Sizing capital refresh (matches production `init_balances` per-scan call):**
  - When `skip_if_positions_open=True`: `sizing_capital` refreshes to current `wallet_balance` when ALL positions close and a new cycle begins.
  - When `skip_if_positions_open=False` (DEFAULT): `sizing_capital` refreshes to current `wallet_balance` (= starting_capital + Σ realized_pnl − Σ fees) at EVERY SCAN EVENT, regardless of open positions. This matches production's per-scan `init_balances()` which re-fetches wallet balance.
  - In both cases: `wallet_balance` = initial_capital + cumulative realized PnL − cumulative fees paid.

### Task 3.9b: post_scan_recheck simulation
- **File:** `backend/services/backtest_engine.py`
- **Test:** `test_recheck_reopens_after_mid_scan_close`, `test_recheck_close_on_profit_retrades`
- **Logic (matches production `post_scan_recheck`):**
  1. After processing a scan's signals + some time passes (during candle iteration to next scan):
  2. If a position closes between scans AND `skip_if_positions_open=True` was blocking → re-process current scan's remaining signals (strict + fill pass) with refreshed capital
  3. If `close_on_profit_pct` threshold was reached → force-close all positions → recreate rules → re-trade from current scan signals
  4. Max recheck iterations per scan: 3 (prevents infinite loops)

### Task 3.10: Multi-scan time stepping + end-of-backtest handling
- **File:** `backend/services/backtest_engine.py`
- **Test:** 5+ consecutive scans, verify correct chronological processing + force-close at end
- **Logic:**
  - Build scan timeline from signal timestamps, iterate candles between scans, process signals at scan times
  - **Force-close at backtest end:** When last candle reached, close ALL open positions at candle.close with close_reason="BACKTEST_END", taker fee
  - **Kline gap handling:** Forward-fill ≤3 missing candles (synthetic=true), skip evaluation for >24h gaps (no TP/SL trigger on synthetic), log warning
  - **Symbol delisting mid-position:** If kline data ends while position open → force-close at last available price, close_reason="DATA_UNAVAILABLE", log warning
  - **BacktestTimeout vs BacktestCancelled:** Engine checks `cancel_event.is_set()` per 100 candles. Service layer sets a flag `_timed_out=True` before Timer fires cancel_event. Engine raises `BacktestCancelled`; service re-raises as `BacktestTimeout` if flag was set.
- **Tests:** `test_consecutive_scans_chronological`, `test_force_close_at_end`, `test_gap_handling_forward_fill`, `test_delisted_symbol_midposition`

---

## Phase 4: Metrics Computation

**Goal:** Compute all TradingView-parity metrics from trade list + equity curve.

### Task 4.1: Core metrics module
- **File:** `backend/services/backtest_metrics.py`
- **Test:** `tests/backend/test_backtest_metrics.py`
- **Functions:**
  - `compute_all_metrics(trades, equity_curve, config) -> dict` — returns ALL metrics below
  - `compute_sharpe(daily_returns) -> float | None` (√365 annualized, None if <2 data points)
  - `compute_sortino(daily_returns) -> float | None` (√365 annualized; None if <2 data points OR no downside periods — undefined deviation, consistent with profit_factor's no-loss → None)
  - `compute_max_drawdown(equity_curve) -> dict` ({max_dd_pct, max_dd_$, max_dd_duration_hours, avg_dd_pct})
  - `compute_streaks(trades) -> dict` (max_consecutive_wins/losses, count + $ amounts)
  - `compute_per_trade_series(trades) -> list[dict]` (per-trade detail: pnl, cumulative_pnl, MFE/MAE, close_reason, times — consolidates the per-trade MFE/MAE requirement into one series rather than a separate `compute_mfe_mae`, avoiding a near-duplicate function)
  - `compute_run_up(equity_curve) -> dict` ({max_run_up_pct, max_run_up_usd}) — mirror of drawdown
  - `compute_durations(trades) -> dict` (avg/winner/loser/max trade duration in hours)
  - `split_by_direction(trades) -> dict` (All/Long/Short columns for the core P&L subset: total/winners/losers, net_profit, win_rate, avg_trade, avg_win, avg_loss — per-direction Sharpe/Sortino/drawdown are out of scope as they require per-direction equity curves the engine does not track)
- **Full metrics list (must all be in output):**
  - Net profit ($ and %), gross profit, gross loss, profit factor, recovery factor
  - CAGR, Calmar ratio, expectancy ($), total commission paid
  - Win rate %, avg winning trade, avg losing trade, ratio avg win/avg loss
  - Largest winning/losing trade, total trades, winners, losers
  - Avg trade duration, avg winner duration, avg loser duration, max trade duration
  - Max consecutive wins/losses (count and $), max run-up
  - Max drawdown ($ and %), avg drawdown %, max drawdown duration
  - Cumulative PnL per trade, MFE/MAE per trade
- **Edge case tests:** `test_zero_trades` (all ratios=None, equity=flat), `test_one_trade` (Sharpe=None), `test_all_wins` (profit_factor=None — no losses → "∞"/"N/A" in UI; JSONB-safe), `test_all_losses`

### Task 4.2: Buy & Hold benchmark
- **File:** `backend/services/backtest_metrics.py`
- **Test:** Compare against known BTC price series
- **Logic:** Fetch BTC kline for backtest period, compute hold return.

---

## Phase 5: Backend Service + API

**Goal:** Orchestration service, REST endpoints, background execution.

### Task 5.1: BacktestService orchestrator
- **File:** `backend/services/backtest_service.py`
- **Test:** `tests/backend/test_backtest_service.py`
- **Methods:**
  - `async create_backtest(config) -> str` (returns run_id)
  - `async get_backtest(run_id) -> dict` (includes LTTB-downsampled equity via `trading_rules.lttb_downsample`)
  - `async list_backtests(filters) -> list`
  - `async cancel_backtest(run_id) -> bool`
  - `async delete_backtest(run_id) -> bool` (cascade delete, reject if running)
  - `async compare_backtests(run_ids: list[str]) -> dict` (validate 2-4 IDs, all completed)
  - `async _load_signals(scan_source: ScanSource, date_range) -> list[dict]` — 3-mode dispatch (by schedule_id, date_range, explicit scan_ids)

### Task 5.2: Background execution with ThreadPoolExecutor
- **File:** `backend/services/backtest_service.py`
- **Test:** `tests/backend/test_backtest_execution.py`
- **Logic:** `await loop.run_in_executor(thread_pool, engine.run, ...)` (bounded ThreadPoolExecutor(3))
- **Cancellation:** `threading.Event` passed to engine, checked per 100 candles → `BacktestCancelled`
- **Timeout:** `threading.Timer(120, cancel_event.set)` auto-fires → `BacktestTimeout` (distinct from user cancel)
- **Progress:** Engine calls `on_progress(pct)` → asyncio Queue → service updates DB `progress_pct`
- **Memory validation:** Pre-compute `date_range_days × 288`. Reject >105,120 candles with 422.
- **Semaphore:** `asyncio.Semaphore(3)` — return 503 if full
- **Startup recovery:** On service init: `UPDATE backtest_runs SET status='failed' WHERE status IN ('running','pending')`
- **Tests:** `test_cancel_within_200_candles`, `test_timeout_at_120s`, `test_semaphore_rejects_4th`, `test_memory_reject_large`, `test_startup_recovery_marks_stale`

### Task 5.3: REST API router
- **File:** `backend/routers/backtest.py`
- **Test:** `tests/backend/test_backtest_router.py`
- **Endpoints:** POST create (201/422/429/503), GET list (200), GET {id} (200/404), GET {id}/trades (200/404, paginated: page/limit/sort_by/side/close_reason), POST {id}/cancel (200/404/409), DELETE {id} (204/404/409), GET compare (200/404/422), POST warmup-cache (202), GET cache-status (200)
- **Status codes:** 429 if rate limit exceeded (per-user: in-memory sliding window, 10 creates/hour), 503 if semaphore full (global 3 slots)
- **Paginated trades:** `get_backtest_trades(run_id, page, limit, sort_by, side?, close_reason?) -> {trades, total, page}`
- **Error handling in _load_signals:** If >20% of required symbols have no kline data → return 422 with descriptive message. Otherwise proceed with available data + warnings in results.

### Task 5.4: Wire into main.py
- **File:** `backend/main.py`
- **Test:** Smoke test via TestClient (assert router registered, DI resolves)
- **Logic:** Create KlineCacheService + BacktestService on startup, register router, add shutdown hook for running tasks

---

## Phase 6: Frontend

**Goal:** Complete backtest UI with config form, results dashboard, comparison.

### Task 6.1: API client namespace + TypeScript types
- **File:** `frontend/src/api/client.ts`
- **Add:** `backtestApi` namespace with all endpoint methods
- **Types:** `BacktestRun`, `BacktestResults`, `BacktestTrade`, `BacktestCompareResponse`, `BacktestCreateRequest`

### Task 6.2: Route definitions + polling hook
- **File:** `frontend/src/routes/` (route-tree)
- **Routes:** `/backtest` (list), `/backtest/new` (config), `/backtest/$runId` (results), `/backtest/compare` (comparison page)
- **Hook:** `useBacktestPolling(runId)` — TanStack Query with `refetchInterval: 2000` while running, `false` on terminal

### Task 6.3: Config form page
- **File:** `frontend/src/components/backtest/BacktestConfigForm.tsx`
- **Test:** `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx`
- **Sections:** Capital & Range, Signal Filtering, Trade Sizing, Close Rules (collapsible)
- **Quick mode fields (7):** starting_capital, date_range_start, date_range_end, scan_source (schedule picker), leverage, take_profit_pct, stop_loss_pct
- **Advanced toggle:** reveals 4 collapsible sections with remaining ~30 fields
- **Preset save/load:** localStorage, import/export JSON
- **UX:** Navigation guard (`useBlocker` on dirty), validation preview, `beforeunload`

### Task 6.4: Results dashboard
- **File:** `frontend/src/components/backtest/BacktestResultsPage.tsx`
- **Test:** `frontend/src/components/backtest/__tests__/BacktestResultsPage.test.tsx`
- **Tabs:** Overview, Equity Curve, Trade List, Analysis
- **Features:** Sticky header (4 hero metrics), tabbed navigation, cancel button + confirmation dialog
- **UX States:** Loading (skeleton + progress bar), Running (cancel button + live %), Completed (full dashboard), Failed (error card + Retry), Cancelled (partial + Re-run)
- **Polling:** Uses `useBacktestPolling` hook. Toast on completion when navigated away.
- **"Add to comparison":** Secondary action button → adds run_id to sessionStorage basket (max 4). Shows badge count if basket non-empty.

### Task 6.5: Equity curve chart
- **File:** `frontend/src/components/backtest/EquityCurveChart.tsx`
- **Test:** `frontend/src/components/backtest/__tests__/EquityCurveChart.test.tsx`
- **Features:** Area chart + drawdown overlay + Buy&Hold line, crosshair, zoom
- **Props:** `datasets: Array<{label, data, color}>` for single + comparison reuse

### Task 6.5b: Analysis tab charts
- **File:** `frontend/src/components/backtest/BacktestAnalysisTab.tsx`
- **Test:** `frontend/src/components/backtest/__tests__/BacktestAnalysisTab.test.tsx`
- **Components:**
  - Monthly returns heatmap (calendar grid, green/red cells, row totals)
  - P&L distribution histogram (bucketed trade PnL, normal curve overlay, zero-line)
  - Trade duration distribution (histogram, color-coded win/loss)
- **Data aggregation:** Group trades by month for heatmap; bucket PnL values for histogram
- **Recharts:** BarChart for histograms, custom grid for heatmap

### Task 6.6: Metrics grid
- **File:** `frontend/src/components/backtest/MetricsGrid.tsx`
- **Features:** Responsive grid (4→2→1 col), All/Long/Short columns, color indicators

### Task 6.7: Trade list table
- **File:** `frontend/src/components/backtest/TradeListTable.tsx`
- **Features:** Sortable, filterable, paginated, CSV export, cumulative PnL column

### Task 6.8: Run history + comparison
- **File:** `frontend/src/components/backtest/BacktestListPage.tsx` + `BacktestComparePage.tsx`
- **Test:** `frontend/src/components/backtest/__tests__/BacktestListPage.test.tsx`
- **List features:** History table, multi-select checkboxes (max 4), "Compare Selected" button, DELETE button + confirm
- **Empty state:** "No backtests yet" + CTA to create
- **Comparison page** (`/backtest/compare?ids=...`):
  - Overlaid equity curves (color-coded per run, shared x-axis)
  - Metric diff table: each metric row shows all runs + green/red delta highlighting
  - Uses `GET /backtests/compare?ids=` API
  - Reads sessionStorage basket (populated from Task 6.4 "Add to comparison") OR URL params
  - Max 4 runs enforced in both UI selection and API validation

---

## Phase 7: Integration & Polish

### Task 7.1: "Backtest These Settings" entry from Scanner
- **Files:** `ScanDetailPage.tsx`, `ScheduledScansPage.tsx`
- **Logic:** Button navigates to /backtest/new with pre-filled config

### Task 7.2: Golden-set validation tests
- **File:** `tests/backend/test_backtest_golden.py`
- **Logic:** 5+ frozen scenarios with expected outputs, CI fails on >0.1% deviation

### Task 7.3: Performance benchmarks
- **File:** `tests/backend/test_backtest_performance.py`
- **Assertion:** 30-day backtest < 3 seconds on warm cache (matching AC-001)

### Task 7.4: Navigation integration
- **Files:** Layout header, mobile dock, route-tree
- **Logic:** Add "Backtesting" nav item between Analytics and Strategies

---

## Dependency Graph

```
Phase 1 (Foundation) ──┬──► Phase 2 (Kline Cache)
                       │
                       └──► Phase 3 (Engine) ──► Phase 4 (Metrics)
                                                       │
Phase 2 + Phase 4 ────────────────────────────────► Phase 5 (API)
                                                       │
Phase 5 ──────────────────────────────────────────► Phase 6 (Frontend)
                                                       │
Phase 6 ──────────────────────────────────────────► Phase 7 (Integration)
```

Phases 2 and 3 can run in parallel after Phase 1 completes.
