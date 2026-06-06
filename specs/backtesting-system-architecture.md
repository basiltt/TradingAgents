# Backtesting System — Architecture Document

## 1. System Context

The backtesting system is a new subsystem within the existing TradingAgents platform. It operates entirely independently from the live trading path — no shared state, no API calls to exchanges during simulation, no account credentials.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TradingAgents Platform                         │
├─────────────────┬───────────────────────┬───────────────────────┤
│  Live Trading   │   Market Scanner      │   BACKTESTING (NEW)   │
│  - accounts_svc │   - scanner_svc       │   - backtest_svc      │
│  - close_rules  │   - auto_trade_svc    │   - sim_engine        │
│  - positions    │   - regime_classifier │   - kline_cache_svc   │
│                 │                       │   - results_store     │
└────────┬────────┴───────────┬───────────┴───────────┬───────────┘
         │                    │                       │
         │                    │  reads scan_results   │
         │                    ├───────────────────────┤
         │                    │                       │
    Bybit API            PostgreSQL              Bybit Public API
    (authenticated)      (shared DB)             (unauthenticated)
```

**Key architectural principle:** The backtesting system READS from the same database (scan results, scheduled configs) but WRITES to its own tables only. No mutations to live trading tables.

---

## 2. Component Architecture

### 2.1 Backend Components

```
backend/
├── services/
│   ├── backtest_service.py       # Orchestration: lifecycle management
│   ├── backtest_engine.py        # Pure simulation engine (stateless)
│   ├── kline_cache_service.py    # Kline data fetch + cache management
│   └── backtest_metrics.py       # Metrics computation (stateless)
├── routers/
│   └── backtest.py               # REST API endpoints
└── schemas/
    └── backtest_schemas.py       # Pydantic models (request/response)
