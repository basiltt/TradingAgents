/**
 * @module backtestCompare
 *
 * Pure ranking helpers for the backtest comparison view.
 *
 * Architectural role: comparison-table logic extracted from
 * {@link ../BacktestComparePage} so the component file exports only a component
 * (React Fast Refresh / `react-refresh/only-export-components`) and so the
 * "which run wins this metric" logic is unit-testable in isolation.
 *
 * Boundary: pure functions over `BacktestRun[]` — no rendering, no I/O, no state.
 */
import type { BacktestRun } from "./types";

/**
 * Find the index of the best run for a single metric row.
 *
 * @param runs - The runs being compared, in display order.
 * @param rawValue - Accessor returning the metric for a run, or null when absent.
 *   When undefined, the row is non-rankable and the function returns -1.
 * @param better - `"high"` if larger values win, `"low"` if smaller values win.
 *   When undefined, the row is non-rankable and the function returns -1.
 * @returns The index of the winning run, or -1 when no run has a finite value or
 *   the row is non-rankable.
 *
 * @example
 * bestRunIndex(runs, (r) => r.results?.metrics?.sharpe ?? null, "high"); // → 2
 * bestRunIndex(runs, (r) => r.results?.metrics?.max_dd_pct ?? null, "low"); // → 0
 */
export function bestRunIndex(
  runs: BacktestRun[],
  rawValue: ((r: BacktestRun) => number | null) | undefined,
  better: "high" | "low" | undefined,
): number {
  if (!rawValue || !better) return -1;
  let bestIdx = -1;
  let bestVal: number | null = null;
  runs.forEach((r, i) => {
    const v = rawValue(r);
    if (v == null || !Number.isFinite(v)) return;
    if (bestVal == null || (better === "high" ? v > bestVal : v < bestVal)) {
      bestVal = v;
      bestIdx = i;
    }
  });
  return bestIdx;
}
