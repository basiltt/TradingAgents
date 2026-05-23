import type { PerformanceAnalytics } from "@/api/client";
import { motion } from "@/lib/motion";
import { springs } from "@/lib/motion";

interface Props {
  analytics: PerformanceAnalytics;
}

function KpiCard({ label, value, color, suffix = "", index = 0 }: { label: string; value: string | number; color?: string; suffix?: string; index?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ ...springs.snappy, delay: index * 0.04 }}
      className="glass-card border border-border/50 bg-card/65 backdrop-blur-sm p-3 sm:p-4 rounded-xl sm:rounded-2xl shadow-sm hover:shadow-md transition-all duration-300 hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98]"
    >
      <div className={`text-base sm:text-xl font-black tracking-tight tabular-nums ${color || "text-foreground"}`}>
        {value}{suffix}
      </div>
      <div className="text-[9px] sm:text-[10px] text-muted-foreground mt-0.5 sm:mt-1 uppercase tracking-wider font-extrabold">{label}</div>
    </motion.div>
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
    <div className="space-y-2 sm:space-y-3">
      {/* Primary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-3">
        <KpiCard index={0} label="Total Return" value={`${totalReturn > 0 ? "+" : ""}${totalReturn}%`} color={returnColor} />
        <KpiCard index={1} label="Total P&L" value={fmtCurrency(pnl)} color={pnlColor} />
        <KpiCard index={2} label="Max Drawdown" value={`${analytics.max_drawdown_pct > 0 ? "-" : ""}${analytics.max_drawdown_pct}%`} color={analytics.max_drawdown_pct > 0 ? "text-red-500" : ""} />
        <KpiCard index={3} label="Sharpe Ratio" value={analytics.sharpe_ratio} color={analytics.sharpe_ratio >= 1 ? "text-emerald-500" : analytics.sharpe_ratio >= 0 ? "text-yellow-500" : "text-red-500"} />
        <KpiCard index={4} label="Win Rate" value={`${analytics.win_rate}%`} color={analytics.win_rate >= 50 ? "text-emerald-500" : "text-red-500"} />
        <KpiCard index={5} label="Profit Factor" value={analytics.profit_factor} color={analytics.profit_factor >= 1 ? "text-emerald-500" : "text-red-500"} />
      </div>

      {/* Secondary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-2 sm:gap-3">
        <KpiCard index={6} label="Sortino" value={analytics.sortino_ratio} />
        <KpiCard index={7} label="Calmar" value={analytics.calmar_ratio} />
        <KpiCard index={8} label="Expectancy" value={fmtCurrency(expectancy)} color={expectancy >= 0 ? "text-emerald-500" : "text-red-500"} />
        <KpiCard index={9} label="Avg Daily" value={`${analytics.avg_daily_return_pct > 0 ? "+" : ""}${analytics.avg_daily_return_pct}%`} />
        <KpiCard index={10} label="Best Day" value={`${analytics.best_day_pct > 0 ? "+" : ""}${analytics.best_day_pct}%`} color={analytics.best_day_pct > 0 ? "text-emerald-500" : ""} />
        <KpiCard index={11} label="Worst Day" value={`${analytics.worst_day_pct}%`} color={analytics.worst_day_pct < 0 ? "text-red-500" : ""} />
        <KpiCard index={12} label="Win Streak" value={analytics.max_consecutive_wins} color="text-emerald-500" />
        <KpiCard index={13} label="Loss Streak" value={analytics.max_consecutive_losses} color="text-red-500" />
      </div>

      {/* Trade Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-3">
        <KpiCard index={14} label="Total Trades" value={analytics.total_trades} />
        <KpiCard index={15} label="Wins" value={analytics.win_count} color="text-emerald-500" />
        <KpiCard index={16} label="Losses" value={analytics.loss_count} color="text-red-500" />
        <KpiCard index={17} label="Avg Win" value={fmtCurrency(avgWin)} color="text-emerald-500" />
        <KpiCard index={18} label="Avg Loss" value={fmtCurrency(avgLoss)} color="text-red-500" />
        <KpiCard index={19} label="DD Duration" value={`${analytics.drawdown_duration_days}d`} />
      </div>
    </div>
  );
}
