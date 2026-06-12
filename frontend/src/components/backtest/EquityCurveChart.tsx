import {
  AreaChart,
  Area,
  Line,
  Legend,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useId, useMemo } from "react";
import type { EquityPoint } from "./types";
import {
  prepareEquitySeries,
  equityDomain,
  buildBuyHoldSeries,
  computeCooloffMembership,
  buildCooloffChartData,
  type CooloffBand,
} from "./equityCurveData";

// AI-CONTEXT: Pure data-shaping helpers (formatTsLabel, prepareEquitySeries,
// equityDomain, buildBuyHoldSeries, EquityChartDatum) live in ./equityCurveData
// so this file exports only the component — a requirement for React Fast Refresh
// (react-refresh/only-export-components). Import only the helpers this component
// uses; tests import the rest (e.g. formatTsLabel) from ./equityCurveData directly.

export interface EquityCurveChartProps {
  equityCurve: EquityPoint[];
  height?: number;
  showDrawdown?: boolean;
  /** Final value of a buy & hold benchmark over the same window. When provided,
   * a dashed reference line is interpolated from the starting equity to here. */
  buyHoldFinalValue?: number | null;
  /** Cool-off pause windows from `results.summary.cooloff_bands`. When present and
   * non-empty, the samples that fall inside a window are shaded as full-height
   * bands behind the equity line. Absent/empty → no shading (the pre-feature look). */
  cooloffBands?: CooloffBand[] | null;
}

