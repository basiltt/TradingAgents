import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export interface BenchmarkRow {
  date: string;
  trade_number: number;
  system_pnl: number;
  buy_and_hold: number;
  random_expected: number;
}

interface Props {
  data: BenchmarkRow[];
}

export function BenchmarkChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={300}>
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
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={45}
        />
        <Tooltip
          formatter={(value: number, name: string) => [`${value.toFixed(2)}%`, name]}
          labelFormatter={(label) => `Trade #${label}`}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          type="monotone"
          dataKey="system_pnl"
          name="System PnL"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="buy_and_hold"
          name="Buy & Hold"
          stroke="#9ca3af"
          strokeWidth={1.5}
          strokeDasharray="5 3"
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="random_expected"
          name="Random Expected"
          stroke="#ef4444"
          strokeWidth={1.5}
          strokeDasharray="3 3"
          dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
