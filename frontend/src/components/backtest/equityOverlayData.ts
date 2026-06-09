/**
 * @module equityOverlayData
 *
 * Pure data-shaping helpers for the multi-run equity-overlay comparison chart.
 *
 * Architectural role: presentation-layer transforms that merge N independent
 * `EquityPoint[]` series into index-aligned rows for recharts. Separated from
 * {@link ../EquityOverlayChart} (the React component) so the helpers are
 * unit-testable in isolation and so the component file exports only a component
 * (React Fast Refresh / `react-refresh/only-export-components`).
 *
 * Boundary: no rendering, no I/O, no state — every export is a pure function or
 * constant.
 */
import type { EquityPoint } from "./types";

/**
 * One labeled equity series to overlay on the comparison chart.
 *
 * @property label - Human-readable run label shown in the legend/tooltip.
 * @property color - Stroke color (typically drawn from {@link OVERLAY_COLORS}).
 * @property data - The run's equity samples.
 */
export interface EquityDataset {
  label: string;
  color: string;
  data: EquityPoint[];
}

/**
 * Color palette for overlaying up to 4 comparison runs.
 *
 * @remarks Must contain at least `MAX_COMPARE_RUNS` entries (see
 * ./comparisonBasket). Callers index with `OVERLAY_COLORS[i % OVERLAY_COLORS.length]`
 * so a shorter palette wraps rather than producing `undefined` strokes.
 */
export const OVERLAY_COLORS = [
  "var(--neu-accent)",
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#ec4899", // pink
];

/**
 * A merged chart row keyed by sample index.
 *
 * @property idx - Zero-based sample position shared across all overlaid series.
 * @remarks Additional `s{i}` numeric keys (one per dataset) are added dynamically;
 *   a key is absent when that dataset has no finite sample at `idx`.
 */
export interface MergedRow {
  idx: number;
  [seriesKey: string]: number;
}

/**
 * Merge N equity datasets into rows indexed by sample position (`0..maxLen-1`).
 *
 * Each dataset becomes an `s{i}` numeric key. Datasets of differing lengths are
 * aligned by index; missing tail points are simply absent for that series so
 * recharts draws a shorter line (with `connectNulls`). Non-finite equity values
 * are dropped (absent key) rather than charted as 0.
 *
 * @param datasets - The labeled series to overlay.
 * @returns `rows` (the merged, index-aligned data) and `series` (per-dataset
 *   metadata: stable key, label, color).
 *
 * @example
 * const { rows, series } = mergeEquityDatasets([
 *   { label: "A", color: OVERLAY_COLORS[0], data: [{ ts: "…", equity: 100 }] },
 *   { label: "B", color: OVERLAY_COLORS[1], data: [{ ts: "…", equity: 90 }] },
 * ]);
 * // rows[0] === { idx: 0, s0: 100, s1: 90 }
 */
export function mergeEquityDatasets(datasets: EquityDataset[]): {
  rows: MergedRow[];
  series: Array<{ key: string; label: string; color: string }>;
} {
  const series = datasets.map((d, i) => ({
    key: `s${i}`,
    label: d.label,
    color: d.color,
  }));
  const maxLen = datasets.reduce((m, d) => Math.max(m, d.data.length), 0);
  const rows: MergedRow[] = [];
  for (let idx = 0; idx < maxLen; idx++) {
    const row: MergedRow = { idx };
    datasets.forEach((d, i) => {
      const pt = d.data[idx];
      if (pt && Number.isFinite(pt.equity)) {
        row[`s${i}`] = Math.round(pt.equity * 100) / 100;
      }
    });
    rows.push(row);
  }
  return { rows, series };
}
