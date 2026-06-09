/**
 * @module regimeStrategyPreset
 *
 * Research-recommended preset for the Regime Multi-Strategy config block.
 *
 * Architectural role: a static configuration constant consumed by
 * {@link ../RegimeStrategyFields}. Extracted into its own module so the component
 * file exports only a component (React Fast Refresh /
 * `react-refresh/only-export-components`) and so the preset can be imported by
 * tests and other callers without pulling in the component.
 *
 * Boundary: pure data — no rendering, no I/O, no state.
 */
import { type AutoTradeConfig } from "@/api/client";

/**
 * UTC hours blocked by the recommended preset (the Asian-session bleed window
 * identified in the 2026-06-07 profitability report).
 *
 * @remarks Spread into a fresh array when assigned to config so callers cannot
 *   mutate this shared constant. Exported so the inline "Apply recommended" hours
 *   button in {@link ../RegimeStrategyFields} can apply just the blocked hours
 *   without the rest of the preset.
 */
export const RECOMMENDED_BLOCKED_HOURS = [1, 6, 7, 8, 9, 10, 11, 12];

/**
 * One-click "research-recommended" preset (TASK-5.3).
 *
 * Turns F1 (regime/session filter) on with the proven Asian-session block plus a
 * conservative BTC-vol band, and primes F2 (mean-reversion) with small/tight
 * sizing. The long side stays OFF (negative expectancy per the report). Applied
 * via the parent's `onChange` so the existing diff/confirm + persistence flow is
 * reused.
 *
 * @example
 * onChange(RECOMMENDED_PRESET); // user clicks "Apply recommended"
 */
export const RECOMMENDED_PRESET: Partial<AutoTradeConfig> = {
  regime_filter_enabled: true,
  session_filter_enabled: true,
  session_blocked_hours_utc: [...RECOMMENDED_BLOCKED_HOURS],
  btc_vol_filter_enabled: true,
  btc_vol_min_threshold: 0.8,
  btc_vol_max_threshold: 3.0,
  mean_reversion_enabled: true,
  strategy_cohort: "mean_reversion",
  mr_capital_pct: 2,
  mr_leverage: 5,
  mr_time_stop_minutes: 120,
  mr_long_enabled: false,
};
