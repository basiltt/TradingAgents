import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { DailySnapshot } from "@/api/client";

interface Props {
  snapshots: DailySnapshot[];
}

export function DrawdownChart({ snapshots }: Props) {
  const gradId = useId().replace(/:/g, "");
  const data = snapshots.map((s) => ({
    date: s.snapshot_date,
    drawdown: -(Math.abs(Math.round(s.drawdown_pct * 100) / 100)),
  }));

  if (data.length === 0) return null;

  const minDD = Math.min(data.reduce((min, d) => d.drawdown < min ? d.drawdown : min, data[0].drawdown) * 1.1, -0.1);

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id={`dd-${gradId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
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
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          domain={[minDD, 0]}
          tickFormatter={(v: number) => `${v.toFixed(1)}%`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            fontSize: 12,
          }}
          formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
          labelFormatter={(label: string) => {
            if (label.includes(" ")) {
              const [datePart, time] = label.split(" ");
              const [y, m, d] = datePart.split("-");
              return `${parseInt(m)}/${parseInt(d)}/${y} ${time}`;
            }
            const [y, m, d] = label.split("-");
            return `${parseInt(m)}/${parseInt(d)}/${y}`;
          }}
        />
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke="#ef4444"
          strokeWidth={1.5}
          fill={`url(#dd-${gradId})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
