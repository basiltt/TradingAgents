import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

export interface WinRateRow {
  date: string;
  win_rate: number;
  trade_number: number;
}

interface Props {
  data: WinRateRow[];
}

export function RollingWinRateChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.15} />
        <XAxis
          dataKey="trade_number"
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          label={{ value: "Trade #", position: "insideBottom", offset: -2, fontSize: 10 }}
        />
        <YAxis
          tickFormatter={(v) => `${v}%`}
          domain={[0, 100]}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={40}
        />
        <Tooltip
          formatter={(value: number) => [`${value.toFixed(1)}%`, "Win Rate"]}
          labelFormatter={(label) => `Trade #${label}`}
          contentStyle={{ fontSize: 12 }}
        />
        <ReferenceLine y={50} stroke="#6366f1" strokeDasharray="4 2" strokeOpacity={0.7} label={{ value: "50%", position: "right", fontSize: 10 }} />
        <Line
          type="monotone"
          dataKey="win_rate"
          name="Win Rate"
          stroke="#10b981"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
