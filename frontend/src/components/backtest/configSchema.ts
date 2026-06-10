/**
 * Zod schema + defaults for the backtest configuration form. Kept separate from
 * the component so validation rules are unit-testable and reusable.
 *
 * Mirrors BacktestCreateRequest (types.ts) and the backend validation in
 * backtest_schemas.py — BOTH the ranges AND the DEFAULTS must match the backend,
 * which in turn inherits its defaults from the production AutoTradeConfig. This
 * keeps the form (and any raw-API caller that omits a field) on real-world trading
 * defaults, so backtest results reflect ~100% real trading rather than an
 * arbitrary conservative form preset.
 */
import { z } from "zod";
import type { BacktestCreateRequest } from "./types";

const isoDate = z.string().min(1, "Required");

export const scanSourceSchema = z
  .object({
    mode: z.enum(["schedule", "date_range", "explicit", "replay"]),
    schedule_id: z.string().optional(),
    // Backend caps scan_ids at 500 (backtest_schemas.py).
    scan_ids: z.array(z.string()).max(500, "Maximum 500 scans").optional(),
    // Replay mode: account whose actual live trades are replayed for validation.
    replay_account_id: z.string().optional(),
  })
  .refine(
    (s) => s.mode !== "schedule" || !!s.schedule_id,
    { message: "Select a schedule", path: ["schedule_id"] },
  )
  .refine(
    (s) => s.mode !== "explicit" || (s.scan_ids != null && s.scan_ids.length > 0),
    { message: "Select at least one scan", path: ["scan_ids"] },
  )
  .refine(
    (s) => s.mode !== "replay" || !!s.replay_account_id,
    { message: "Select an account to replay", path: ["replay_account_id"] },
  );

