import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { DrawdownPoint } from "./performanceTypes";

interface Props {
  data: DrawdownPoint[];
}

export function DrawdownChart({ data }: Props) {
  const gradId = useId().replace(/:/g, "");
  if (data.length === 0) {
    return (
      <figure
        role="img"
        aria-label="Drawdown chart: no data"
        className="flex h-[260px] items-center justify-center text-[var(--neu-text-soft)]"
      >
        No drawdown data
      </figure>
    );
  }
  const rows = data.map((p) => ({
    t: p.t,
    dd: Math.round((p.drawdown_pct ?? p.drawdown_abs ?? 0) * 100) / 100,
  }));
  const usesPct = data.some((p) => p.drawdown_pct != null);
  return (
    <figure role="img" aria-label="Drawdown underwater chart">
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={rows}>
          <defs>
            <linearGradient id={`dd-${gradId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--neu-danger)" stopOpacity={0} />
              <stop offset="100%" stopColor="var(--neu-danger)" stopOpacity={0.35} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--neu-stroke-soft)" strokeDasharray="3 3" />
          <XAxis dataKey="t" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} minTickGap={32} />
          <YAxis
            tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }}
            tickFormatter={(v) => (usesPct ? `${v}%` : `${v}`)}
          />
          <Tooltip />
          <Area type="monotone" dataKey="dd" stroke="var(--neu-danger)" fill={`url(#dd-${gradId})`} />
        </AreaChart>
      </ResponsiveContainer>
    </figure>
  );
}
