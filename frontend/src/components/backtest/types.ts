/**
 * TypeScript types for the backtesting feature — mirror the backend schemas
 * (backtest_schemas.py) and the service response shapes.
 */

export type BacktestStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export const TERMINAL_BACKTEST_STATUSES: BacktestStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

/** The only statuses for which a run is still in flight. Anything NOT in this set
 * (including an unrecognized status string from the backend) is treated as
 * non-active so polling halts — a default-deny guard against infinite polling. */
export const ACTIVE_BACKTEST_STATUSES: BacktestStatus[] = ["pending", "running"];

export function isTerminalStatus(status: BacktestStatus): boolean {
  return TERMINAL_BACKTEST_STATUSES.includes(status);
}

/** True only for pending/running. Unknown/unexpected statuses return false so
 * the UI stops polling rather than looping forever. */
export function isActiveStatus(status: string | null | undefined): boolean {
  return status === "pending" || status === "running";
}

/** Scan source — which historical scan results feed the backtest. */
export interface ScanSource {
  mode: "schedule" | "date_range" | "explicit";
  schedule_id?: string;
  scan_ids?: string[];
}

/** Request body for creating a backtest (mirrors BacktestCreateRequest). */
export interface BacktestCreateRequest {
  // Backtest-specific
  starting_capital: number;
  date_range_start: string; // ISO 8601
  date_range_end: string;
  scan_source: ScanSource;
  simulation_interval?: "5m" | "15m" | "1h" | "4h";
  fee_rate_pct?: number;
  slippage_bps?: number;
  funding_rate_model?: "none" | "fixed_8h";
  funding_rate_fixed_pct?: number;

  // Trade-decision params (AutoTradeConfig subset)
  direction?: "straight" | "reverse";
  leverage?: number;
  capital_pct?: number;
  take_profit_pct?: number;
  stop_loss_pct?: number;
  min_score?: number;
  confidence_filter?: "any" | "high" | "moderate" | "low";
  signal_sides?: "both" | "buy" | "sell";
  max_trades?: number;
  execution_mode?: "immediate" | "batch";
  fill_to_max_trades?: boolean;
  skip_if_positions_open?: boolean;
  max_same_direction?: number | null;
  max_same_sector?: number | null;
  symbol_blacklist?: string[] | null;
  symbol_whitelist?: string[] | null;
  max_signal_age_minutes?: number | null;
  max_price_drift_pct?: number | null;

  // Close rules
  max_drawdown_pct?: number;
  smart_drawdown_close?: boolean;
  breakeven_timeout_hours?: number | null;
  max_trade_duration_hours?: number | null;
  trailing_profit_pct?: number | null;
  close_on_profit_pct?: number | null;
  target_goal_type?: "trade_count" | "profit_pct" | null;
  target_goal_value?: number | null;

  // Adaptive blacklist
  adaptive_blacklist_enabled?: boolean;
  adaptive_blacklist_min_trades?: number;
  adaptive_blacklist_max_win_rate?: number;
  adaptive_blacklist_lookback_hours?: number;

  // ── Regime Multi-Strategy (F1/F2/F3) — replayed in the backtester ──
  // F1 — Regime/Session Entry Filter
  regime_filter_enabled?: boolean;
  session_filter_enabled?: boolean;
  session_blocked_hours_utc?: number[] | null;
  session_allowed_hours_utc?: number[] | null;
  btc_vol_filter_enabled?: boolean;
  btc_vol_min_threshold?: number | null;
  btc_vol_max_threshold?: number | null;
  btc_vol_interval?: "15m" | "1h" | "4h";
  btc_vol_lookback_candles?: number;
  // F2 — Mean-Reversion Strategy
  mean_reversion_enabled?: boolean;
  mr_short_enabled?: boolean;
  mr_long_enabled?: boolean;
  mr_regime?: "ranging";
  mr_mean_period?: number;
  mr_mean_interval?: "15m" | "1h" | "4h";
  mr_target_capture_pct?: number;
  mr_tight_stop_pct?: number | null;
  mr_time_stop_minutes?: number;
  mr_min_edge_pct?: number;
  mr_extreme_min_abs_score?: number;
  mr_capital_pct?: number;
  mr_leverage?: number;
  mr_max_trades?: number;
  // F3 — Strategy-Cohort (tri-state; null inherits -> trend in backtest)
  strategy_cohort?: "trend" | "mean_reversion" | null;
  // classifier-tuning
  regime_staleness_minutes?: number;
  regime_volatile_atr?: number;
  regime_trend_ema_dist_pct?: number;
}

