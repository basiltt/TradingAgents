import { useAppSelector } from "@/store";
import { selectActiveTradeAggregates, selectActiveTradesList } from "@/components/trades/selectors";
import { useTradeStats } from "@/components/trades/hooks/useTradeStats";
import { Skeleton } from "@/components/ui/skeleton";

function formatUsd(value: number | null): string {
  if (value == null) return "--";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function TradeStats() {
  const activeTab = useAppSelector((s) => s.trades.activeTab);
  const aggregates = useAppSelector(selectActiveTradeAggregates);
  const trades = useAppSelector(selectActiveTradesList);
  const { data: stats, isLoading } = useTradeStats();

  if (activeTab === "active") {
    const longCount = trades.filter((t) => t.side === "Buy").length;
    const shortCount = trades.filter((t) => t.side === "Sell").length;
    const totalExposure = trades.reduce((acc, t) => acc + (t.qty * (t.entry_price ?? 0)), 0);

    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <Metric
          label="Positions"
          value={String(aggregates.tradeCount)}
          sub={
            <span className="text-[10px] font-medium">
              <span className="text-emerald-400">{longCount}L</span>
              <span className="px-1 text-muted-foreground/40">|</span>
              <span className="text-red-400">{shortCount}S</span>
            </span>
          }
        />
        <Metric
          label="Total PnL"
          value={formatUsd(aggregates.totalPnl)}
          valueColor={aggregates.totalPnl > 0 ? "profit" : aggregates.totalPnl < 0 ? "loss" : "neutral"}
        />
        <Metric
          label="Unrealized"
          value={formatUsd(aggregates.totalUnrealizedPnl)}
          valueColor={aggregates.totalUnrealizedPnl > 0 ? "profit" : aggregates.totalUnrealizedPnl < 0 ? "loss" : "neutral"}
        />
        <Metric
          label="Realized"
          value={formatUsd(aggregates.totalRealizedPnl)}
          valueColor={aggregates.totalRealizedPnl > 0 ? "profit" : aggregates.totalRealizedPnl < 0 ? "loss" : "neutral"}
        />
        <Metric
          label="Exposure"
          value={`$${totalExposure.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="rounded-[calc(var(--radius)*1.3)] border border-border/60 bg-card/70 p-4 shadow-[var(--shadow-soft)]">
            <Skeleton className="mb-2 h-3 w-14" />
            <Skeleton className="h-7 w-18" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      <Metric label="Total Trades" value={String(stats?.total_trades ?? 0)} />
      <Metric label="Open" value={String(stats?.open_count ?? 0)} valueColor="profit" />
      <Metric label="Win Rate" value={`${((stats?.win_rate ?? 0) * 100).toFixed(1)}%`} valueColor={(stats?.win_rate ?? 0) >= 0.5 ? "profit" : "loss"} />
      <Metric label="Avg PnL" value={formatUsd(stats?.avg_pnl ?? null)} valueColor={(stats?.avg_pnl ?? 0) > 0 ? "profit" : (stats?.avg_pnl ?? 0) < 0 ? "loss" : "neutral"} />
      <Metric label="Total PnL" value={formatUsd(stats?.total_pnl ?? null)} valueColor={(stats?.total_pnl ?? 0) > 0 ? "profit" : (stats?.total_pnl ?? 0) < 0 ? "loss" : "neutral"} />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  valueColor = "neutral",
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  valueColor?: "profit" | "loss" | "neutral";
}) {
  const colorMap = {
    profit: "text-emerald-500 dark:text-emerald-400",
    loss: "text-destructive",
    neutral: "text-foreground",
  };

  return (
    <div className="glass-card rounded-[calc(var(--radius)*1.35)] px-4 py-3.5 transition-all duration-300 hover:border-primary/22 hover:shadow-[var(--shadow-card-hover)]">
      <span className="text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/70 leading-none">{label}</span>
      <span className={`mt-2 block text-xl font-semibold tabular-nums tracking-[-0.04em] ${colorMap[valueColor]}`}>
        {value}
      </span>
      {sub ? <div className="mt-1.5">{sub}</div> : null}
    </div>
  );
}
