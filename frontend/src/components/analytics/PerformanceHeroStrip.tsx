import { AreaChart, Area, ResponsiveContainer } from "recharts";
import type { PerformanceOverview } from "./performanceTypes";
import { formatUsd, formatPct, formatRatio, DASH } from "@/lib/format";

interface Props {
  overview: PerformanceOverview;
}

const MIN_PREV_TRADES = 3;

function DeltaChip({ delta, suffix = "" }: { delta: number; suffix?: string }) {
  const up = delta >= 0;
  return (
    <span
      data-testid="delta-chip"
      className={`ml-1 inline-flex items-center text-xs font-semibold ${up ? "text-emerald-500" : "text-rose-500"}`}
      aria-label={`change ${up ? "up" : "down"} ${Math.abs(delta).toFixed(2)}${suffix}`}
    >
      {up ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}{suffix}
    </span>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div className="h-8" aria-hidden="true">
      <ResponsiveContainer width="100%" height={32}>
        <AreaChart data={data}>
          <Area type="monotone" dataKey="v" stroke={color} fill={color} fillOpacity={0.15} strokeWidth={1.5} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Card({
  label, value, ariaValue, delta, deltaSuffix, sparkline,
}: {
  label: string;
  value: string;
  ariaValue: string;
  delta?: number | null;
  deltaSuffix?: string;
  sparkline?: React.ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={`${label}: ${ariaValue}`}
      className="neu-surface-base neu-surface-raised col-span-2 rounded-[var(--neu-radius-md)] p-3 sm:p-4 md:col-span-1"
    >
      <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">{label}</div>
      <div className="mt-1 flex items-baseline text-lg font-black tabular-nums text-[var(--neu-text-strong)]">
        {value}
        {delta != null && <DeltaChip delta={delta} suffix={deltaSuffix} />}
      </div>
      {sparkline}
    </div>
  );
}

export function PerformanceHeroStrip({ overview }: Props) {
  const k = overview.kpis;
  const prev = overview.kpis_prev;
  const showDelta = !!prev && prev.total_trades >= MIN_PREV_TRADES;
  const equitySpark = overview.equity_curve.map((p) => p.cum_pnl);
  const pnlSpark = overview.daily_pnl.map((p) => p.pnl);

  const d = (cur: number | null, p: number | null | undefined) =>
    showDelta && cur != null && p != null ? cur - p : undefined;

  return (
    <div className="sticky top-0 z-10 grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-5">
      <Card
        label="Total Equity (now)"
        value={k.total_equity != null ? formatUsd(k.total_equity) : DASH}
        ariaValue={k.total_equity != null ? `${k.total_equity} USDT` : "not available"}
        delta={d(k.total_equity, prev?.total_equity)}
        sparkline={<Sparkline values={equitySpark} color="var(--neu-accent)" />}
      />
      <Card
        label="Net P&L"
        value={formatUsd(k.net_pnl, { sign: true })}
        ariaValue={`${k.net_pnl} USDT`}
        delta={d(k.net_pnl, prev?.net_pnl)}
        sparkline={<Sparkline values={pnlSpark} color="var(--neu-success)" />}
      />
      <Card
        label="Win Rate"
        value={k.win_rate != null ? formatPct(k.win_rate) : DASH}
        ariaValue={k.win_rate != null ? `${k.win_rate} percent` : "not available"}
        delta={d(k.win_rate, prev?.win_rate)}
        deltaSuffix="%"
      />
      <Card
        label="Sharpe"
        value={k.sharpe_ratio != null ? formatRatio(k.sharpe_ratio) : DASH}
        ariaValue={k.sharpe_ratio != null ? `${k.sharpe_ratio}` : "not available"}
        delta={d(k.sharpe_ratio, prev?.sharpe_ratio)}
      />
      <Card
        label="Max DD"
        value={k.max_drawdown_pct != null ? formatPct(k.max_drawdown_pct) : DASH}
        ariaValue={k.max_drawdown_pct != null ? `${k.max_drawdown_pct} percent` : "not available"}
        delta={d(k.max_drawdown_pct, prev?.max_drawdown_pct)}
        deltaSuffix="%"
      />
    </div>
  );
}
