import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export interface RegimeRow {
  regime: string;
  total: number;
  wins: number;
  win_rate: number;
  avg_pnl_pct: number;
}

interface Props {
  data: RegimeRow[];
}

export function RegimeBreakdownChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.15} />
        <XAxis
          dataKey="regime"
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          yAxisId="left"
          tickFormatter={(v) => `${v}%`}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={45}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          tickFormatter={(v) => `${v}%`}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={45}
        />
        <Tooltip
          formatter={(value: number, name: string) => [`${value.toFixed(1)}%`, name]}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar yAxisId="left" dataKey="win_rate" name="Win Rate %" fill="#10b981" radius={[4, 4, 0, 0]} />
        <Bar yAxisId="right" dataKey="avg_pnl_pct" name="Avg PnL %" fill="#6366f1" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
