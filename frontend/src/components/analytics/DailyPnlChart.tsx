import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { DailySnapshot } from "@/api/client";

interface Props {
  snapshots: DailySnapshot[];
}

export function DailyPnlChart({ snapshots }: Props) {
  const data = snapshots.map((s) => ({
    date: s.snapshot_date,
    pnl: Math.round(s.realised_pnl * 100) / 100,
  }));

  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: string) => {
            const [, m, d] = v.split("-");
            return `${parseInt(m)}/${parseInt(d)}`;
          }}
        />
        <YAxis
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => v < 0 ? `-$${Math.abs(v).toFixed(0)}` : `$${v.toFixed(0)}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            fontSize: 12,
          }}
          formatter={(value: number) => [value < 0 ? `-$${Math.abs(value).toFixed(2)}` : `$${value.toFixed(2)}`, "Realized P&L"]}
          labelFormatter={(label: string) => {
            const [y, m, d] = label.split("-");
            return `${parseInt(m)}/${parseInt(d)}/${y}`;
          }}
        />
        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
          {data.map((entry, index) => (
            <Cell key={index} fill={entry.pnl >= 0 ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
