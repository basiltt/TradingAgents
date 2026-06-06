/**
 * Pure data-aggregation helpers for the Analysis tab: monthly returns heatmap,
 * P&L distribution histogram, and trade-duration distribution. Framework-free so
 * the bucketing math is unit-testable without rendering recharts.
 */
import type { BacktestTrade } from "./types";

/* ----------------------------- monthly returns ----------------------------- */

export interface MonthCell {
  year: number;
  month: number; // 1-12
  pnl: number;
  trades: number;
}

export interface MonthlyReturns {
  /** One cell per (year, month) that has at least one closed trade, ascending. */
  cells: MonthCell[];
  /** Per-year totals keyed by year. */
  yearTotals: Record<number, number>;
  years: number[];
}

/** Group closed trades by calendar month (by exit_time) and sum PnL. */
export function aggregateMonthlyReturns(trades: BacktestTrade[]): MonthlyReturns {
  const map = new Map<string, MonthCell>();
  const yearTotals: Record<number, number> = {};
  for (const t of trades) {
    if (!t.exit_time) continue;
    const d = new Date(t.exit_time);
    const year = d.getUTCFullYear();
    const month = d.getUTCMonth() + 1;
    if (!Number.isFinite(year)) continue;
    const key = `${year}-${month}`;
    const pnl = t.pnl ?? 0;
    const cell = map.get(key) ?? { year, month, pnl: 0, trades: 0 };
    cell.pnl += pnl;
    cell.trades += 1;
    map.set(key, cell);
    yearTotals[year] = (yearTotals[year] ?? 0) + pnl;
  }
  const cells = Array.from(map.values()).sort(
    (a, b) => a.year - b.year || a.month - b.month,
  );
  const years = Object.keys(yearTotals)
    .map(Number)
    .sort((a, b) => a - b);
  return { cells, yearTotals, years };
}

/* ----------------------------- generic histogram ----------------------------- */

export interface HistogramBucket {
  /** Inclusive lower edge. */
  start: number;
  /** Exclusive upper edge (inclusive for the final bucket). */
  end: number;
  /** Mid-point label for the x-axis. */
  label: string;
  count: number;
}

export interface HistogramMeta {
  min: number;
  max: number;
  width: number;
  count: number;
}

/** Compute the [min,max,width,count] for `bucketCount` equal-width buckets over
 * the finite values. Returns null for empty input or a degenerate (single value)
 * distribution. Single source of truth for bucket geometry. */
function histogramMeta(values: number[], bucketCount: number): HistogramMeta | null {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return null;
  let min = finite[0];
  let max = finite[0];
  for (const v of finite) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) return null;
  const count = Math.max(1, Number.isFinite(bucketCount) ? Math.floor(bucketCount) : 20);
  return { min, max, width: (max - min) / count, count };
}

/** The bucket index a value falls into given the geometry (final bucket inclusive). */
function bucketIndexOf(value: number, meta: HistogramMeta): number {
  let idx = Math.floor((value - meta.min) / meta.width);
  if (idx >= meta.count) idx = meta.count - 1;
  if (idx < 0) idx = 0;
  return idx;
}

/**
 * Bucket numeric values into `bucketCount` equal-width buckets spanning
 * [min, max]. Returns empty array for empty input. A single distinct value is
 * placed into one degenerate bucket.
 */
export function buildHistogram(values: number[], bucketCount = 20): HistogramBucket[] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return [];
  const meta = histogramMeta(finite, bucketCount);
  if (!meta) {
    // All values identical → one degenerate bucket.
    const v = finite[0];
    return [{ start: v, end: v, label: fmtBucketLabel(v), count: finite.length }];
  }
  const { min, max, width, count: n } = meta;
  const buckets: HistogramBucket[] = Array.from({ length: n }, (_, i) => {
    const start = min + i * width;
    const end = i === n - 1 ? max : min + (i + 1) * width;
    return { start, end, label: fmtBucketLabel((start + end) / 2), count: 0 };
  });
  for (const v of finite) {
    buckets[bucketIndexOf(v, meta)].count += 1;
  }
  return buckets;
}

function fmtBucketLabel(value: number): string {
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
  if (Math.abs(value) >= 1) return value.toFixed(0);
  return value.toFixed(2);
}

/* --------------------------- domain-specific wrappers --------------------------- */

/** Histogram of per-trade PnL (for the P&L distribution chart). */
export function pnlHistogram(trades: BacktestTrade[], bucketCount = 20): HistogramBucket[] {
  return buildHistogram(
    trades.map((t) => t.pnl).filter((v): v is number => v != null),
    bucketCount,
  );
}

export interface DurationBucket extends HistogramBucket {
  winCount: number;
  lossCount: number;
}

/** Hours a trade was open. Null when either timestamp is missing. */
export function tradeDurationHours(t: BacktestTrade): number | null {
  if (!t.entry_time || !t.exit_time) return null;
  const ms = new Date(t.exit_time).getTime() - new Date(t.entry_time).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms / 3_600_000;
}

/**
 * Duration histogram split into win/loss counts per bucket (for the color-coded
 * duration-distribution chart).
 */
export function durationHistogram(
  trades: BacktestTrade[],
  bucketCount = 20,
): DurationBucket[] {
  // Only trades with a measurable duration AND a known PnL participate, so the
  // win/loss split stays consistent with the P&L histogram's population.
  const withDur = trades
    .map((t) => ({ hours: tradeDurationHours(t), pnl: t.pnl }))
    .filter((d): d is { hours: number; pnl: number } => d.hours != null && d.pnl != null);
  const base = buildHistogram(
    withDur.map((d) => d.hours),
    bucketCount,
  );
  if (base.length === 0) return [];
  const out: DurationBucket[] = base.map((b) => ({ ...b, winCount: 0, lossCount: 0 }));
  // Reuse the exact same bucket geometry buildHistogram used (single source of
  // truth) so win/loss counts can never land in a different bucket than counts.
  const meta = histogramMeta(withDur.map((d) => d.hours), bucketCount);
  for (const d of withDur) {
    const idx = meta ? bucketIndexOf(d.hours, meta) : 0; // null meta → single degenerate bucket
    const safeIdx = Math.min(idx, out.length - 1);
    if (d.pnl >= 0) out[safeIdx].winCount += 1;
    else out[safeIdx].lossCount += 1;
  }
  return out;
}

export const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
