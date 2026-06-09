import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { BacktestTrade } from "./types";
import {
  aggregateMonthlyReturns,
  pnlHistogram,
  durationHistogram,
  MONTH_LABELS,
  type MonthCell,
} from "./analysis";
import { formatUsd, pnlColorClass } from "./format";

/* ------------------------------ monthly heatmap ------------------------------ */

// AI-CONTEXT: Heatmap fill colors as raw "R, G, B" triples (composed into rgba()
// with a computed alpha). Emerald = positive PnL, rose = negative — the same
// semantic palette as the text-emerald-500 / text-rose-500 utility classes used
// elsewhere; kept as RGB strings here because the alpha is dynamic per cell.
const HEAT_POSITIVE_RGB = "16, 185, 129"; // emerald-500
const HEAT_NEGATIVE_RGB = "244, 63, 94"; // rose-500

/** Background color for a heat cell, scaled by |pnl| relative to the max. */
function heatStyle(pnl: number, maxAbs: number): React.CSSProperties {
  if (maxAbs === 0) return {};
  const intensity = Math.min(1, Math.abs(pnl) / maxAbs);
  const alpha = 0.12 + intensity * 0.5;
  const color = pnl >= 0 ? HEAT_POSITIVE_RGB : HEAT_NEGATIVE_RGB;
  return { backgroundColor: `rgba(${color}, ${alpha.toFixed(2)})` };
}

function MonthlyHeatmap({ trades }: { trades: BacktestTrade[] }) {
  const { cells, yearTotals, years } = useMemo(
    () => aggregateMonthlyReturns(trades),
    [trades],
  );

  const cellByKey = useMemo(() => {
    const map = new Map<string, MonthCell>();
    for (const c of cells) map.set(`${c.year}-${c.month}`, c);
    return map;
  }, [cells]);

  const maxAbs = useMemo(
    () => cells.reduce((m, c) => Math.max(m, Math.abs(c.pnl)), 0),
    [cells],
  );

  if (cells.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-[var(--neu-text-muted)]" data-testid="heatmap-empty">
        No monthly data.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto" data-testid="monthly-heatmap">
      <table className="w-full border-separate border-spacing-1 text-center text-[0.72rem]">
        <caption className="sr-only">Monthly returns heatmap</caption>
        <thead>
          <tr>
            <th scope="col" className="px-2 py-1 text-left text-[var(--neu-text-muted)]">Year</th>
            {MONTH_LABELS.map((mLabel) => (
              <th key={mLabel} scope="col" className="px-1 py-1 text-[var(--neu-text-muted)]">
                {mLabel}
              </th>
            ))}
            <th scope="col" className="px-2 py-1 text-[var(--neu-text-muted)]">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year}>
              <th scope="row" className="px-2 py-1 text-left font-medium text-[var(--neu-text-strong)]">
                {year}
              </th>
              {MONTH_LABELS.map((_, i) => {
                const cell = cellByKey.get(`${year}-${i + 1}`);
                const desc = cell
                  ? `${MONTH_LABELS[i]} ${year}: ${formatUsd(cell.pnl, { sign: true })} (${cell.trades} trades)`
                  : undefined;
                return (
                  <td
                    key={i}
                    className="rounded px-1 py-1 tabular-nums text-[var(--neu-text-strong)]"
                    style={cell ? heatStyle(cell.pnl, maxAbs) : undefined}
                    title={desc}
                    aria-label={desc}
                  >
                    {cell ? Math.round(cell.pnl) : ""}
                  </td>
                );
              })}
              <td className={cn("px-2 py-1 font-semibold tabular-nums", pnlColorClass(yearTotals[year]))}>
                {formatUsd(yearTotals[year], { sign: true })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------ pnl histogram ------------------------------ */

function PnlHistogram({ trades }: { trades: BacktestTrade[] }) {
  const data = useMemo(() => pnlHistogram(trades, 21), [trades]);
  if (data.length === 0) {
    return <p className="py-6 text-center text-sm text-[var(--neu-text-muted)]" data-testid="pnl-hist-empty">No trade data.</p>;
  }
  const total = data.reduce((s, b) => s + b.count, 0);
  return (
    <div data-testid="pnl-histogram" role="img" aria-label={`Profit and loss distribution across ${total} trades, bucketed by PnL.`}>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--neu-stroke-soft)" opacity={0.3} />
          <XAxis dataKey="label" tick={{ fill: "var(--neu-text-muted)", fontSize: 9 }} tickLine={false} axisLine={false} interval={2} />
          <YAxis tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} width={36} />
          <Tooltip
            contentStyle={{ backgroundColor: "var(--neu-surface-raised)", border: "1px solid var(--neu-stroke-soft)", borderRadius: 12, fontSize: 11 }}
            formatter={(v: unknown) => [`${v} trades`, "Count"]}
          />
          <Bar dataKey="count" isAnimationActive={false}>
            {data.map((b, i) => (
              <Cell key={i} fill={b.start >= 0 ? "var(--neu-accent)" : "var(--neu-danger)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------- duration distribution --------------------------- */

function DurationDistribution({ trades }: { trades: BacktestTrade[] }) {
  const data = useMemo(() => durationHistogram(trades, 16), [trades]);
  if (data.length === 0) {
    return <p className="py-6 text-center text-sm text-[var(--neu-text-muted)]" data-testid="duration-hist-empty">No duration data.</p>;
  }
  const wins = data.reduce((s, b) => s + b.winCount, 0);
  const losses = data.reduce((s, b) => s + b.lossCount, 0);
  return (
    <div data-testid="duration-distribution" role="img" aria-label={`Trade duration distribution: ${wins} winners and ${losses} losers bucketed by hours held.`}>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--neu-stroke-soft)" opacity={0.3} />
          <XAxis dataKey="label" tick={{ fill: "var(--neu-text-muted)", fontSize: 9 }} tickLine={false} axisLine={false} interval={1} />
          <YAxis tick={{ fill: "var(--neu-text-muted)", fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} width={36} />
          <Tooltip
            contentStyle={{ backgroundColor: "var(--neu-surface-raised)", border: "1px solid var(--neu-stroke-soft)", borderRadius: 12, fontSize: 11 }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="winCount" stackId="d" fill="var(--neu-accent)" name="Winners" isAnimationActive={false} />
          <Bar dataKey="lossCount" stackId="d" fill="var(--neu-danger)" name="Losers" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------------- the tab --------------------------------- */

export interface BacktestAnalysisTabProps {
  trades: BacktestTrade[];
}

export function BacktestAnalysisTab({ trades }: BacktestAnalysisTabProps) {
  return (
    <div className="flex flex-col gap-5" data-testid="backtest-analysis-tab">
      <Card>
        <CardHeader>
          <CardTitle>Monthly Returns</CardTitle>
        </CardHeader>
        <CardContent>
          <MonthlyHeatmap trades={trades} />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>P&amp;L Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <PnlHistogram trades={trades} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Trade Duration</CardTitle>
          </CardHeader>
          <CardContent>
            <DurationDistribution trades={trades} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
