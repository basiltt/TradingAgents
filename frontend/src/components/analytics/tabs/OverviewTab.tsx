import type { PerformanceOverview } from "../performanceTypes";
import { EquityCurveChart } from "../EquityCurveChart";
import { DrawdownChart } from "../DrawdownChart";
import { DailyPnlChart } from "../DailyPnlChart";
import { MonthlyPnlGrid } from "../MonthlyPnlGrid";
import { KpiCards } from "../KpiCards";

export function OverviewTab({ overview }: { overview: PerformanceOverview }) {
  const lowData = (overview.meta.trading_days ?? 0) < 10;
  return (
    <div className="flex flex-col gap-4">
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <EquityCurveChart
          data={overview.equity_curve}
          startingEquity={overview.meta.live_equity_available ? overview.meta.starting_equity : null}
          equityNow={overview.equity_now}
        />
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <DrawdownChart data={overview.drawdown_series} />
        </section>
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <DailyPnlChart data={overview.daily_pnl} />
        </section>
      </div>
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <MonthlyPnlGrid data={overview.monthly_pnl} />
      </section>
      <KpiCards kpis={overview.kpis} lowDataNotice={lowData} />
    </div>
  );
}
