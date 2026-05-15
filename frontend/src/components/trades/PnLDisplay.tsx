import { formatPnl } from "@/components/trades/utils";

export function PnLDisplay({ value }: { value: number | null }) {
  if (value == null || isNaN(value)) return <span className="text-gray-400">--</span>;
  const isPositive = value > 0;
  const isZero = value === 0;
  const color = isPositive ? "text-green-400" : isZero ? "text-gray-400" : "text-red-400";
  const arrow = isPositive ? "↑ " : isZero ? "" : "↓ ";
  return <span className={color}>{arrow}{formatPnl(value)}</span>;
}
