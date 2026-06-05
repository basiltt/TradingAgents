# Backtesting System — Codebase Discovery Summary

## 1. Architecture Overview

The TradingAgents platform is a FastAPI + React app with this trading flow:

```
Scheduled Scan → Symbol Analysis (LLM) → Scan Results (signals)
    → AutoTradeExecutor (filter + place trades)
    → CloseRuleEvaluator (monitor + close positions)
    → Cycle Complete
```

**The backtesting system replicates this entire flow using historical data instead of live APIs.**

---

## 2. Key Components to Replicate

### 2.1 Signal Source — Scan Results (DB)

Table: `scan_results`
```
id | scan_id | ticker | status | direction | confidence | score | decision_summary | signal_source
```

- Score: -10 to +10 (positive=buy, negative=sell, 0=hold)
- Confidence: high/moderate/low/none
- Status: completed/failed/cancelled/unknown
- Signal source: structured/regex_fallback/ta_prefilter/none

Scans table has: `started_at`, `completed_at`, `config` (JSON with auto_trade_configs)

### 2.2 AutoTradeExecutor Filter Chain (19 checks)

1. Status == "completed"
2. Direction extraction (buy/sell/hold)
3. Ticker validity
4. Symbol blacklist
5. Symbol whitelist (if set, must be in it)
6. Existing position (no duplicates)
7. Signal age (max_signal_age_minutes, strict only)
8. Hold direction (skip holds)
9. Max same direction
10. Sector concentration (max_same_sector)
11. Adaptive blacklist
12. Signal sides filter (buy/sell/both)
13. Min score (strict only)
14. Confidence filter (strict only)
15. Max trades limit
16. Target goal (trade_count type)
17. Balance check (> 0)
18. Price drift validation (mark vs analysis_price)

All checks pass → execute trade.

### 2.3 Close Rule Types

| Rule | What It Does | Parameters |
|------|-------------|------------|
| EQUITY_RISE_PCT | Close ALL when equity rises X% | threshold_value (%), reference_value (starting equity) |
| EQUITY_DROP_PCT | Close ALL when equity drops X% | threshold_value (%), reference_value (starting equity) |
| EQUITY_DROP_PCT_SMART | Close only LOSING positions | Same as above, reference resets |
| BREAKEVEN_TIMEOUT | Move TP to ~breakeven after X hours | threshold_value (hours), reference_value (ISO datetime) |
| MAX_DURATION | Close ALL after X hours | threshold_value (hours), reference_value (ISO datetime) |
| TRAILING_PROFIT | Per-position trailing stop | threshold_value (activation %), 50% trail ratio |

### 2.4 Trade Execution Formulas

```python
# Side determination
side = "Buy" if (signal=="buy" AND direction=="straight") OR (signal=="sell" AND direction=="reverse")

# Position sizing
margin = base_capital * capital_pct / 100
qty = (margin * leverage) / entry_price

# TP/SL prices
price_move_pct = pct_value / leverage / 100
tp_price = entry * (1 + price_move_pct) if long else entry * (1 - price_move_pct)
sl_price = entry * (1 - price_move_pct) if long else entry * (1 + price_move_pct)

# PnL
unrealized_pnl = (current - entry) * qty if long else (entry - current) * qty
equity = wallet_balance + sum(all_unrealized_pnl)
```

### 2.5 Trailing Profit State Machine

```
INACTIVE → profit_pct >= activation_pct → TRACKING (update peak)
TRACKING → per_unit_pnl > peak → UPDATE PEAK
TRACKING → per_unit_pnl < peak * 0.5 → CLOSE POSITION
TRACKING → upnl <= 0 → INACTIVE (clear peak)
```

### 2.6 Cycle Enforcement

- `skip_if_positions_open`: No new trades if positions exist
- After cycle-level close rule triggers → ALL rules deactivated, cycle ends
- Only ONE active cycle per account at a time (DB constraint)
- `post_scan_recheck`: Re-evaluates if conditions changed during scan

---

## 3. Data Gaps for Backtesting

| Need | Current State | Solution |
|------|--------------|----------|
| Historical kline data | Fetched live from Bybit, 5-min TTL cache | New persistent cache (DB table or file) |
| Fast price lookup | Rate-limited API (18 req/s) | In-memory DataFrame during simulation |
| No API calls during sim | All paths hit Bybit REST | Pure computation engine |
| Repeated runs same data | No persistence | Cache survives across runs |

**Bybit Kline API:**
- Endpoint: `GET /v5/market/kline`
- Max 200 candles/page, 5 pages/call = 1000 candles
- Intervals: 1, 5, 15, 30, 60, 120, 240, D, W
- Paginated by time (oldest→newest or newest→oldest)

---

## 4. Frontend Patterns

| Aspect | Pattern |
|--------|---------|
| Routing | TanStack Router, lazy imports, RouteSuspense |
| Data fetching | TanStack Query (useQuery/useMutation) |
| API client | Namespace objects in client.ts |
| Charts | Recharts (AreaChart, BarChart) + ResponsiveContainer |
| Design | Neumorphic design system + shadcn/ui primitives |
| State | Local useState + TanStack Query cache |
| Installed | recharts, framer-motion, lucide-react, tailwindcss 4, shadcn |

---

## 5. AutoTradeConfig — Complete Parameter List (40+ fields)

### Trade Execution
- account_id, direction (straight/reverse), leverage, capital_pct
- take_profit_pct, stop_loss_pct, execution_mode (immediate/batch)

### Signal Filtering
- min_score, confidence_filter, signal_sides
- symbol_blacklist, symbol_whitelist
- max_signal_age_minutes, max_price_drift_pct

### Trade Limits
- max_trades, fill_to_max_trades
- target_goal_type, target_goal_value

### Position Constraints
- skip_if_positions_open
- max_same_direction, max_same_sector

### Close Rules
- max_drawdown_pct, smart_drawdown_close
- breakeven_timeout_hours, max_trade_duration_hours
- trailing_profit_pct, close_on_profit_pct

### Adaptive Blacklist
- adaptive_blacklist_enabled, adaptive_blacklist_min_trades
- adaptive_blacklist_max_win_rate, adaptive_blacklist_lookback_hours

### AI (excluded from backtest)
- ai_manager_enabled, ai_pause_cycles

---

## 6. Existing Scan Data Available

From `scans` table joined with `scan_results`:
- Historical scans: timestamps, configs, all ticker results
- Per-result: ticker, direction, confidence, score
- Scheduled scan configs: recurring configs with auto_trade_configs embedded
- ~570+ symbols scanned per run
- Multiple scans per day (scheduled intervals)

This provides the SIGNAL SOURCE for backtesting — no re-analysis needed.

---

## 7. Impact Areas

| Area | Impact |
|------|--------|
| Backend | New service (backtest engine), new router, new DB tables (kline cache, backtest results) |
| Frontend | New route + components (config form, results dashboard, charts) |
| Database | New tables: kline_cache, backtest_runs, backtest_trades |
| Existing code | Zero modifications to existing services (pure simulation) |