```

| Component | Responsibility | Dependencies |
|-----------|---------------|--------------|
| `BacktestService` | Lifecycle: create, run, cancel, list, compare | DB, KlineCacheService, BacktestEngine |
| `BacktestEngine` | Pure simulation loop. Zero I/O. | None (all data injected) |
| `KlineCacheService` | Fetch, cache, gap-detect kline data | DB, Bybit public API |
| `BacktestMetrics` | Compute all metrics from trade list + equity | None (pure functions) |
| `BacktestRouter` | HTTP endpoints | BacktestService |

### 2.2 Frontend Components

```
frontend/src/
├── components/backtest/
│   ├── BacktestConfigForm.tsx    # Configuration form
│   ├── BacktestResultsPage.tsx   # Results dashboard (tabbed)
│   ├── BacktestListPage.tsx      # Run history
│   ├── EquityCurveChart.tsx      # Interactive equity + drawdown
│   ├── TradeListTable.tsx        # Sortable/filterable trade list
│   ├── MetricsGrid.tsx           # Performance metrics grid
│   ├── MonthlyHeatmap.tsx        # Monthly returns heatmap
│   └── ComparisonView.tsx        # Side-by-side comparison
├── routes/
│   └── (route definitions for /backtest/*)
└── api/
    └── client.ts                 # backtestApi namespace added
```

---

## 3. Data Architecture

### 3.1 Database Tables (New)

```sql
-- Kline price data cache
CREATE TABLE kline_cache (
    symbol       TEXT NOT NULL,
    interval     TEXT NOT NULL,
    open_time    TIMESTAMPTZ NOT NULL,
    open         DOUBLE PRECISION NOT NULL,
    high         DOUBLE PRECISION NOT NULL,
    low          DOUBLE PRECISION NOT NULL,
    close        DOUBLE PRECISION NOT NULL,
    volume       DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, open_time)
) PARTITION BY RANGE (open_time);

-- Coverage tracking for fast gap detection
CREATE TABLE kline_cache_coverage (
    symbol       TEXT NOT NULL,
    interval     TEXT NOT NULL,
    date         DATE NOT NULL,
    candle_count SMALLINT NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, interval, date)
);

-- Backtest run metadata
CREATE TABLE backtest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','completed','failed','cancelled')),
    config          JSONB NOT NULL,
    scan_source     JSONB NOT NULL,       -- {mode, schedule_id?, scan_ids?, date_range}
    progress_pct    SMALLINT NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backtest results (1:1 with runs)
CREATE TABLE backtest_results (
    run_id          UUID PRIMARY KEY REFERENCES backtest_runs(id) ON DELETE CASCADE,
    metrics         JSONB NOT NULL,       -- All computed metrics
    equity_curve    JSONB NOT NULL,       -- [{ts, equity, drawdown_pct}]
    summary         JSONB NOT NULL,       -- Quick summary for list view
    warnings        JSONB DEFAULT '[]'
);

-- Individual simulated trades
CREATE TABLE backtest_trades (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('Buy','Sell')),
    entry_price     NUMERIC(20,8) NOT NULL,
    exit_price      NUMERIC(20,8),
    qty             NUMERIC(20,8) NOT NULL,
    leverage        SMALLINT NOT NULL,
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    pnl             NUMERIC(20,8),
    pnl_pct         NUMERIC(8,4),
    fees_paid       NUMERIC(20,8),
    close_reason    TEXT,
    mfe_pct         NUMERIC(8,4),         -- Max Favorable Excursion
    mae_pct         NUMERIC(8,4),         -- Max Adverse Excursion
    signal_score    SMALLINT,
    signal_confidence TEXT,
    scan_id         TEXT,
    metadata        JSONB DEFAULT '{}'
);
CREATE INDEX idx_backtest_trades_run ON backtest_trades(run_id);
```

### 3.2 Data Flow

```
1. User submits config
   └─► BacktestService.create() → save to backtest_runs (status=pending)

2. Execution starts (asyncio.Task)
   ├─► Load scan results from scan_results table (date range + source filter)
   ├─► KlineCacheService.ensure_coverage(symbols, interval, date_range)
   │   ├─► Check kline_cache_coverage for gaps
   │   ├─► Fetch missing data from Bybit public API
   │   └─► Insert into kline_cache + update coverage
   ├─► Load kline data into memory (pandas DataFrame per symbol)
   └─► BacktestEngine.run(config, signals, klines)
       ├─► Time-step loop (candle by candle)
       │   ├─► At scan timestamps: apply filter chain, open positions
       │   ├─► Each candle: evaluate close rules for open positions
       │   ├─► Track equity, drawdown, peak at each step
       │   └─► On close: record trade, update state
       └─► Return: trades[], equity_curve[], raw_metrics

3. Post-processing
   ├─► BacktestMetrics.compute(trades, equity_curve, config)
   ├─► Save to backtest_results + backtest_trades
   └─► Update backtest_runs (status=completed, completed_at)
```

---

## 4. Simulation Engine Architecture

### 4.1 Core Loop (event-driven time stepping)

```python
class BacktestEngine:
    """Pure simulation engine. Zero I/O. All data injected."""

    def run(self, config: BacktestConfig, 
            scan_signals: list[ScanSignal],
            klines: dict[str, pd.DataFrame]) -> SimulationResult:
        """
        Args:
            config: All backtest parameters
            scan_signals: Chronological list of signals with timestamps
            klines: {symbol: DataFrame[open_time, O, H, L, C, V]}
        Returns:
            SimulationResult with trades, equity_curve, raw metrics
        """
```

### 4.2 State Management (Struct-of-Arrays)

```python
@dataclass
class SimulationState:
    # Portfolio state
    wallet_balance: Decimal          # Cash (initial + realized PnL - fees)
    
    # Open positions (parallel arrays for vectorized ops)
    position_symbols: list[str]
    position_sides: list[str]        # "Buy" / "Sell"
    position_entries: np.ndarray     # float64 entry prices
    position_sizes: np.ndarray       # float64 quantities
    position_leverages: np.ndarray   # int leverages
    position_tp_prices: np.ndarray   # float64 TP levels
    position_sl_prices: np.ndarray   # float64 SL levels
    position_entry_times: list[datetime]
    position_trailing_peaks: np.ndarray  # float64 for trailing profit
    position_trailing_active: np.ndarray # bool: trailing activated?
    
    # Cycle state
    cycle_active: bool
    cycle_reference_equity: Decimal  # For EQUITY_RISE/DROP rules
    cycle_start_time: datetime
    
    # Tracking
    closed_trades: list[SimulatedTrade]
    equity_curve: list[EquityPoint]
    signals_processed: int
    signals_filtered: int
```

### 4.3 Per-Candle Evaluation Order

```
For each candle timestamp T:
  1. FUNDING: If T contains an 8-hour boundary (candle.open < funding_time <= candle.close)
     → Apply funding_payment = position_value × funding_rate to wallet_balance
  2. LIQUIDATION: Check candle extreme vs liquidation prices
     → Long: if candle.low <= liq_price → force-close at liq_price
     → Short: if candle.high >= liq_price → force-close at liq_price
  3. TP/SL ON WICKS: Check candle H/L vs TP/SL levels
     → Long TP: candle.high >= tp_price → close at tp_price (maker fee)
     → Long SL: candle.low <= sl_price → close at sl_price (taker fee)
     → Short TP: candle.low <= tp_price → close at tp_price (maker fee)
     → Short SL: candle.high >= sl_price → close at sl_price (taker fee)
     → AMBIGUITY: If both TP and SL breached on same candle → pessimistic (SL wins)
  4. EQUITY RULES: Compute equity using candle CLOSE prices for unrealized PnL
     → EQUITY_RISE_PCT: (equity - reference) / reference × 100 >= threshold → close ALL
     → EQUITY_DROP_PCT: (reference - equity) / reference × 100 >= threshold → close ALL
     → EQUITY_DROP_PCT_SMART: same check but close only LOSING positions, then reset reference
  5. TRAILING PROFIT: For each position with trailing_profit enabled:
     → profit_pct = abs(close - entry) / entry × 100
     → If upnl <= 0: clear peak, skip
     → If profit_pct < activation_pct: skip (don't clear existing peak)
     → Compute per_unit_pnl = unrealized_pnl / qty
     → If per_unit_pnl > stored_peak: update peak (new high)
     → If per_unit_pnl < peak × 0.5: CLOSE at candle.close (taker fee)
  6. TIME RULES:
     → BREAKEVEN_TIMEOUT: If elapsed >= timeout_hours AND max_profit_pct < 0.5%
       → MODIFY TP to entry × (1 ± 1%/leverage) — does NOT close position
     → MAX_DURATION: If elapsed >= max_hours → CLOSE at candle.close
  7. CYCLE STATE: After all closes processed:
     → Recalculate available_capital = wallet_balance - sum(position_margins)
     → If ALL positions in cycle closed → set cycle_active = False
  8. SIGNALS: If cycle_active == False AND scan signal exists at time T:
     → Apply full filter chain (18 steps from AutoTradeExecutor)
     → Entry price = candle.close × (1 ± slippage_bps/10000)
     → Open positions, set cycle_active = True, set cycle_reference_equity
  9. EQUITY CURVE: Record {T, equity, drawdown_pct, open_positions_count}
```

**Key correctness notes:**
- New positions at step 8 are first evaluated for TP/SL at the NEXT candle (T+1)
- BREAKEVEN_TIMEOUT modifies TP (does NOT close) — only MAX_DURATION force-closes
- SMART drawdown: if triggered but no losers, reference resets to current equity
- Trailing peak uses candle HIGH (long) / LOW (short) for peak tracking, CLOSE for trigger check
- All equity calculations at step 4 use CLOSE price (not wick extremes)

---

## 5. API Design

### 5.1 Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/backtests` | Create + start backtest |
| GET | `/api/v1/backtests` | List runs (paginated, sortable) |
| GET | `/api/v1/backtests/{id}` | Get run status + results |
| POST | `/api/v1/backtests/{id}/cancel` | Cancel running backtest |
| GET | `/api/v1/backtests/compare` | Compare 2-4 runs |
| POST | `/api/v1/backtests/warmup-cache` | Pre-fetch klines |
| GET | `/api/v1/backtests/cache-status` | Kline cache coverage |

### 5.2 Request Schema

```python
class BacktestCreateRequest(BaseModel):
    # Backtest-specific
    starting_capital: Decimal                    # Required
    date_range_start: datetime                   # Required
    date_range_end: datetime                     # Required
    scan_source: ScanSource                      # Required
    simulation_interval: str = "5m"              # Kline resolution
    fee_rate_pct: Decimal = Decimal("0.055")
    slippage_bps: int = 2
    funding_rate_model: Literal["none","fixed_8h"] = "none"
    funding_rate_fixed_pct: Decimal = Decimal("0.01")
    
    # From AutoTradeConfig (all trade decision params)
    direction: Literal["straight","reverse"] = "straight"
    leverage: int = 20
    capital_pct: float = 5.0
    take_profit_pct: float = 150.0
    stop_loss_pct: float = 100.0
    min_score: float = 0.0
    confidence_filter: str = "any"
    signal_sides: str = "both"
    max_trades: int = 999
    execution_mode: str = "batch"
    fill_to_max_trades: bool = False
    skip_if_positions_open: bool = False
    max_same_direction: Optional[int] = None
    max_same_sector: Optional[int] = None
    symbol_blacklist: Optional[list[str]] = None
    symbol_whitelist: Optional[list[str]] = None
    
    # Close rules
    max_drawdown_pct: float = 100.0
    smart_drawdown_close: bool = False
    breakeven_timeout_hours: Optional[float] = None
    max_trade_duration_hours: Optional[float] = None
    trailing_profit_pct: Optional[float] = None
    close_on_profit_pct: Optional[float] = None
    
    # Adaptive blacklist
    adaptive_blacklist_enabled: bool = False
    adaptive_blacklist_min_trades: int = 5
    adaptive_blacklist_max_win_rate: float = 30.0
```

---

## 6. Performance Strategy

### 6.1 Speed Targets

| Operation | Target | Strategy |
|-----------|--------|----------|
| Single 30-day backtest (warm cache) | <3s | In-memory numpy, sparse simulation |
| Single 30-day backtest (cold cache) | <60s | Fetch klines first, then simulate |
| Kline cache warm (full universe) | <6min | 15 concurrent fetches, 18 req/s |
| Results API response | <100ms | JSONB + gzip |

### 6.2 Memory Strategy

- Load only symbols that fire signals (typically 50-150 out of 570)
- Per-symbol DataFrame: 8640 candles × 6 cols × 8 bytes = ~415KB per symbol
- 150 symbols = ~62MB of kline data in memory
- Position state: negligible (max ~20 concurrent positions)
- Equity curve: ~8640 points × 24 bytes = ~200KB
- Total per-backtest memory: <100MB

### 6.3 Kline Cache Strategy

```
Request arrives → Check coverage → Fetch gaps → Load to memory → Simulate

Coverage table (O(1) lookup):
  kline_cache_coverage: (symbol, interval, date) → candle_count

Gap detection:
  - Expected: 288 candles/day for 5m interval
  - If candle_count < 288: partial, need delta fetch
  - If row missing: full fetch needed for that day

Fetch strategy:
  - asyncio.Semaphore(15) for concurrent Bybit requests
  - 200 candles per page, 5 pages per call = 1000 max
  - Prioritize symbols from scan results first
```

---

## 7. Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Kline storage | PostgreSQL (DOUBLE PRECISION) | Consistent with existing stack. Fast asyncpg float reads. |
| Price arrays | numpy float64 | Sufficient precision. No Decimal conversion tax. |
| PnL calculation | float64 in hot loop, Decimal at trade close | Speed in loop, accuracy at boundaries. |
| Simulation execution | `run_in_executor(ThreadPoolExecutor)` + `threading.Event` cancel | Numpy releases GIL; thread allows cooperative cancellation. |
| Frontend charts | Recharts | Already installed. Sufficient for equity curves. |
| Background execution | asyncio.Task + executor + semaphore(3) | Bounded concurrency, responsive cancellation. |
| Result storage | JSONB metrics + normalized trades | Queryable for comparison, exportable. |
| API format | REST with conditional polling | TanStack Query refetchInterval pattern. |
| Close rule logic | Shared `trading_rules.py` module | One source of truth for both live + backtest. |
| Kline DB columns | DOUBLE PRECISION (not NUMERIC) | Native float return from asyncpg, no conversion. |

---

## 8. Integration Points

| Integration | Direction | Mechanism |
|-------------|-----------|-----------|
| Scan results | READ | SQL query on `scan_results` + `scans` tables |
| Scheduled scan configs | READ | SQL query on `scheduled_scans.scan_config` |
| Kline data (Bybit) | READ | Public REST API (no auth needed) |
| Existing close rule logic | REPLICATE | Port logic from `close_rule_evaluator.py` to engine |
| Existing filter chain | REPLICATE | Port logic from `auto_trade_service.py` to engine |
| Frontend router | EXTEND | Add `/backtest/*` routes |
| Frontend API client | EXTEND | Add `backtestApi` namespace |
| Database migrations | EXTEND | New entries in `_MIGRATIONS` list |

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Close rule logic diverges from production | Inaccurate results | Shared `trading_rules.py` module; CI golden-set tests |
| Kline data quality (gaps, errors) | Simulation errors | Coverage checks + forward-fill + warnings |
| Memory pressure with many symbols | OOM | Budget check before start, lazy loading, max 100MB/run |
| Bybit API changes | Fetch failures | 3 retries + exponential backoff + cached data fallback |
| Frontend complexity (many charts) | Development time | Phase charts: equity first, then others |
| Filter chain changes in production | Backtest becomes stale | Shared module ensures one source of truth |
| Event loop starvation | Unresponsive API | run_in_executor(ProcessPoolExecutor) for CPU work |

---

## 10. Resource Limits & Governance

| Resource | Limit | Enforcement |
|----------|-------|-------------|
| Concurrent backtests | 3 | asyncio.Semaphore in BacktestService |
| Max date range | 365 days | Pydantic validator on request schema |
| Max symbols per run | 200 | Validator (symbols from scan results) |
| Kline cache retention | 180 days | Monthly cron drops old partitions |
| Backtest execution timeout | 120 seconds | asyncio.wait_for() wrapper |
| Per-run memory budget | 256 MB | Pre-flight estimate; reject if exceeds |
| Kline warmup rate | 15 req/s | Shared semaphore with live scanner |
| Equity curve max points | 10,000 stored, 1,000 in API | LTTB downsample on API response |
| Simulation interval | 5m, 15m, 1h, 4h only | Literal type constraint |

**Orphan recovery:** On server startup, transition all `status='running'` records to `status='failed'` with `error_message='server_restart'`.

---

## 11. Observability

**Structured logging** with `run_id` correlation on every backtest operation.

| Metric | Type | Source |
|--------|------|--------|
| `backtest_execution_seconds` | Histogram | Timer around engine.run() |
| `backtest_active_count` | Gauge | Semaphore occupancy |
| `kline_cache_hit_ratio` | Counter | Cache service |
| `kline_fetch_duration_seconds` | Histogram | Bybit API calls |
| `backtest_trades_total` | Counter | Per-run trade count |
| `kline_cache_size_mb` | Gauge | Periodic pg_relation_size check |

**Key log events:** `backtest_started`, `backtest_completed`, `backtest_failed`, `kline_fetch_partial_failure`, `cache_eviction`, `signal_filtered` (with filter reason counts).

---

## 12. Shared Logic Module (Prevents Drift)

Extract core trading decision logic from production services into shared pure functions:

```
backend/services/trading_rules.py
├── filter_signal(signal, config, state) → (pass: bool, reason: str)
├── compute_tp_sl(entry, side, tp_pct, sl_pct, leverage) → (tp, sl)
├── compute_position_size(capital, capital_pct, leverage, price, qty_step, min_qty) → qty
├── check_equity_rise(equity, reference, threshold) → bool
├── check_equity_drop(equity, reference, threshold) → bool
├── check_trailing_profit(per_unit_pnl, peak, ratio=0.5) → bool
├── compute_liquidation_price(entry, side, leverage, mmr) → float
└── compute_unrealized_pnl(entry, current, qty, side) → float
```

Both `auto_trade_service.py` (live) and `backtest_engine.py` import from this module.
CI test: run golden-set vectors through both code paths, assert identical results.
