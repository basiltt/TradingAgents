import { useEffect, useState } from "react";
import { accountsApi, type PnlSummary } from "@/api/client";

interface PnLPanelProps {
  pnlSummary: PnlSummary | null;
  accountId?: string;
}

function dateStr(offset: number): string {
  return new Date(Date.now() - offset * 86400000).toISOString().split("T")[0];
}

function PnlCard({ label, summary, loading, accent }: { label: string; summary: PnlSummary | null; loading?: boolean; accent?: string }) {
  if (loading) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-5 space-y-3">
        <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">{label}</span>
        <div className="h-7 w-24 animate-pulse bg-muted rounded-lg" />
        <div className="h-3 w-32 animate-pulse bg-muted rounded" />
      </div>
    );
  }
  if (!summary) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-5 space-y-3">
        <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">{label}</span>
        <p className="text-lg font-bold text-muted-foreground/30">—</p>
      </div>
    );
  }
  const pnl = parseFloat(summary.total_pnl) || 0;
  const isPositive = pnl >= 0;
  return (
    <div className={`rounded-2xl border bg-card p-5 space-y-3 ${
      accent ? `border-${accent}-500/20` : "border-border/40"
    }`}>
      <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">{label}</span>
      <p className={`text-2xl font-bold tabular-nums tracking-tight ${isPositive ? "text-emerald-500" : "text-red-500"}`}>
        {isPositive ? "+" : ""}${pnl.toFixed(2)}
      </p>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-muted-foreground/50 tabular-nums">
          {summary.win_rate.toFixed(0)}% WR
        </span>
        <div className="w-px h-3 bg-border/30" />
        <span className="text-[10px] tabular-nums">
          <span className="text-emerald-500">{summary.win_count}W</span>
          <span className="text-muted-foreground/40 mx-1">/</span>
          <span className="text-red-500">{summary.loss_count}L</span>
        </span>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-2xl border border-border/40 bg-card p-5 space-y-2">
      <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">{label}</span>
      <p className={`text-xl font-bold tabular-nums tracking-tight ${color ?? ""}`}>{value}</p>
    </div>
  );
}

export function PnLPanel({ accountId }: PnLPanelProps) {
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

  const [customError, setCustomError] = useState<string | null>(null);

  const fetchCustom = async () => {
    if (!accountId) return;
    if (startDate > endDate) {
      setCustomError("Start date must be before end date");
      return;
    }
    setCustomError(null);
    setLoadingCustom(true);
    try {
      const result = await accountsApi.getPnlSummary(accountId, startDate, endDate);
      setCustomPnl(result);
    } catch {
      setCustomError("Failed to load PnL data");
    } finally {
      setLoadingCustom(false);
    }
  };

  if (!accountId) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-12 text-center">
        <p className="text-sm text-muted-foreground/60">No PnL data available</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* PnL Overview */}
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground/80 uppercase tracking-wider mb-4">PnL Overview</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <PnlCard label="Today" summary={todayPnl} loading={loadingPeriods} />
          <PnlCard label="7 Days" summary={weekPnl} loading={loadingPeriods} />
          <PnlCard label="30 Days" summary={monthPnl} loading={loadingPeriods} />
        </div>
      </div>

      {/* 7-Day Breakdown */}
      {weekPnl && (
        <div>
          <h3 className="text-sm font-semibold text-muted-foreground/80 uppercase tracking-wider mb-4">7-Day Breakdown</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-border/40 bg-card p-5 space-y-2">
              <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Win Rate</span>
              <p className="text-xl font-bold tabular-nums tracking-tight">{weekPnl.win_rate.toFixed(1)}%</p>
              {/* Win/loss bar */}
              <div className="flex h-1.5 rounded-full overflow-hidden bg-muted/30">
                {weekPnl.win_count + weekPnl.loss_count > 0 && (
                  <>
                    <div className="bg-emerald-500 rounded-l-full" style={{ width: `${weekPnl.win_rate}%` }} />
                    <div className="bg-red-500 rounded-r-full" style={{ width: `${100 - weekPnl.win_rate}%` }} />
                  </>
                )}
              </div>
              <span className="text-[10px] tabular-nums">
                <span className="text-emerald-500">{weekPnl.win_count}W</span>
                <span className="text-muted-foreground/40 mx-1">/</span>
                <span className="text-red-500">{weekPnl.loss_count}L</span>
              </span>
            </div>
            <StatCard label="Avg Win" value={`$${(parseFloat(weekPnl.avg_win) || 0).toFixed(2)}`} color="text-emerald-500" />
            <StatCard label="Avg Loss" value={`$${(parseFloat(weekPnl.avg_loss) || 0).toFixed(2)}`} color="text-red-500" />
          </div>
        </div>
      )}

      {/* Custom Range */}
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground/80 uppercase tracking-wider mb-4">Custom Range</h3>
        <div className="rounded-2xl border border-border/40 bg-card p-5 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-muted/30 border border-border/40 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
              aria-label="Start date"
            />
            <svg className="w-4 h-4 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-muted/30 border border-border/40 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
              aria-label="End date"
            />
            <button
              onClick={fetchCustom}
              disabled={loadingCustom}
              className="px-5 py-2 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25 disabled:opacity-50"
            >
              {loadingCustom ? (
                <div className="flex items-center gap-2">
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Loading...
                </div>
              ) : "Apply"}
            </button>
          </div>
          {customError && (
            <div className="px-3.5 py-2.5 rounded-xl bg-red-500/[0.06] border border-red-500/15">
              <p className="text-sm text-red-500">{customError}</p>
            </div>
          )}
          {customPnl && (
            <div className="pt-2">
              <PnlCard label={`${startDate} → ${endDate}`} summary={customPnl} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
