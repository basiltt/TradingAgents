/**
 * @module cohortConcentration
 *
 * Pure strategy-cohort concentration logic for the fleet view.
 *
 * Architectural role: the F3 decorrelation guard (AC-014) extracted from
 * {@link ../FleetCohortView} so the component file exports only a component (React
 * Fast Refresh / `react-refresh/only-export-components`) and so the concentration
 * math is unit-testable without rendering.
 *
 * Boundary: pure functions and constants over account cohort assignments — no
 * rendering, no I/O, no state.
 */
import type { TradingAccount } from "../../api/client";

/** A strategy cohort an account can belong to. */
export type Cohort = "trend" | "mean_reversion";

/**
 * Concentration warning threshold (server-side SD22 constant).
 *
 * @remarks When a single cohort holds more than this fraction of the fleet, a
 *   warning is surfaced: concentrating one strategy re-correlates drawdowns.
 */
export const COHORT_CONCENTRATION_PCT = 0.7;

/**
 * Result of the cohort-concentration calculation.
 *
 * @property trend - Count of accounts in the trend cohort.
 * @property mean_reversion - Count of accounts in the mean-reversion cohort.
 * @property dominant - The larger cohort (ties resolve to `"trend"`), or null when
 *   the fleet is empty.
 * @property fraction - The dominant cohort's share of the fleet in `[0, 1]`.
 * @property warn - True when `fraction` exceeds {@link COHORT_CONCENTRATION_PCT}.
 */
export interface CohortConcentration {
  trend: number;
  mean_reversion: number;
  dominant: Cohort | null;
  fraction: number;
  warn: boolean;
}

/**
 * Compute per-cohort counts and whether a single cohort dominates the fleet
 * beyond {@link COHORT_CONCENTRATION_PCT} (the F3 decorrelation guard).
 *
 * @param accounts - The fleet, each carrying an optional `strategy_cohort`. Any
 *   value other than `"mean_reversion"` is treated as `"trend"`.
 * @returns Counts, the dominant cohort, its fleet fraction, and the warn flag.
 *
 * @example
 * computeConcentration([{ strategy_cohort: "trend" }, { strategy_cohort: "trend" }]);
 * // → { trend: 2, mean_reversion: 0, dominant: "trend", fraction: 1, warn: true }
 */
export function computeConcentration(
  accounts: Pick<TradingAccount, "strategy_cohort">[],
): CohortConcentration {
  const counts = { trend: 0, mean_reversion: 0 };
  for (const a of accounts) {
    const c: Cohort = a.strategy_cohort === "mean_reversion" ? "mean_reversion" : "trend";
    counts[c] += 1;
  }
  const total = accounts.length;
  let dominant: Cohort | null = null;
  let fraction = 0;
  if (total > 0) {
    dominant = counts.trend >= counts.mean_reversion ? "trend" : "mean_reversion";
    fraction = counts[dominant] / total;
  }
  return { ...counts, dominant, fraction, warn: total > 0 && fraction > COHORT_CONCENTRATION_PCT };
}