/** Per-direction metric subset (All / Long / Short columns). */
export interface DirectionMetrics {
  total_trades: number;
  winners: number;
  losers: number;
  net_profit: number;
  win_rate: number | null;
  avg_trade: number | null;
  avg_win: number | null;
  avg_loss: number | null;
}

/** The full metrics payload from compute_all_metrics (TradingView-parity). */
export interface BacktestMetrics {
  total_trades: number;
  winners: number;
  losers: number;
  net_profit: number;
  net_profit_pct: number | null;
  gross_profit: number;
  gross_loss: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_dd_pct: number;
  max_dd_usd: number;
  max_dd_duration_hours: number;
  avg_dd_pct: number;
  max_run_up_pct: number;
  max_run_up_usd: number;
  avg_trade: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  avg_win_loss_ratio: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  total_commission: number;
  recovery_factor: number | null;
  cagr: number | null;
  calmar: number | null;
  expectancy: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  max_consecutive_wins_usd: number;
  max_consecutive_losses_usd: number;
  avg_trade_duration_hours: number | null;
  avg_winner_duration_hours: number | null;
  avg_loser_duration_hours: number | null;
  max_trade_duration_hours: number | null;
  final_equity: number;
  by_direction: { all: DirectionMetrics; long: DirectionMetrics; short: DirectionMetrics };
  /** Per-strategy×direction breakdown keyed "<kind>:<long|short>" (e.g. "mean_reversion:short"). */
  by_strategy?: Record<string, DirectionMetrics>;
  per_trade?: PerTradePoint[];
  diagnostics?: Record<string, number>;
  // Phase 5 service-attached comparison fields
  buy_hold_return_pct?: number | null;
  buy_hold_final_value?: number | null;
  excess_return?: number | null;
}

/** A single point in the per-trade cumulative-PnL series. */
export interface PerTradePoint {
  index: number;
  symbol: string | null;
  side: string | null;
  pnl: number;
  cumulative_pnl: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  close_reason: string | null;
  entry_time: string | null;
  exit_time: string | null;
}

/** A single point in the equity curve. */
export interface EquityPoint {
  ts: string | null;
  equity: number;
  drawdown_pct?: number;
}

/** The results bundle attached to a completed run. */
export interface BacktestResults {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  summary: Record<string, unknown>;
  warnings: string[];
}

/** A backtest run (lifecycle + optional results). */
export interface BacktestRun {
  id: string;
  status: BacktestStatus;
  config: Record<string, unknown>;
  scan_source: Record<string, unknown>;
  progress_pct: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  results?: BacktestResults | null;
}

/** A persisted simulated trade row. */
export interface BacktestTrade {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  qty: number;
  leverage: number;
  entry_time: string;
  exit_time: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  fees_paid: number | null;
  close_reason: string | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  signal_score: number | null;
  signal_confidence: string | null;
  scan_id: string | null;
}

/** Paginated trades response. */
export interface BacktestTradesResponse {
  trades: BacktestTrade[];
  total: number;
  page: number;
}

/** Comparison response (2-4 runs). */
export interface BacktestCompareResponse {
  runs: BacktestRun[];
}

/** Kline-cache coverage status. */
export interface CacheStatusResponse {
  symbols_total: number;
  symbols_cached: number;
  symbols_with_gaps: string[];
  ready: boolean;
}
