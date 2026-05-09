import type { PerformanceAnalytics } from "@/api/client";

interface Props {
  analytics: PerformanceAnalytics;
}

function KpiCard({ label, value, color, suffix = "" }: { label: string; value: string | number; color?: string; suffix?: string }) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card p-4">
      <div className={`text-xl font-bold tabular-nums ${color || ""}`}>
        {value}{suffix}
      </div>
      <div className="text-[11px] text-muted-foreground mt-1 uppercase tracking-wider font-medium">{label}</div>
    </div>
  );
}

function fmtCurrency(v: number): string {
  return v < 0 ? `-$${Math.abs(v).toFixed(2)}` : `$${v.toFixed(2)}`;
}

export function KpiCards({ analytics }: Props) {
  const totalReturn = analytics.total_return_pct;
  const returnColor = totalReturn >= 0 ? "text-emerald-500" : "text-red-500";
  const pnl = parseFloat(analytics.total_pnl) || 0;
  const pnlColor = pnl >= 0 ? "text-emerald-500" : "text-red-500";
  const avgWin = parseFloat(analytics.avg_win) || 0;
  const avgLoss = Math.abs(parseFloat(analytics.avg_loss) || 0);
  const expectancy = analytics.expectancy;

  return (
    <div className="space-y-3">
      {/* Primary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label="Total Return" value={`${totalReturn > 0 ? "+" : ""}${totalReturn}%`} color={returnColor} />
        <KpiCard label="Total P&L" value={fmtCurrency(pnl)} color={pnlColor} />
        <KpiCard label="Max Drawdown" value={`${analytics.max_drawdown_pct > 0 ? "-" : ""}${analytics.max_drawdown_pct}%`} color={analytics.max_drawdown_pct > 0 ? "text-red-500" : ""} />
        <KpiCard label="Sharpe Ratio" value={analytics.sharpe_ratio} color={analytics.sharpe_ratio >= 1 ? "text-emerald-500" : analytics.sharpe_ratio >= 0 ? "text-yellow-500" : "text-red-500"} />
        <KpiCard label="Win Rate" value={`${analytics.win_rate}%`} color={analytics.win_rate >= 50 ? "text-emerald-500" : "text-red-500"} />
        <KpiCard label="Profit Factor" value={analytics.profit_factor} color={analytics.profit_factor >= 1 ? "text-emerald-500" : "text-red-500"} />
      </div>

      {/* Secondary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        <KpiCard label="Sortino" value={analytics.sortino_ratio} />
        <KpiCard label="Calmar" value={analytics.calmar_ratio} />
        <KpiCard label="Expectancy" value={fmtCurrency(expectancy)} color={expectancy >= 0 ? "text-emerald-500" : "text-red-500"} />
        <KpiCard label="Avg Daily" value={`${analytics.avg_daily_return_pct > 0 ? "+" : ""}${analytics.avg_daily_return_pct}%`} />
        <KpiCard label="Best Day" value={`${analytics.best_day_pct > 0 ? "+" : ""}${analytics.best_day_pct}%`} color={analytics.best_day_pct > 0 ? "text-emerald-500" : ""} />
        <KpiCard label="Worst Day" value={`${analytics.worst_day_pct}%`} color={analytics.worst_day_pct < 0 ? "text-red-500" : ""} />
        <KpiCard label="Win Streak" value={analytics.max_consecutive_wins} color="text-emerald-500" />
        <KpiCard label="Loss Streak" value={analytics.max_consecutive_losses} color="text-red-500" />
      </div>

      {/* Trade Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label="Total Trades" value={analytics.total_trades} />
        <KpiCard label="Wins" value={analytics.win_count} color="text-emerald-500" />
        <KpiCard label="Losses" value={analytics.loss_count} color="text-red-500" />
        <KpiCard label="Avg Win" value={fmtCurrency(avgWin)} color="text-emerald-500" />
        <KpiCard label="Avg Loss" value={fmtCurrency(avgLoss)} color="text-red-500" />
        <KpiCard label="DD Duration" value={`${analytics.drawdown_duration_days}d`} />
      </div>
    </div>
  );
}