export const backtestConfigSchema = z
  .object({
    // Backtest-specific — ranges AND defaults MUST match backend BacktestCreateRequest.
    starting_capital: z.coerce
      .number({ error: "Enter a starting capital" })
      .positive("Must be > 0")
      .max(100_000_000, "Max $100,000,000"),
    date_range_start: isoDate,
    date_range_end: isoDate,
    scan_source: scanSourceSchema,
    simulation_interval: z.enum(["5m", "15m", "1h", "4h"]).default("5m"),
    fee_rate_pct: z.coerce.number().min(0).max(1).default(0.055),
    slippage_bps: z.coerce.number().int().min(0).max(50).default(2),
    funding_rate_model: z.enum(["none", "fixed_8h"]).default("none"),
    funding_rate_fixed_pct: z.coerce.number().min(-0.5).max(0.5).default(0.01),

    // Trade-decision params (AutoTradeConfig subset) — defaults mirror production.
    direction: z.enum(["straight", "reverse"]).default("straight"),
    leverage: z.coerce.number().int().min(1).max(125).default(20),
    capital_pct: z.coerce.number().positive().max(100).default(5),
    take_profit_pct: z.coerce.number().positive().max(1000).default(150),
    stop_loss_pct: z.coerce.number().positive().max(1000).default(100),
    // Backend signal score scale is -10..10 (NOT 0..100).
    min_score: z.coerce.number().min(-10).max(10).default(0),
    confidence_filter: z.enum(["any", "high", "moderate", "low"]).default("any"),
    signal_sides: z.enum(["both", "buy", "sell"]).default("both"),
    max_trades: z.coerce.number().int().min(1).max(999).default(999),
    execution_mode: z.enum(["immediate", "batch"]).default("immediate"),
    fill_to_max_trades: z.boolean().default(false),
    skip_if_positions_open: z.boolean().default(false),
    max_same_direction: z.coerce.number().int().min(1).max(100).nullable().default(null),
    max_same_sector: z.coerce.number().int().min(1).max(50).nullable().default(null),
    symbol_blacklist: z.array(z.string()).max(200).nullable().default(null),
    symbol_whitelist: z.array(z.string()).max(200).nullable().default(null),
    max_signal_age_minutes: z.coerce.number().int().min(1).nullable().default(null),
    max_price_drift_pct: z.coerce.number().min(0.1).max(50).nullable().default(null),

    // Close rules
    max_drawdown_pct: z.coerce.number().positive().max(100).default(100),
    smart_drawdown_close: z.boolean().default(false),
    breakeven_timeout_hours: z.coerce.number().min(0.1).max(720).nullable().default(null),
    max_trade_duration_hours: z.coerce.number().min(0.1).max(720).nullable().default(null),
    trailing_profit_pct: z.coerce.number().min(0.1).max(50).nullable().default(null),
    close_on_profit_pct: z.coerce.number().min(0.1).max(100).nullable().default(null),
    target_goal_type: z.enum(["trade_count", "profit_pct"]).nullable().default(null),
    target_goal_value: z.coerce.number().positive().nullable().default(null),

    // Adaptive blacklist — defaults mirror production AutoTradeConfig.
    adaptive_blacklist_enabled: z.boolean().default(false),
    adaptive_blacklist_min_trades: z.coerce.number().int().min(1).max(100).default(5),
    adaptive_blacklist_max_win_rate: z.coerce.number().min(0).max(100).default(30),
    adaptive_blacklist_lookback_hours: z.coerce.number().int().min(1).max(720).default(48),

    // ── Regime Multi-Strategy (F1/F2/F3) — replayed in the backtester ──
    regime_filter_enabled: z.boolean().default(false),
    session_filter_enabled: z.boolean().default(false),
    session_blocked_hours_utc: z.array(z.coerce.number().int().min(0).max(23)).nullable().default(null),
    session_allowed_hours_utc: z.array(z.coerce.number().int().min(0).max(23)).nullable().default(null),
    btc_vol_filter_enabled: z.boolean().default(false),
    btc_vol_min_threshold: z.coerce.number().min(0).nullable().default(null),
    btc_vol_max_threshold: z.coerce.number().min(0).nullable().default(null),
    btc_vol_interval: z.enum(["15m", "1h", "4h"]).default("1h"),
    btc_vol_lookback_candles: z.coerce.number().int().min(2).max(200).default(14),
    mean_reversion_enabled: z.boolean().default(false),
    mr_short_enabled: z.boolean().default(true),
    mr_long_enabled: z.boolean().default(false),
    mr_regime: z.enum(["ranging"]).default("ranging"),
    mr_mean_period: z.coerce.number().int().min(2).max(200).default(20),
    mr_mean_interval: z.enum(["15m", "1h", "4h"]).default("1h"),
    mr_target_capture_pct: z.coerce.number().positive().max(100).default(60),
    mr_tight_stop_pct: z.coerce.number().positive().max(1000).nullable().default(null),
    mr_time_stop_minutes: z.coerce.number().int().min(5).max(1440).default(120),
    mr_min_edge_pct: z.coerce.number().min(0).max(100).default(1),
    mr_extreme_min_abs_score: z.coerce.number().min(0).max(10).default(5),
    mr_capital_pct: z.coerce.number().positive().max(100).default(2),
    mr_leverage: z.coerce.number().int().min(1).max(125).default(10),
    mr_max_trades: z.coerce.number().int().min(1).max(999).default(2),
    strategy_cohort: z.enum(["trend", "mean_reversion"]).nullable().default(null),
    regime_staleness_minutes: z.coerce.number().int().min(5).max(240).default(30),
    regime_volatile_atr: z.coerce.number().positive().max(10).default(2),
    regime_trend_ema_dist_pct: z.coerce.number().min(0).max(50).default(1),
  })
  .refine(
    (c) => new Date(c.date_range_end).getTime() > new Date(c.date_range_start).getTime(),
    { message: "End must be after start", path: ["date_range_end"] },
  )
  .refine(
    (c) => {
      // Backend caps the window at 365 *whole* days (timedelta.days > 365 → reject),
      // so a duration in (365d, 366d) is still accepted there. Match that semantics.
      const ms = new Date(c.date_range_end).getTime() - new Date(c.date_range_start).getTime();
      return Math.floor(ms / (24 * 3600 * 1000)) <= 365;
    },
    { message: "Date range cannot exceed 365 days", path: ["date_range_end"] },
  )
  .refine(
    // SL% at the chosen leverage cannot reach the liquidation distance (backend rule).
    (c) => c.stop_loss_pct / c.leverage < 100,
    { message: "Stop loss too large for this leverage (liquidation risk)", path: ["stop_loss_pct"] },
  )
  .refine(
    // Breakeven timeout must fire before the max-duration close (when both set).
    (c) =>
      c.breakeven_timeout_hours == null ||
      c.max_trade_duration_hours == null ||
      c.breakeven_timeout_hours < c.max_trade_duration_hours,
    {
      message: "Breakeven timeout must be less than max duration",
      path: ["breakeven_timeout_hours"],
    },
  )
  .refine(
    // close_on_profit_pct requires target_goal_value (backend + live-trading parity:
    // the effective threshold is (close_on_profit_pct/100)·target_goal_value, so the
    // goal value must be set, or the rule has no defined trigger level).
    (c) =>
      c.close_on_profit_pct == null ||
      (c.target_goal_value != null && c.target_goal_value > 0),
    {
      message: "Close on Profit requires a Goal Value",
      path: ["target_goal_value"],
    },
  )
  .refine(
    // Regime F1: blocked + allowed session hours are mutually exclusive (backend).
    (c) => !(c.session_blocked_hours_utc != null && c.session_allowed_hours_utc != null),
    { message: "Use blocked OR allowed session hours, not both", path: ["session_blocked_hours_utc"] },
  )
  .refine(
    // Regime F1: BTC vol band must be lo < hi when both set (backend).
    (c) => c.btc_vol_min_threshold == null || c.btc_vol_max_threshold == null ||
           c.btc_vol_min_threshold < c.btc_vol_max_threshold,
    { message: "Min vol must be < Max vol", path: ["btc_vol_min_threshold"] },
  )
  .refine(
    // Regime F2: enabling MR requires at least one direction (backend).
    (c) => !c.mean_reversion_enabled || c.mr_short_enabled || c.mr_long_enabled,
    { message: "Enable at least one MR direction (short or long)", path: ["mr_short_enabled"] },
  );

