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
import { type EquityDataset, mergeEquityDatasets } from "./equityOverlayData";

// AI-CONTEXT: EquityDataset, OVERLAY_COLORS, MergedRow, and mergeEquityDatasets
// live in ./equityOverlayData so this file exports only the component (React Fast
// Refresh / react-refresh/only-export-components). Import what the component needs
// from ./equityOverlayData directly; do NOT re-export or the rule re-triggers.

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