export function EquityCurveChart({
  equityCurve,
  height = 320,
  showDrawdown = true,
  buyHoldFinalValue,
  cooloffBands,
}: EquityCurveChartProps) {
  const gradId = useId().replace(/:/g, "");
  // ~2000 points → memoize the map + domain so resize/tab re-renders don't rebuild both charts.
  const data = useMemo(() => prepareEquitySeries(equityCurve), [equityCurve]);

  // Per-row cool-off membership, parallel to `data`. The equity x-axis is
  // categorical (dataKey="label"), so we shade via a full-height Area keyed off a
  // boolean-derived value rather than timestamp-anchored ReferenceAreas (which
  // would not align with irregular sample spacing). See computeCooloffMembership.
  const cooloffFlags = useMemo(
    () => computeCooloffMembership(equityCurve, cooloffBands),
    [equityCurve, cooloffBands],
  );
  const hasCooloff = useMemo(() => cooloffFlags.some(Boolean), [cooloffFlags]);

  const dataWithBenchmark = useMemo(
    () => buildBuyHoldSeries(data, buyHoldFinalValue),
    [data, buyHoldFinalValue],
  );

  // Domain must span BOTH the equity and (when present) the benchmark line, or a
  // far-above/below buy&hold line would be clipped off the axis.
  const [minEquity, maxEquity] = useMemo(() => {
    const [lo, hi] = equityDomain(data);
    if (buyHoldFinalValue != null && Number.isFinite(buyHoldFinalValue) && data.length >= 2) {
      const start = data[0].equity;
      return [Math.min(lo, start, buyHoldFinalValue), Math.max(hi, start, buyHoldFinalValue)];
    }
    return [lo, hi];
  }, [data, buyHoldFinalValue]);

  // Attach a per-row cool-off overlay value: full-height (maxEquity) for in-band
  // samples, null elsewhere. When no row is in a band, buildCooloffChartData returns
  // dataWithBenchmark BY REFERENCE — byte-for-byte the pre-feature chart.
  const chartData = useMemo(
    () => buildCooloffChartData(dataWithBenchmark, cooloffFlags, maxEquity),
    [dataWithBenchmark, cooloffFlags, maxEquity],
  );

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-[var(--neu-text-muted)]"
        style={{ height }}
        data-testid="equity-chart-empty"
      >
        No equity data available.
      </div>
    );
  }

  // Text summary for screen readers (the SVG itself is not accessible).
  const first = data[0];
  const last = data[data.length - 1];
  const worstDd = data.reduce((min, d) => (d.drawdown < min ? d.drawdown : min), 0);
  const ariaSummary =
    `Equity curve from ${first.label} to ${last.label}: ` +
    `start $${first.equity.toLocaleString("en-US")}, ` +
    `end $${last.equity.toLocaleString("en-US")}, ` +
    `worst drawdown ${worstDd.toFixed(1)}%.`;

  return (
    <div data-testid="equity-curve-chart">
      <div role="img" aria-label={ariaSummary}>
        <ResponsiveContainer width="100%" height={height}>
          <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id={`eq-${gradId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="var(--neu-accent)" stopOpacity={0.32} />
              <stop offset="95%" stopColor="var(--neu-accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--neu-stroke-soft)" opacity={0.3} />
          <XAxis
            dataKey="label"
            tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            minTickGap={32}
          />
          <YAxis
            tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            domain={[minEquity, maxEquity]}
            tickFormatter={(v: number) =>
              v < 0 ? `-$${Math.abs(v).toFixed(0)}` : `$${v.toFixed(0)}`
            }
            width={56}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--neu-surface-raised)",
              border: "1px solid var(--neu-stroke-soft)",
              borderRadius: "12px",
              fontSize: 11,
            }}
            formatter={(value: unknown, name: unknown) => {
              const num = Number(value);
              if (name === "drawdown") return [`${num.toFixed(2)}%`, "Drawdown"];
              const usd = num < 0 ? `-$${Math.abs(num).toFixed(2)}` : `$${num.toFixed(2)}`;
              // name is the series' `name` prop ("Equity" / "Buy & Hold").
              return [usd, name === "Buy & Hold" ? "Buy & Hold" : "Equity"];
            }}
          />
          {hasCooloff ? (
            <Area
              type="stepAfter"
              dataKey="cooloffBand"
              baseValue={minEquity}
              stroke="none"
              fill="var(--neu-warning)"
              fillOpacity={0.14}
              dot={false}
              activeDot={false}
              connectNulls={false}
              isAnimationActive={false}
              tooltipType="none"
              legendType="none"
              name="cooloff"
            />
          ) : null}
          <Area
            type="monotone"
            dataKey="equity"
            stroke="var(--neu-accent)"
            strokeWidth={2}
            fill={`url(#eq-${gradId})`}
            dot={false}
            isAnimationActive={false}
            name="Equity"
          />
          {buyHoldFinalValue != null && Number.isFinite(buyHoldFinalValue) && data.length >= 2 ? (
            <>
              <Line
                type="monotone"
                dataKey="buyHold"
                stroke="var(--neu-text-muted)"
                strokeWidth={1.5}
                strokeDasharray="5 4"
                dot={false}
                isAnimationActive={false}
                name="Buy & Hold"
              />
              {/* Legend labels come from each series' `name` prop (Equity / Buy & Hold). */}
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </>
          ) : null}
        </AreaChart>
      </ResponsiveContainer>

      {showDrawdown ? (
        <ResponsiveContainer width="100%" height={Math.round(height * 0.45)}>
          <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
            <defs>
              <linearGradient id={`dd-${gradId}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--neu-danger)" stopOpacity={0.05} />
                <stop offset="95%" stopColor="var(--neu-danger)" stopOpacity={0.32} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--neu-stroke-soft)" opacity={0.3} />
            <XAxis dataKey="label" tick={false} axisLine={false} tickLine={false} height={4} />
            <YAxis
              tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              width={56}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--neu-surface-raised)",
                border: "1px solid var(--neu-stroke-soft)",
                borderRadius: "12px",
                fontSize: 11,
              }}
              formatter={(value: unknown) => [`${Number(value).toFixed(2)}%`, "Drawdown"]}
            />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke="var(--neu-danger)"
              strokeWidth={1.5}
              fill={`url(#dd-${gradId})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : null}
      </div>
    </div>
  );
}
