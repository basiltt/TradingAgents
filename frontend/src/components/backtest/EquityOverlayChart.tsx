import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useMemo } from "react";
import type { EquityPoint } from "./types";

export interface EquityDataset {
  label: string;
  color: string;
  data: EquityPoint[];
}

/** A color palette for overlaying up to 4 comparison runs. */
export const OVERLAY_COLORS = [
  "var(--neu-accent)",
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#ec4899", // pink
];

interface MergedRow {
  idx: number;
  [seriesKey: string]: number;
}

/**
 * Merge N equity datasets into rows indexed by sample position (0..maxLen-1).
 * Each dataset becomes a `s{i}` numeric key. Datasets of differing lengths are
 * aligned by index; missing tail points are simply absent for that series so
 * recharts draws a shorter line. Returns the rows plus the series metadata.
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

export interface EquityOverlayChartProps {
  datasets: EquityDataset[];
  height?: number;
}

/** Overlays multiple runs' equity curves on a shared axis (comparison view). */
export function EquityOverlayChart({ datasets, height = 320 }: EquityOverlayChartProps) {
  const { rows, series } = useMemo(() => mergeEquityDatasets(datasets), [datasets]);

  if (rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-[var(--neu-text-muted)]"
        style={{ height }}
        data-testid="overlay-empty"
      >
        No equity data to overlay.
      </div>
    );
  }

  const ariaSummary = `Equity comparison of ${series.length} runs: ${series
    .map((s) => s.label)
    .join(", ")}.`;

  return (
    <div data-testid="equity-overlay-chart" role="img" aria-label={ariaSummary}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--neu-stroke-soft)" opacity={0.3} />
          <XAxis dataKey="idx" tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40} />
          <YAxis
            tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v: number) => (v < 0 ? `-$${Math.abs(v).toFixed(0)}` : `$${v.toFixed(0)}`)}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "var(--neu-surface-raised)", border: "1px solid var(--neu-stroke-soft)", borderRadius: 12, fontSize: 11 }}
            formatter={(value: unknown, name: unknown) => {
              const num = Number(value);
              const s = series.find((x) => x.key === name);
              return [num < 0 ? `-$${Math.abs(num).toFixed(2)}` : `$${num.toFixed(2)}`, s?.label ?? String(name)];
            }}
          />
          <Legend formatter={(value: unknown) => series.find((s) => s.key === value)?.label ?? String(value)} />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
