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
      <div className="grid grid-cols-5 gap-px rounded-xl overflow-hidden border border-border/60 bg-border/60">
        <Metric
          label="Positions"
          value={String(aggregates.tradeCount)}
          sub={<span className="text-[10px]"><span className="text-emerald-400">{longCount}L</span> <span className="text-muted-foreground/60">/</span> <span className="text-red-400">{shortCount}S</span></span>}
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
      <div className="grid grid-cols-5 gap-px rounded-xl overflow-hidden border border-border/60 bg-border/60">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="bg-card p-4">
            <Skeleton className="h-3 w-12 mb-2" />
            <Skeleton className="h-6 w-16" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-5 gap-px rounded-xl overflow-hidden border border-border/60 bg-border/60">
      <Metric label="Total Trades" value={String(stats?.total_trades ?? 0)} />
      <Metric label="Open" value={String(stats?.open_count ?? 0)} valueColor="profit" />
      <Metric label="Win Rate" value={`${((stats?.win_rate ?? 0) * 100).toFixed(1)}%`} valueColor={((stats?.win_rate ?? 0)) >= 0.5 ? "profit" : "loss"} />
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
    profit: "text-emerald-400",
    loss: "text-red-400",
    neutral: "text-foreground",
  };

  return (
    <div className="bg-card px-4 py-3.5 flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground/80">{label}</span>
      <span className={`text-lg font-semibold font-mono tabular-nums leading-none ${colorMap[valueColor]}`}>{value}</span>
      {sub && <div className="mt-0.5">{sub}</div>}
    </div>
  );
}
