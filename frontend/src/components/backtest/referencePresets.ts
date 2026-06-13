/**
 * Reference auto-trade presets, extracted from configSchema.ts so they can be shared
 * WITHOUT pulling zod (and the rest of the schema) into consumers like the scanner's
 * AutoTradeSection. This module's ONLY dependency is the pure `BacktestCreateRequest`
 * type — no zod, no runtime imports. configSchema.ts re-exports these (and uses them
 * internally), so existing importers keep resolving them from "../configSchema".
 */
import type { BacktestCreateRequest } from "./types";

/** Default values for the adaptive-blacklist dependent fields. Single source shared
 *  by the schema `.default()`s, buildDefaults(), and the form's reset/normalize logic
 *  (FiltersAdvancedTab disable + BacktestConfigForm load-time sanitize), so the three
 *  can't drift. Mirrors the production AutoTradeConfig defaults. */
export const ADAPTIVE_BLACKLIST_DEFAULTS = {
  min_trades: 5,
  max_win_rate: 30,
  lookback_hours: 48,
} as const;

export const DAD_DEMO_REFERENCE_CONFIG = {
  starting_capital: 234,
  date_range_start: "2026-06-04T18:30",
  date_range_end: "2026-06-13T06:07",
  scan_source: {
    mode: "schedule",
    schedule_id: "d9c5f14f-a71f-4907-9449-dab3b75a52cb",
  },
  simulation_interval: "5m",
  fee_rate_pct: 0.055,
  slippage_bps: 2,
  funding_rate_model: "fixed_8h",
  funding_rate_fixed_pct: 0.01,
  direction: "straight",
  leverage: 8,
  capital_pct: 22,
  take_profit_pct: 150,
  stop_loss_pct: 100,
  min_score: 7,
  confidence_filter: "moderate",
  signal_sides: "both",
  max_trades: 3,
  execution_mode: "batch",
  fill_to_max_trades: true,
  skip_if_positions_open: true,
  max_same_direction: 3,
  max_same_sector: 4,
  symbol_blacklist: null,
  symbol_whitelist: null,
  max_signal_age_minutes: 150,
  max_price_drift_pct: 6,
  max_drawdown_pct: 12,
  smart_drawdown_close: true,
  breakeven_timeout_hours: null,
  max_trade_duration_hours: 24,
  trailing_profit_pct: 2,
  close_on_profit_pct: null,
  target_goal_type: "profit_pct",
  target_goal_value: 15,
  adaptive_blacklist_enabled: false,
  adaptive_blacklist_min_trades: ADAPTIVE_BLACKLIST_DEFAULTS.min_trades,
  adaptive_blacklist_max_win_rate: ADAPTIVE_BLACKLIST_DEFAULTS.max_win_rate,
  adaptive_blacklist_lookback_hours: ADAPTIVE_BLACKLIST_DEFAULTS.lookback_hours,
  cooloff_on_success_enabled: false,
  cooloff_on_success_minutes: null,
  cooloff_on_failure_enabled: false,
  cooloff_on_failure_minutes: null,
  cooloff_on_double_success_enabled: false,
  cooloff_on_double_success_minutes: null,
  cooloff_on_double_failure_enabled: true,
  cooloff_on_double_failure_minutes: 600,
  regime_filter_enabled: false,
  session_filter_enabled: false,
  session_blocked_hours_utc: null,
  session_allowed_hours_utc: null,
  btc_vol_filter_enabled: false,
  btc_vol_min_threshold: null,
  btc_vol_max_threshold: null,
  btc_vol_interval: "1h",
  btc_vol_lookback_candles: 14,
  mean_reversion_enabled: false,
  mr_short_enabled: false,
  mr_long_enabled: false,
  mr_regime: "ranging",
  mr_mean_period: 20,
  mr_mean_interval: "1h",
  mr_target_capture_pct: 60,
  mr_tight_stop_pct: null,
  mr_time_stop_minutes: 120,
  mr_min_edge_pct: 1,
  mr_extreme_min_abs_score: 5,
  mr_capital_pct: 2,
  mr_leverage: 10,
  mr_max_trades: 2,
  strategy_cohort: null,
  regime_staleness_minutes: 30,
  regime_volatile_atr: 2,
  regime_trend_ema_dist_pct: 1,
} satisfies Partial<BacktestCreateRequest>;

/** Optimized reference preset — the winner of the June 2026 216-combo research
 * sweep (scripts/squeeze_research/). It diverges from the Dad-Demo baseline in
 * exactly the knobs the sweep searched, and was validated out-of-sample:
 * robustly +11–18% more net profit than baseline on every tested window, at a
 * drawdown of ~15% on the original week / ~21% on later windows (a higher-return,
 * higher-risk point on the same frontier — NOT a free drawdown reduction).
 * Winner deltas vs baseline: leverage 8→7, max_trades 3→4, portfolio drawdown
 * stop 12→off, profit target 15→12 (faster capital recycling). */
export const OPTIMIZED_REFERENCE_CONFIG = {
  ...DAD_DEMO_REFERENCE_CONFIG,
  leverage: 7,
  max_trades: 4,
  max_drawdown_pct: 100,
  target_goal_value: 12,
} satisfies Partial<BacktestCreateRequest>;
