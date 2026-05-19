import { formatPnl } from "@/components/trades/utils";

export function PnLDisplay({ value }: { value: number | null }) {
  if (value == null || isNaN(value)) return <span className="text-muted-foreground/40">—</span>;
  const isPositive = value > 0;
  const isZero = value === 0;
  const color = isPositive ? "text-emerald-400" : isZero ? "text-muted-foreground/50" : "text-red-400";
  return <span className={`${color} font-mono tabular-nums`}>{formatPnl(value)}</span>;
}
