import { type AutoTradeConfig } from "@/api/client";
import {
  DAD_DEMO_REFERENCE_CONFIG,
  OPTIMIZED_REFERENCE_CONFIG,
  BEST_WINRATE_CONFIG,
} from "@/components/backtest/referencePresets";

/**
 * Maps the curated backtest reference presets onto a live `AutoTradeConfig` so the
 * Auto-Trade account card can prefill trade/risk/strategy settings from a backtested
 * config. Pure + dependency-light: imports only the (zod-free) preset constants and the
 * `AutoTradeConfig` type — never the backtest form or zod.
 */

/**
 * Fields the apply MUST NEVER write:
 * - `account_id` — the card's own routing, not a strategy setting.
 * - `ai_manager_*` / `ai_pause_cycles` — AI-Manager is user-managed on the card.
 * - `mr_long_ack_requested` — a transient ack flag, not part of a strategy preset.
 * - `strategy_kind` / `f1_active` — response-only read-backs from the engine.
 * Excluding them from the key TYPE makes listing one a COMPILE ERROR: a bare
 * `keyof AutoTradeConfig` would still accept `account_id`/`ai_manager_*` (they ARE
 * keys), so this exclusion is the real guard, not the `satisfies` alone.
 */
export const PROTECTED_KEYS = [
  "account_id",
  "ai_manager_enabled",
  "ai_manager_capabilities",
  "ai_pause_cycles",
  "mr_long_ack_requested",
  "strategy_kind",
  "f1_active",
] as const;
type ProtectedKey = (typeof PROTECTED_KEYS)[number];

type MappableKey = Exclude<keyof AutoTradeConfig, ProtectedKey>;

/**
 * The 67 trade/risk/strategy keys shared by the presets and `AutoTradeConfig`. The
 * `satisfies readonly MappableKey[]` clause rejects a typo OR a protected/response-only
 * key at compile time. (Backtest-only preset keys like `starting_capital`,
 * `scan_source`, `simulation_interval`, fees/slippage/funding are NOT keys of
 * `AutoTradeConfig`, so they too fail the `satisfies` check if listed.)
 */
export const MAPPABLE_KEYS = [
  // Direction / sizing / exits
  "direction",
  "leverage",
  "capital_pct",
  "take_profit_pct",
  "stop_loss_pct",
  "min_score",
  "confidence_filter",
  "signal_sides",
  "max_trades",
  "execution_mode",
  "fill_to_max_trades",
  "skip_if_positions_open",
  "max_same_direction",
  "max_same_sector",
  "symbol_blacklist",
  "symbol_whitelist",
  "max_signal_age_minutes",
  "max_price_drift_pct",
  // FIX-005 signal-quality gates
  "require_trend_alignment",
  "block_falling_knife",
  "max_drawdown_pct",
  "smart_drawdown_close",
  "breakeven_timeout_hours",
  "max_trade_duration_hours",
  "trailing_profit_pct",
  "close_on_profit_pct",
  "target_goal_type",
  "target_goal_value",
  // Adaptive blacklist
  "adaptive_blacklist_enabled",
  "adaptive_blacklist_min_trades",
  "adaptive_blacklist_max_win_rate",
  "adaptive_blacklist_lookback_hours",
  // Cool-off tiers (8)
  "cooloff_on_success_enabled",
  "cooloff_on_success_minutes",
  "cooloff_on_failure_enabled",
  "cooloff_on_failure_minutes",
  "cooloff_on_double_success_enabled",
  "cooloff_on_double_success_minutes",
  "cooloff_on_double_failure_enabled",
  "cooloff_on_double_failure_minutes",
  // Regime / session / BTC-vol
  "regime_filter_enabled",
  "session_filter_enabled",
  "session_blocked_hours_utc",
  "session_allowed_hours_utc",
  "btc_vol_filter_enabled",
  "btc_vol_min_threshold",
  "btc_vol_max_threshold",
  "btc_vol_interval",
  "btc_vol_lookback_candles",
  // Mean-reversion
  "mean_reversion_enabled",
  "mr_short_enabled",
  "mr_long_enabled",
  "mr_regime",
  "mr_mean_period",
  "mr_mean_interval",
  "mr_target_capture_pct",
  "mr_tight_stop_pct",
  "mr_time_stop_minutes",
  "mr_min_edge_pct",
  "mr_extreme_min_abs_score",
  "mr_capital_pct",
  "mr_leverage",
  "mr_max_trades",
  "strategy_cohort",
  // Regime classifier tuning
  "regime_staleness_minutes",
  "regime_volatile_atr",
  "regime_trend_ema_dist_pct",
] as const satisfies readonly MappableKey[];

export type ReferencePresetId = "reference" | "optimized" | "best_winrate";

/**
 * Single accessor seam for the preset values. Today it returns the hardcoded literal;
 * the future weekly `sweep_run` auto-update swaps ONLY this body (e.g. fetch/cache the
 * latest optimized config) without touching any call site.
 */
export function getReferencePreset(id: ReferencePresetId): Record<string, unknown> {
  switch (id) {
    case "reference":
      return DAD_DEMO_REFERENCE_CONFIG;
    case "optimized":
      return OPTIMIZED_REFERENCE_CONFIG;
    case "best_winrate":
      return BEST_WINRATE_CONFIG;
    default: {
      // Exhaustiveness guard: a new ReferencePresetId that forgets to add a case
      // fails to compile HERE instead of silently returning the Reference preset.
      const _exhaustive: never = id;
      return _exhaustive;
    }
  }
}

/**
 * Build the partial `AutoTradeConfig` to merge into the card. Copies ONLY the 67
 * mappable keys (skips backtest-only + protected fields by construction), omitting any
 * key the preset leaves undefined.
 */
export function presetToAutoTradeConfig(id: ReferencePresetId): Partial<AutoTradeConfig> {
  const preset = getReferencePreset(id);
  const out: Partial<AutoTradeConfig> = {};
  for (const k of MAPPABLE_KEYS) {
    const v = preset[k];
    if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}

/**
 * Would applying this preset actually change any mappable field on the card? Used to
 * skip the confirm (and the no-op onChange) when the card already matches the preset.
 * Treats absent ≈ undefined via `Object.is`.
 */
export function presetChangesCard(config: AutoTradeConfig, id: ReferencePresetId): boolean {
  const partial = presetToAutoTradeConfig(id) as Record<string, unknown>;
  const c = config as unknown as Record<string, unknown>;
  return Object.keys(partial).some((k) => !Object.is(c[k], partial[k]));
}

/**
 * Has the card diverged from a fresh card's defaults on any mappable key? `defaults` is
 * PASSED IN (the caller hands its local `DEFAULT_CONFIG`) so this module never imports
 * `DEFAULT_CONFIG` from `AutoTradeSection.tsx` — which imports THIS module — avoiding a
 * circular dependency. Compares over `MAPPABLE_KEYS` with absent ≈ undefined, since
 * `DEFAULT_CONFIG` is an incomplete `Omit` (several mappable keys default to undefined).
 */
export function cardHasEdits(
  config: AutoTradeConfig,
  defaults: Omit<AutoTradeConfig, "account_id">,
): boolean {
  const c = config as unknown as Record<string, unknown>;
  const d = defaults as unknown as Record<string, unknown>;
  return (MAPPABLE_KEYS as readonly string[]).some((k) => !Object.is(c[k], d[k]));
}
