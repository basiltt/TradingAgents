import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { DailySnapshot } from "@/api/client";

interface Props {
  snapshots: DailySnapshot[];
}

export function EquityCurveChart({ snapshots }: Props) {
  const gradId = useId().replace(/:/g, "");
  const data = snapshots.map((s) => ({
    date: s.snapshot_date,
    equity: Math.round(s.equity * 100) / 100,
    peak: Math.round(s.peak_equity * 100) / 100,
  }));

  if (data.length === 0) return null;

  const minVal = data.reduce((min, d) => d.equity < min ? d.equity : min, data[0].equity);
  const maxVal = data.reduce((max, d) => {
    const v = Math.max(d.equity, d.peak);
    return v > max ? v : max;
  }, Math.max(data[0].equity, data[0].peak));
  const pad = Math.max(Math.abs(maxVal - minVal) * 0.02, 1);
  const minEquity = minVal - pad;
  const maxEquity = maxVal + pad;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id={`eq-${gradId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: string) => {
            if (v.includes(" ")) {
              const [, time] = v.split(" ");
              return time.slice(0, 5);
            }
            const [, m, d] = v.split("-");
            return `${parseInt(m)}/${parseInt(d)}`;
          }}
        />
        <YAxis
          tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          domain={[minEquity, maxEquity]}
          tickFormatter={(v: number) => v < 0 ? `-$${Math.abs(v).toFixed(0)}` : `$${v.toFixed(0)}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            fontSize: 11,
          }}
          formatter={(value: unknown, name: unknown) => [
            Number(value) < 0 ? `-$${Math.abs(Number(value)).toFixed(2)}` : `$${Number(value).toFixed(2)}`,
            name === "equity" ? "Equity" : "Peak",
          ]}
          labelFormatter={(label: unknown) => {
            const s = String(label);
            if (s.includes(" ")) {
              const [datePart, time] = s.split(" ");
              const [y, m, d] = datePart.split("-");
              return `${parseInt(m)}/${parseInt(d)}/${y} ${time}`;
            }
            const [y, m, d] = s.split("-");
            return `${parseInt(m)}/${parseInt(d)}/${y}`;
          }}
        />
        <Area
          type="monotone"
          dataKey="peak"
          stroke="var(--muted-foreground)"
          strokeDasharray="4 4"
          strokeWidth={1}
          fill="none"
          dot={false}
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="var(--primary)"
          strokeWidth={2}
          fill={`url(#eq-${gradId})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
