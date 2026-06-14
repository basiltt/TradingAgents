export type TabId = "setup" | "strategy" | "risk" | "filters";

export const TAB_ORDER: TabId[] = ["setup", "strategy", "risk", "filters"];

export const TAB_LABELS: Record<TabId, string> = {
  setup: "Setup",
  strategy: "Strategy",
  risk: "Risk & Exits",
  filters: "Filters & Advanced",
};

/** Top-level form field paths per tab. The union MUST equal the schema key set
 *  (enforced by tabMeta.test.ts). Used for per-tab error counts + auto-switch.
 *
 *  `scan_source` is one top-level key (its .mode/.schedule_id/etc. live under it).
 *
 *  Carried-but-not-rendered: `mr_regime`, `mr_extreme_min_abs_score`,
 *  `regime_staleness_minutes`, `regime_volatile_atr`, `regime_trend_ema_dist_pct`
 *  have no visible input but are part of the submitted payload (kept at defaults).
 *  They are listed under `strategy` so the coverage invariant holds; no UI renders
 *  them (out of scope — see spec Non-Goals). */
export const FIELD_PATHS_BY_TAB: Record<TabId, string[]> = {
  setup: [
    "starting_capital", "date_range_start", "date_range_end",
    "scan_source",
    "simulation_interval", "fee_rate_pct", "slippage_bps",
    "funding_rate_model", "funding_rate_fixed_pct",
  ],
  strategy: [
    "direction", "leverage", "capital_pct", "take_profit_pct", "stop_loss_pct",
    "min_score", "confidence_filter", "signal_sides", "max_trades",
    "execution_mode", "fill_to_max_trades", "skip_if_positions_open",
    // Market Regime & Strategy (F1/F2/F3)
    "regime_filter_enabled", "session_filter_enabled",
    "session_blocked_hours_utc", "session_allowed_hours_utc",
    "btc_vol_filter_enabled", "btc_vol_min_threshold", "btc_vol_max_threshold",
    "btc_vol_interval", "btc_vol_lookback_candles",
    "strategy_cohort", "mean_reversion_enabled",
    "mr_short_enabled", "mr_long_enabled", "mr_leverage", "mr_capital_pct",
    "mr_max_trades", "mr_mean_period", "mr_mean_interval",
    "mr_target_capture_pct", "mr_tight_stop_pct", "mr_time_stop_minutes",
    "mr_min_edge_pct",
    // Carried-but-not-rendered (payload defaults, no UI — see note above).
    "mr_regime", "mr_extreme_min_abs_score", "regime_staleness_minutes",
    "regime_volatile_atr", "regime_trend_ema_dist_pct",
  ],
  risk: [
    "max_drawdown_pct", "smart_drawdown_close", "close_on_profit_pct",
    "breakeven_timeout_hours", "max_trade_duration_hours", "trailing_profit_pct",
    "max_same_direction", "max_signal_age_minutes",
    "target_goal_type", "target_goal_value",
  ],
  filters: [
    "symbol_whitelist", "symbol_blacklist",
    "max_price_drift_pct", "max_same_sector",
    "require_trend_alignment", "block_falling_knife",
    "adaptive_blacklist_enabled", "adaptive_blacklist_min_trades",
    "adaptive_blacklist_max_win_rate", "adaptive_blacklist_lookback_hours",
    "cooloff_on_success_enabled", "cooloff_on_success_minutes",
    "cooloff_on_failure_enabled", "cooloff_on_failure_minutes",
    "cooloff_on_double_success_enabled", "cooloff_on_double_success_minutes",
    "cooloff_on_double_failure_enabled", "cooloff_on_double_failure_minutes",
  ],
};
