import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceDot, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { CurvePoint, EquityNow } from "./performanceTypes";

interface Props {
  data: CurvePoint[];
  /** optional absolute-equity offset D for the secondary "your equity" axis */
  startingEquity?: number | null;
  equityNow?: EquityNow | null;
}

export function EquityCurveChart({ data, startingEquity, equityNow }: Props) {
  const gradId = useId().replace(/:/g, "");
  if (data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-[var(--neu-text-soft)]">
        No closed trades in this range
      </div>
    );
  }
  const rows = data.map((p) => ({
    t: p.t,
    cum_pnl: Math.round(p.cum_pnl * 100) / 100,
    equity: startingEquity != null ? Math.round((startingEquity + p.cum_pnl) * 100) / 100 : undefined,
  }));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={rows}>
        <defs>
          <linearGradient id={`eq-${gradId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--neu-accent)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--neu-accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--neu-border)" strokeDasharray="3 3" />
        <XAxis dataKey="t" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} minTickGap={32} />
        <YAxis yAxisId="pnl" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        {startingEquity != null && (
          <YAxis yAxisId="eq" orientation="right" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        )}
        <Tooltip />
        <Area
          yAxisId="pnl"
          type="monotone"
          dataKey="cum_pnl"
          stroke="var(--neu-accent)"
          fill={`url(#eq-${gradId})`}
        />
        {equityNow && startingEquity != null && (
          <ReferenceDot yAxisId="eq" x={equityNow.t} y={equityNow.equity} r={4} fill="var(--neu-accent)" />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}
