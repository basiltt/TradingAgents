import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTradeStats } from "@/components/trades/hooks/useTradeStats";
import { PnLDisplay } from "@/components/trades/PnLDisplay";
import { useAppSelector } from "@/store";
import { selectActiveTradeAggregates } from "@/components/trades/selectors";

export function TradeStats() {
  const activeTab = useAppSelector((s) => s.trades.activeTab);
  const aggregates = useAppSelector(selectActiveTradeAggregates);
  const { data: stats, isLoading } = useTradeStats();

  if (activeTab === "active") {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard title="Active Trades" value={String(aggregates.tradeCount)} />
        <StatCard title="Total PnL">
          <PnLDisplay value={aggregates.totalRealizedPnl} />
        </StatCard>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i}><CardContent className="p-4"><Skeleton className="h-8 w-20" /></CardContent></Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard title="Total Trades" value={String(stats?.total_trades ?? 0)} />
      <StatCard title="Open" value={String(stats?.open_count ?? 0)} />
      <StatCard title="Win Rate" value={`${((stats?.win_rate ?? 0) * 100).toFixed(1)}%`} />
      <StatCard title="Total PnL">
        <PnLDisplay value={stats?.total_pnl ?? null} />
      </StatCard>
    </div>
  );
}

function StatCard({
  title,
  value,
  children,
}: {
  title: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-xs font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        {children ?? <p className="text-2xl font-bold">{value}</p>}
      </CardContent>
    </Card>
  );
}
