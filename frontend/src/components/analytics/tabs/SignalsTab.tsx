import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useSignalSummary, useSignalWinRate } from "../hooks/usePerformance";
import { formatPct } from "@/lib/format";

interface Props {
  scope: string;
}

/**
 * Signals tab. Coverage-gated (spec §4.4): the signal_performance table only has rows
 * for trades placed from scanner signals, so for manual/cycle-only accounts it is empty.
 * When summary.total_trades === 0 we show an honest empty card instead of a blank/0.0
 * surface. v1 ships the rolling win-rate view; calibration/benchmark/regime/decay are a
 * follow-up gated on confirmed coverage.
 */
export function SignalsTab({ scope }: Props) {
  const { data: summary, isLoading } = useSignalSummary(scope);
  const { data: winRate } = useSignalWinRate(scope);

  if (isLoading || !summary) {
    return <div className="h-40 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />;
  }

  if (summary.total_trades === 0) {
    return (
      <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-10 text-center">
        <p className="text-[var(--neu-text-strong)]">No signal analytics yet</p>
        <p className="mt-1 text-[var(--neu-text-soft)]">
          Signal analytics become available once trades are placed from scanner signals.
        </p>
      </div>
    );
  }

  const series = (winRate ?? []).map((p) => ({ x: p.trade_number, wr: Math.round(p.win_rate * 1000) / 10 }));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Signals" value={String(summary.total_trades)} />
        <Stat label="Win Rate" value={formatPct(summary.win_rate * 100)} />
        <Stat label="Avg P&L" value={formatPct(summary.avg_pnl_pct)} />
        <Stat label="Streak" value={String(summary.current_streak)} />
      </div>
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Rolling Win Rate</h3>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={series}>
            <CartesianGrid stroke="var(--neu-stroke-soft)" strokeDasharray="3 3" />
            <XAxis dataKey="x" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip />
            <Line type="monotone" dataKey="wr" stroke="var(--neu-accent)" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-3">
      <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">{label}</div>
      <div className="mt-1 text-lg font-black tabular-nums text-[var(--neu-text-strong)]">{value}</div>
    </div>
  );
}
