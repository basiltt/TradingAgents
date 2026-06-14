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

// ── Trades tab (Phase 3) ─────────────────────────────────────────────────────
export interface SymbolRow { symbol: string; trades: number; count: number; pnl: number; win_rate: number | null; }
export interface StrategyRow { strategy: string; trades: number; count: number; pnl: number; win_rate: number | null; }
export interface CloseReasonRow { reason: string; count: number; pnl: number; }
export interface DistributionRow { bucket: string; count: number; }
export interface HoldTimeRow { bucket: string; count: number; win_rate: number | null; }

export interface TradesBreakdown {
  by_symbol: SymbolRow[];
  by_strategy: StrategyRow[];
  by_close_reason: CloseReasonRow[];
  pnl_distribution: DistributionRow[];
  hold_time_buckets: HoldTimeRow[];
  meta: { strategy_legacy_approximate: boolean };
}

export interface TradeRow {
  id: string;
  symbol: string;
  side: string;
  net_pnl: number | null;
  net_pnl_pct: number | null;
  close_reason: string | null;
  opened_at: string | null;
  closed_at: string | null;
  hold_hours: number | null;
}

export interface TradesPage {
  rows: TradeRow[];
  cursor: string | null;
  has_more: boolean;
}

// ── Signals tab (Phase 4) ────────────────────────────────────────────────────
export interface SignalSummary {
  total_trades: number;
  win_rate: number;
  avg_pnl_pct: number;
  total_pnl: number;
  avg_hold_minutes: number;
  current_streak: number;
  active_alerts: number;
}
export interface WinRatePoint { date: string | null; win_rate: number; trade_number: number; }
export type SignalWinRate = WinRatePoint[];

// ── Live tab (Phase 5) ───────────────────────────────────────────────────────
export interface LivePosition {
  account_id: string;
  symbol: string;
  side: string;
  size: number;
  leverage: number;
  entry: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number | null;
}
export interface AccountTile {
  account_id: string;
  label: string;
  type: string | null;
  equity: number | null;
  today_pnl: number | null;
  positions_count: number;
  error: string | null;
}
export interface SectorConcentration { sector: string; exposure_pct: number; positions: number; }
export interface PerformanceLive {
  positions: LivePosition[];
  account_tiles: AccountTile[];
  sector_concentration: SectorConcentration[];
  degraded: boolean;
}
