/**
 * @module equityCurveData
 *
 * Pure data-shaping helpers for the backtest equity-curve visualization.
 *
 * Architectural role: presentation-layer transforms that turn raw `EquityPoint[]`
 * series (from the backtest API) into chart-ready rows for recharts. Kept separate
 * from {@link ../EquityCurveChart} (the React component) so the functions can be
 * unit-tested in isolation and so the component file exports only a component
 * (required for React Fast Refresh / `react-refresh/only-export-components`).
 *
 * Boundary: this module performs NO rendering, NO I/O, and holds NO state — every
 * export is a referentially-transparent function of its inputs.
 */
import type { EquityPoint } from "./types";

/**
 * A single charted row of the equity curve.
 *
 * @property label - Compact x-axis label derived from the point timestamp (see
 *   {@link formatTsLabel}).
 * @property equity - Account equity at this sample, rounded to 2 decimals.
 * @property drawdown - Drawdown-from-peak as a non-positive percent (0 or negative).
 */
export interface EquityChartDatum {
  label: string;
  equity: number;
  drawdown: number; // negative or zero, percent
}

/**
 * Format an ISO timestamp into a compact axis label (`M/D` or `M/D HH:mm`).
 *
 * Midnight timestamps collapse to a date-only label to reduce axis noise on
 * daily-resolution backtests; intraday samples keep the `HH:mm` suffix.
 *
 * @param ts - ISO-8601 timestamp string, or null for synthetic/edge points.
 * @returns The formatted label, or `""` when `ts` is null, or the raw input when
 *   it cannot be parsed into year-month-day parts.
 *
 * @example
 * formatTsLabel("2026-01-05T00:00:00Z"); // "1/5"
 * formatTsLabel("2026-01-05T14:30:00Z"); // "1/5 14:30"
 * formatTsLabel(null);                    // ""
 */
export function formatTsLabel(ts: string | null): string {
  if (!ts) return "";
  const [datePart, timePart] = ts.replace("T", " ").split(" ");
  const [, m, d] = datePart.split("-");
  if (!m || !d) return ts;
  const base = `${parseInt(m, 10)}/${parseInt(d, 10)}`;
  if (timePart && timePart !== "00:00:00" && !timePart.startsWith("00:00")) {
    return `${base} ${timePart.slice(0, 5)}`;
  }
  return base;
}

/**
 * Round to 2 decimals and normalize `-0` to `0`.
 *
 * @param value - The number to round.
 * @returns `value` rounded to 2 decimal places, with negative-zero collapsed to
 *   `0` so downstream `Object.is(-0, 0)` comparisons and serialization stay stable.
 *
 * @remarks Not exported — an internal helper shared by the series builders.
 */
function round2(value: number): number {
  const r = Math.round(value * 100) / 100;
  return r === 0 ? 0 : r;
}

/**
 * Prepare the equity-curve series for charting.
 *
 * Derives a drawdown-from-peak percent series when the points don't already
 * carry `drawdown_pct`. Non-finite equity is coerced to 0 defensively so a
 * single bad sample cannot blow up the axis domain.
 *
 * @param points - Raw equity samples from the backtest results.
 * @returns Chart-ready rows; same length and order as `points`.
 *
 * @example
 * prepareEquitySeries([
 *   { ts: "2026-01-01T00:00:00Z", equity: 100 },
 *   { ts: "2026-01-02T00:00:00Z", equity: 120 }, // new peak
 *   { ts: "2026-01-03T00:00:00Z", equity: 90 },  // -25% from peak 120
 * ]);
 */
export function prepareEquitySeries(points: EquityPoint[]): EquityChartDatum[] {
  let peak = -Infinity;
  // AI-CONTEXT: Carry forward the last finite equity for a non-finite sample rather
  // than substituting 0. Substituting 0 forged a phantom plunge to $0 and a fake
  // -100% drawdown spike for a single bad point; carrying forward keeps the curve
  // flat across the gap (the true "no new data" behavior). The first point, with no
  // prior value, still falls back to 0.
  let lastFinite = 0;
  return points.map((p) => {
    const equity = Number.isFinite(p.equity) ? p.equity : lastFinite;
    if (Number.isFinite(p.equity)) lastFinite = equity;
    if (equity > peak) peak = equity;
    const dd =
      p.drawdown_pct != null && Number.isFinite(p.drawdown_pct)
        ? -Math.abs(p.drawdown_pct)
        : peak > 0
          ? -Math.abs(((peak - equity) / peak) * 100)
          : 0;
    return {
      label: formatTsLabel(p.ts),
      equity: round2(equity),
      drawdown: round2(dd),
    };
  });
}

/**
 * Compute a padded y-domain `[min, max]` for the equity axis.
 *
 * @param data - The prepared equity series.
 * @returns A `[min, max]` tuple padded by 2% of the range (minimum 1 unit) so the
 *   line never touches the chart edges; returns `[0, 1]` for an empty series.
 *
 * @example
 * equityDomain([]); // [0, 1]
 */
export function equityDomain(data: EquityChartDatum[]): [number, number] {
  if (data.length === 0) return [0, 1];
  let min = data[0].equity;
  let max = data[0].equity;
  for (const d of data) {
    if (d.equity < min) min = d.equity;
    if (d.equity > max) max = d.equity;
  }
  const pad = Math.max(Math.abs(max - min) * 0.02, 1);
  return [min - pad, max + pad];
}

/**
 * Linearly interpolate a buy & hold benchmark series.
 *
 * Interpolates from the first equity point to `finalValue`, returning a new array
 * with a `buyHold` key on each row. If the benchmark is unavailable (null /
 * non-finite) or there are fewer than 2 points, returns the input unchanged (no
 * `buyHold` key added).
 *
 * @param data - The prepared equity series.
 * @param finalValue - Final value of the buy & hold benchmark over the same window.
 * @returns A new array of rows, each optionally carrying an interpolated `buyHold`.
 *
 * @example
 * buildBuyHoldSeries(series, 13000); // each row gains buyHold interpolated to 13000
 * buildBuyHoldSeries(series, null);  // unchanged — no buyHold key
 */
export function buildBuyHoldSeries(
  data: EquityChartDatum[],
  finalValue: number | null | undefined,
): Array<EquityChartDatum & { buyHold?: number }> {
  if (finalValue == null || !Number.isFinite(finalValue) || data.length < 2) {
    return data;
  }
  const start = data[0].equity;
  const n = data.length - 1;
  return data.map((d, i) => ({
    ...d,
    buyHold: round2(start + ((finalValue - start) * i) / n),
  }));
}
