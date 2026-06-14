import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { DailyPnlPoint } from "./performanceTypes";

interface Props {
  data: DailyPnlPoint[];
}

export function DailyPnlChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <figure
        role="img"
        aria-label="Daily P&L chart: no data"
        className="flex h-[260px] items-center justify-center text-[var(--neu-text-soft)]"
      >
        No daily P&L data
      </figure>
    );
  }
  const rows = data.map((p) => ({ date: p.date, pnl: Math.round(p.pnl * 100) / 100 }));
  return (
    <figure role="img" aria-label="Daily profit and loss bars">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={rows}>
          <CartesianGrid stroke="var(--neu-border)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} minTickGap={24} />
          <YAxis tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
          <Tooltip />
          <Bar dataKey="pnl">
            {rows.map((r, i) => (
              <Cell key={i} fill={r.pnl >= 0 ? "var(--neu-success)" : "var(--neu-danger)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}
