import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

export interface CalibrationRow {
  tier: string;
  total: number;
  wins: number;
  win_rate: number;
}

interface Props {
  data: CalibrationRow[];
}

export function CalibrationChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.15} />
        <XAxis
          dataKey="tier"
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
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
          contentStyle={{ fontSize: 12 }}
        />
        <ReferenceLine y={50} stroke="#6366f1" strokeDasharray="4 2" strokeOpacity={0.7} label={{ value: "50%", position: "right", fontSize: 10 }} />
        <Bar dataKey="win_rate" name="Win Rate" fill="#10b981" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