export type BacktestConfigFormValues = z.input<typeof backtestConfigSchema>;
export type BacktestConfigParsed = z.output<typeof backtestConfigSchema>;

/** Format a Date as a `datetime-local`-compatible string in LOCAL wall-clock
 * time (YYYY-MM-DDTHH:mm). Using toISOString() here would bake in UTC and shift
 * the visible default range by the user's tz offset. */
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Coerce a seed date (which may be a full ISO string with 'Z'/offset, as
 * produced by toCreateRequest) into the `datetime-local` format the input needs.
 * A datetime-local input silently blanks any value carrying Z/offset/ms. */
function seedDateToInput(value: string | undefined, fallback: Date): string {
  if (!value) return toLocalInputValue(fallback);
  // Already in plain local form (no timezone marker) → use as-is.
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) && value.length <= 16) return value;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? toLocalInputValue(fallback) : toLocalInputValue(d);
}

/** Build default form values, optionally seeded from a partial config.
 * Return type is Required<…> so omitting any field is a typecheck error — this
 * guards against the schema and these defaults silently drifting apart.
 *
 * The non-seed fallbacks MUST equal the zod `.default()`s in backtestConfigSchema
 * (which in turn mirror the backend BacktestCreateRequest / production
 * AutoTradeConfig). buildDefaults supplies EVERY field, so the zod defaults never
 * fire here — if these literals drift from the schema, the form silently ships
 * non-production presets and the "~100% real trading" guarantee breaks. The
 * configSchema test asserts the schema's own minimal-parse defaults; keep these in
 * lockstep with that. */
