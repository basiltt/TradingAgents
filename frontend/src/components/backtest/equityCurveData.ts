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

/**
 * A cool-off pause window emitted by the backtest engine.
 *
 * The engine clamps, de-duplicates, and merges these before persisting them in
 * `results.summary.cooloff_bands`, so the array this UI receives is already
 * non-overlapping and sorted by `start`. We still defend against malformed rows.
 *
 * @property start - ISO-8601 timestamp when the account entered cool-off (inclusive).
 * @property end - ISO-8601 timestamp when the pause expires (inclusive).
 * @property reason - Which tier armed the pause: one of `success` / `failure` /
 *   `double_success` / `double_failure` (or `unknown` defensively).
 */
export interface CooloffBand {
  start: string;
  end: string;
  reason: string;
}

/**
 * Parse an ISO timestamp to epoch milliseconds.
 *
 * @param ts - ISO-8601 string, or null/undefined.
 * @returns Epoch ms, or null when the input is absent or unparseable. A bare
 *   date/datetime with no zone is parsed by the host as local time — that is
 *   acceptable here because membership only compares it against the band bounds,
 *   which are produced by the same backend serializer.
 */
function tsToMs(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Compute per-row cool-off band membership, parallel to the equity series.
 *
 * recharts renders the equity chart on a *categorical* x-axis (`dataKey="label"`),
 * so timestamp-anchored `ReferenceArea` shading would not line up with the
 * irregular sample spacing. Instead we test each sample's own timestamp against
 * the (already-merged) band windows and return a boolean per row; the chart then
 * paints a full-height shaded `Area` over the contiguous `true` runs.
 *
 * Defensive by construction: a point with a null/unparseable `ts` is never in a
 * band, and a band with unparseable bounds (or start > end) is skipped — so a
 * single bad row can never mark the entire curve as paused.
 *
 * @param points - Raw equity samples (must carry `ts`); same order as the chart rows.
 * @param bands - Cool-off windows from `results.summary.cooloff_bands`, or null.
 * @returns A `boolean[]` the same length and order as `points`.
 *
 * @example
 * computeCooloffMembership(
 *   [{ ts: "2026-01-01T00:00:00Z", equity: 100 },
 *    { ts: "2026-01-02T00:00:00Z", equity: 100 }],
 *   [{ start: "2026-01-01T12:00:00Z", end: "2026-01-03T00:00:00Z", reason: "failure" }],
 * ); // [false, true]
 */
export function computeCooloffMembership(
  points: EquityPoint[],
  bands: CooloffBand[] | null | undefined,
): boolean[] {
  if (!bands || bands.length === 0) return points.map(() => false);
  const windows: Array<[number, number]> = [];
  for (const b of bands) {
    const s = tsToMs(b?.start);
    const e = tsToMs(b?.end);
    if (s == null || e == null || s > e) continue;
    windows.push([s, e]);
  }
  if (windows.length === 0) return points.map(() => false);
  return points.map((p) => {
    const t = tsToMs(p.ts);
    if (t == null) return false;
    return windows.some(([s, e]) => t >= s && t <= e);
  });
}

/**
 * Attach a per-row cool-off band overlay value to the equity rows.
 *
 * recharts shades a band by painting an Area whose value is full-height
 * (`maxEquity`) inside a band and `null` outside it (recharts skips null points),
 * with the Area's `baseValue` set to `minEquity`. This helper produces that field
 * WITHOUT mutating the input rows.
 *
 * OFF-parity guarantee (load-bearing): when `flags` has no `true` entry, the input
 * array is returned **by reference, unchanged** — so a backtest with cool-off OFF
 * renders byte-identically to the pre-feature chart. Callers can assert
 * `buildCooloffChartData(rows, flags, max) === rows` to prove that invariant.
 *
 * @param rows - The equity series (already benchmark-merged), in chart order.
 * @param flags - Per-row band membership, parallel to `rows` (see computeCooloffMembership).
 * @param maxEquity - The y-domain max; in-band rows get this value for a full-height band.
 * @returns The same array (no band present) or a new array with a `cooloffBand` field.
 */
export function buildCooloffChartData<T>(
  rows: T[],
  flags: boolean[],
  maxEquity: number,
): Array<T & { cooloffBand?: number | null }> {
  // OFF parity: return the SAME array by reference. `cooloffBand` is optional, so a
  // plain T is structurally a (T & { cooloffBand? }); the cast just satisfies the
  // unconstrained-generic checker without copying (referential identity is the
  // load-bearing OFF-parity contract — see the test `expect(out).toBe(rows)`).
  if (!flags.some(Boolean)) return rows as Array<T & { cooloffBand?: number | null }>;
  return rows.map((row, i) => ({
    ...row,
    cooloffBand: flags[i] ? maxEquity : null,
  }));
}
