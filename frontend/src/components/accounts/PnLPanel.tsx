import { useEffect, useState } from "react";
import { accountsApi, type PnlSummary } from "@/api/client";
import { Button } from "@/components/ui/button";

interface PnLPanelProps {
  pnlSummary: PnlSummary | null;
  accountId?: string;
}

function dateStr(offset: number): string {
  return new Date(Date.now() - offset * 86400000).toISOString().split("T")[0];
}

function PnlCard({ label, summary, loading }: { label: string; summary: PnlSummary | null; loading?: boolean }) {
  if (loading) {
    return (
      <div className="rounded-lg border p-3 space-y-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="h-6 w-20 animate-pulse bg-muted rounded" />
      </div>
    );
  }
  if (!summary) {
    return (
      <div className="rounded-lg border p-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm text-muted-foreground">—</p>
      </div>
    );
  }
  const pnl = parseFloat(summary.total_pnl) || 0;
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-bold ${pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
        ${pnl.toFixed(2)}
      </p>
      <p className="text-xs text-muted-foreground">
        {summary.win_rate.toFixed(0)}% WR · {summary.win_count}W / {summary.loss_count}L
      </p>
    </div>
  );
}

export function PnLPanel({ pnlSummary: _unused, accountId }: PnLPanelProps) {
  const [todayPnl, setTodayPnl] = useState<PnlSummary | null>(null);
  const [weekPnl, setWeekPnl] = useState<PnlSummary | null>(null);
  const [monthPnl, setMonthPnl] = useState<PnlSummary | null>(null);
  const [customPnl, setCustomPnl] = useState<PnlSummary | null>(null);
  const [loadingPeriods, setLoadingPeriods] = useState(true);
  const [loadingCustom, setLoadingCustom] = useState(false);

  const today = dateStr(0);
  const [startDate, setStartDate] = useState(dateStr(30));
  const [endDate, setEndDate] = useState(today);

  useEffect(() => {
    if (!accountId) return;
    const controller = new AbortController();

    async function loadPeriods() {
      setLoadingPeriods(true);
      try {
        const [t, w, m] = await Promise.all([
          accountsApi.getPnlSummary(accountId!, dateStr(0), dateStr(0), controller.signal),
          accountsApi.getPnlSummary(accountId!, dateStr(7), dateStr(0), controller.signal),
          accountsApi.getPnlSummary(accountId!, dateStr(30), dateStr(0), controller.signal),
        ]);
        setTodayPnl(t);
        setWeekPnl(w);
        setMonthPnl(m);
      } catch {
        // silent
      } finally {
        setLoadingPeriods(false);
      }
    }
    loadPeriods();
    return () => controller.abort();
  }, [accountId]);

  const fetchCustom = async () => {
    if (!accountId) return;
    setLoadingCustom(true);
    try {
      const result = await accountsApi.getPnlSummary(accountId, startDate, endDate);
      setCustomPnl(result);
    } catch {
      // keep existing
    } finally {
      setLoadingCustom(false);
    }
  };

  if (!accountId) {
    return <p className="text-muted-foreground text-center py-8">No PnL data available</p>;
  }

  return (
    <div className="space-y-6">
      {/* Fixed period PnL cards - all visible simultaneously */}
      <div>
        <h3 className="font-semibold mb-3">PnL Overview</h3>
        <div className="grid grid-cols-3 gap-4">
          <PnlCard label="Today" summary={todayPnl} loading={loadingPeriods} />
          <PnlCard label="7 Days" summary={weekPnl} loading={loadingPeriods} />
          <PnlCard label="30 Days" summary={monthPnl} loading={loadingPeriods} />
        </div>
      </div>

      {/* Detailed stats from 7-day (or custom) */}
      {weekPnl && (
        <div>
          <h3 className="font-semibold mb-3">7-Day Breakdown</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Win Rate</p>
              <p className="text-lg font-bold">{weekPnl.win_rate.toFixed(1)}%</p>
              <p className="text-xs text-muted-foreground">{weekPnl.win_count}W / {weekPnl.loss_count}L</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Avg Win</p>
              <p className="text-lg font-bold text-green-600">${(parseFloat(weekPnl.avg_win) || 0).toFixed(2)}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Avg Loss</p>
              <p className="text-lg font-bold text-red-600">${(parseFloat(weekPnl.avg_loss) || 0).toFixed(2)}</p>
            </div>
          </div>
        </div>
      )}

      {/* Custom range */}
      <div>
        <h3 className="font-semibold mb-3">Custom Range</h3>
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded px-2 py-1 text-sm" aria-label="Start date" />
          <span className="text-sm">to</span>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="border rounded px-2 py-1 text-sm" aria-label="End date" />
          <Button size="sm" variant="outline" onClick={fetchCustom} disabled={loadingCustom}>
            {loadingCustom ? "Loading..." : "Apply"}
          </Button>
        </div>
        {customPnl && <PnlCard label={`${startDate} → ${endDate}`} summary={customPnl} />}
      </div>
    </div>
  );
}