export function buildDefaults(
  seed?: Partial<BacktestCreateRequest>,
): Required<BacktestConfigFormValues> {
  const now = new Date();
  const start = new Date(now.getTime() - 30 * 24 * 3600 * 1000);
  return {
    starting_capital: seed?.starting_capital ?? 10000,
    date_range_start: seedDateToInput(seed?.date_range_start, start),
    date_range_end: seedDateToInput(seed?.date_range_end, now),
    scan_source: seed?.scan_source ?? { mode: "date_range" },
    simulation_interval: seed?.simulation_interval ?? "5m",
    fee_rate_pct: seed?.fee_rate_pct ?? 0.055,
    slippage_bps: seed?.slippage_bps ?? 2,
    funding_rate_model: seed?.funding_rate_model ?? "none",
    funding_rate_fixed_pct: seed?.funding_rate_fixed_pct ?? 0.01,
    direction: seed?.direction ?? "straight",
    leverage: seed?.leverage ?? 20,
    capital_pct: seed?.capital_pct ?? 5,
    take_profit_pct: seed?.take_profit_pct ?? 150,
    stop_loss_pct: seed?.stop_loss_pct ?? 100,
    min_score: seed?.min_score ?? 0,
    confidence_filter: seed?.confidence_filter ?? "any",
    signal_sides: seed?.signal_sides ?? "both",
    max_trades: seed?.max_trades ?? 999,
    execution_mode: seed?.execution_mode ?? "immediate",
    fill_to_max_trades: seed?.fill_to_max_trades ?? false,
    skip_if_positions_open: seed?.skip_if_positions_open ?? false,
    max_same_direction: seed?.max_same_direction ?? null,
    max_same_sector: seed?.max_same_sector ?? null,
    symbol_blacklist: seed?.symbol_blacklist ?? null,
    symbol_whitelist: seed?.symbol_whitelist ?? null,
    max_signal_age_minutes: seed?.max_signal_age_minutes ?? null,
    max_price_drift_pct: seed?.max_price_drift_pct ?? null,
    max_drawdown_pct: seed?.max_drawdown_pct ?? 100,
    smart_drawdown_close: seed?.smart_drawdown_close ?? false,
    breakeven_timeout_hours: seed?.breakeven_timeout_hours ?? null,
    max_trade_duration_hours: seed?.max_trade_duration_hours ?? null,
    trailing_profit_pct: seed?.trailing_profit_pct ?? null,
    close_on_profit_pct: seed?.close_on_profit_pct ?? null,
    target_goal_type: seed?.target_goal_type ?? null,
    target_goal_value: seed?.target_goal_value ?? null,
    adaptive_blacklist_enabled: seed?.adaptive_blacklist_enabled ?? false,
    adaptive_blacklist_min_trades: seed?.adaptive_blacklist_min_trades ?? 5,
    adaptive_blacklist_max_win_rate: seed?.adaptive_blacklist_max_win_rate ?? 30,
    adaptive_blacklist_lookback_hours: seed?.adaptive_blacklist_lookback_hours ?? 48,
    // Regime Multi-Strategy (F1/F2/F3) — defaults mirror backend (all off / inherit).
    regime_filter_enabled: seed?.regime_filter_enabled ?? false,
    session_filter_enabled: seed?.session_filter_enabled ?? false,
    session_blocked_hours_utc: seed?.session_blocked_hours_utc ?? null,
    session_allowed_hours_utc: seed?.session_allowed_hours_utc ?? null,
    btc_vol_filter_enabled: seed?.btc_vol_filter_enabled ?? false,
    btc_vol_min_threshold: seed?.btc_vol_min_threshold ?? null,
    btc_vol_max_threshold: seed?.btc_vol_max_threshold ?? null,
    btc_vol_interval: seed?.btc_vol_interval ?? "1h",
    btc_vol_lookback_candles: seed?.btc_vol_lookback_candles ?? 14,
    mean_reversion_enabled: seed?.mean_reversion_enabled ?? false,
    mr_short_enabled: seed?.mr_short_enabled ?? true,
    mr_long_enabled: seed?.mr_long_enabled ?? false,
    mr_regime: seed?.mr_regime ?? "ranging",
    mr_mean_period: seed?.mr_mean_period ?? 20,
    mr_mean_interval: seed?.mr_mean_interval ?? "1h",
    mr_target_capture_pct: seed?.mr_target_capture_pct ?? 60,
    mr_tight_stop_pct: seed?.mr_tight_stop_pct ?? null,
    mr_time_stop_minutes: seed?.mr_time_stop_minutes ?? 120,
    mr_min_edge_pct: seed?.mr_min_edge_pct ?? 1,
    mr_extreme_min_abs_score: seed?.mr_extreme_min_abs_score ?? 5,
    mr_capital_pct: seed?.mr_capital_pct ?? 2,
    mr_leverage: seed?.mr_leverage ?? 10,
    mr_max_trades: seed?.mr_max_trades ?? 2,
    strategy_cohort: seed?.strategy_cohort ?? null,
    regime_staleness_minutes: seed?.regime_staleness_minutes ?? 30,
    regime_volatile_atr: seed?.regime_volatile_atr ?? 2,
    regime_trend_ema_dist_pct: seed?.regime_trend_ema_dist_pct ?? 1,
  };
}

/** Convert a parsed form value into the API request body (ISO-normalizes dates). */
export function toCreateRequest(parsed: BacktestConfigParsed): BacktestCreateRequest {
  return {
    ...parsed,
    date_range_start: new Date(parsed.date_range_start).toISOString(),
    date_range_end: new Date(parsed.date_range_end).toISOString(),
  };
}
