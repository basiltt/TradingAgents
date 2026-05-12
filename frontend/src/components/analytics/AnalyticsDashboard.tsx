import { useEffect, useState, useCallback, useRef } from "react";
import { accountsApi, type DailySnapshot, type PerformanceAnalytics, type DashboardCard } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { EquityCurveChart } from "./EquityCurveChart";
import { DrawdownChart } from "./DrawdownChart";
import { DailyPnlChart } from "./DailyPnlChart";
import { KpiCards } from "./KpiCards";
import { MonthlyPnlGrid } from "./MonthlyPnlGrid";
import { AccountSelector } from "@/components/ui/AccountSelector";
import { CleanupDialog } from "./CleanupDialog";

const PERIODS = ["1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H", "1D", "3D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;
type Period = (typeof PERIODS)[number];
type AccountType = "live" | "demo";
const SUB_DAY_PERIODS = new Set(["1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H"]);

const STORAGE_KEY = "analytics-filters";

function loadFilters(): { accountType: AccountType; period: Period; selectedAccount: string } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        accountType: (["live", "demo"] as const).includes(parsed.accountType) ? parsed.accountType : "live",
        period: PERIODS.includes(parsed.period) ? parsed.period : "1M",
        selectedAccount: parsed.selectedAccount || "portfolio",
      };
    }
  } catch { /* empty */ }
  return { accountType: "live", period: "1M", selectedAccount: "portfolio" };
}

function saveFilters(filters: { accountType: AccountType; period: Period; selectedAccount: string }) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
}

interface Props {
  accountId?: string;
  embedded?: boolean;
}

export function AnalyticsDashboard({ accountId, embedded = false }: Props) {
  const [snapshots, setSnapshots] = useState<DailySnapshot[]>([]);
  const [analytics, setAnalytics] = useState<PerformanceAnalytics | null>(null);
  const [accounts, setAccounts] = useState<DashboardCard[]>([]);
  const saved = accountId ? null : loadFilters();
  const [selectedAccount, setSelectedAccount] = useState<string>(accountId || saved?.selectedAccount || "portfolio");
  const [period, setPeriod] = useState<Period>(saved?.period || "1M");
  const [accountType, setAccountType] = useState<AccountType>(saved?.accountType || "live");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [snapshotting, setSnapshotting] = useState(false);
  const [showCleanup, setShowCleanup] = useState(false);
  const manualAbortRef = useRef<AbortController | null>(null);

  const fetchData = useCallback(async (signal: AbortSignal) => {
    setError(null);
    try {
      if (selectedAccount === "portfolio") {
        const params = { period, account_type: accountType };
        const [snaps, anal] = await Promise.all([
          accountsApi.getPortfolioSnapshots(params, signal),
          accountsApi.getPortfolioAnalytics(params, signal),
        ]);
        setSnapshots(snaps);
        setAnalytics(anal);
      } else {
        const params = { period };
        const [snaps, anal] = await Promise.all([
          accountsApi.getSnapshots(selectedAccount, params, signal),
          accountsApi.getAnalytics(selectedAccount, params, signal),
        ]);
        setSnapshots(snaps);
        setAnalytics(anal);
      }
    } catch (e: unknown) {
      if (e && typeof e === "object" && "name" in e && (e as { name: string }).name === "AbortError") return;
      const err = e as { detail?: string; message?: string };
      setError(err.detail || err.message || "Failed to load analytics");
      setSnapshots([]);
      setAnalytics(null);
    }
    if (!signal.aborted) setLoading(false);
  }, [selectedAccount, period, accountType]);

  const fetchDataRef = useRef(fetchData);
  useEffect(() => {
    fetchDataRef.current = fetchData;
  });

  useEffect(() => {
    return () => manualAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!accountId) {
      const controller = new AbortController();
      accountsApi.getDashboard({ account_type: accountType }, controller.signal).then(setAccounts).catch(() => {});
      return () => controller.abort();
    }
  }, [accountId, accountType]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting loading state before async fetch
    setLoading(true);
    manualAbortRef.current?.abort();
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData]);

  useEffect(() => {
    if (!SUB_DAY_PERIODS.has(period)) return;
    let pollController: AbortController | null = null;
    const interval = setInterval(() => {
      pollController?.abort();
      pollController = new AbortController();
      fetchDataRef.current(pollController.signal);
    }, 65_000);
    return () => {
      clearInterval(interval);
      pollController?.abort();
    };
  }, [period]);

  useEffect(() => {
    if (!accountId) saveFilters({ accountType, period, selectedAccount });
  }, [accountId, accountType, period, selectedAccount]);

  const handleTakeSnapshot = async () => {
    setSnapshotting(true);
    try {
      if (selectedAccount !== "portfolio") {
        await accountsApi.takeSnapshot(selectedAccount);
      } else {
        await accountsApi.takeAllSnapshots();
      }
      manualAbortRef.current?.abort();
      const controller = new AbortController();
      manualAbortRef.current = controller;
      setLoading(true);
      await fetchDataRef.current(controller.signal);
    } catch (e: unknown) {
      setError((e as { detail?: string; message?: string }).detail || (e as { message?: string }).message || "Failed to take snapshot");
    } finally {
      setSnapshotting(false);
    }
  };

  const handleToggleInclusion = async (id: string, include: boolean) => {
    try {
      await accountsApi.setAnalyticsInclusion(id, include);
      setAccounts((prev) =>
        prev.map((a) => a.id === id ? { ...a, include_in_analytics: include } : a),
      );
      if (selectedAccount === "portfolio") {
        manualAbortRef.current?.abort();
        const controller = new AbortController();
        manualAbortRef.current = controller;
        setLoading(true);
        await fetchDataRef.current(controller.signal);
      }
    } catch { /* ignore */ }
  };

  const handleCleanupComplete = () => {
    manualAbortRef.current?.abort();
    const controller = new AbortController();
    manualAbortRef.current = controller;
    setLoading(true);
    fetchDataRef.current(controller.signal);
  };

  return (
    <div className="space-y-6">
      {/* Header - hidden when embedded in a tab */}
      {!embedded && (
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Performance Analytics</h1>
            <p className="text-sm text-muted-foreground mt-1.5">
              Track your trading performance with detailed metrics and charts
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCleanup(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-muted text-foreground font-medium text-sm hover:bg-muted/80 transition-all"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Cleanup
            </button>
            <button
              onClick={handleTakeSnapshot}
              disabled={snapshotting}
              aria-label="Take performance snapshot"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25 disabled:opacity-50"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              {snapshotting ? "Capturing..." : "Take Snapshot"}
            </button>
          </div>
        </div>
      )}

      {/* Live/Demo tabs + Account selector + Period selector */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Live / Demo toggle */}
        {!accountId && (
          <div className="flex items-center gap-1 p-1 rounded-xl bg-muted/50">
            {(["live", "demo"] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setAccountType(t); setSelectedAccount("portfolio"); setAccounts([]); }}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 capitalize ${
                  accountType === t
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        )}

        {/* Account dropdown */}
        {!accountId && (
          <AccountSelector
            accounts={accounts}
            selectedAccount={selectedAccount}
            onSelect={setSelectedAccount}
            onToggleInclusion={handleToggleInclusion}
          />
        )}

        {/* Period selector */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-muted/50">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                period === p
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Auto-snapshot indicator */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Auto-capturing every 1 min
        </div>

        {/* Snapshot button when embedded */}
        {embedded && (
          <>
            <button
              onClick={() => setShowCleanup(true)}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted text-foreground font-medium text-xs hover:bg-muted/80 transition-all"
            >
              Cleanup
            </button>
            <button
              onClick={handleTakeSnapshot}
              disabled={snapshotting}
              aria-label="Take performance snapshot"
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary text-white font-medium text-xs hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50"
            >
              {snapshotting ? "Capturing..." : "Take Snapshot"}
            </button>
          </>
        )}
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-6 text-center">
          <p className="text-destructive text-sm">{error}</p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              manualAbortRef.current?.abort();
              const controller = new AbortController();
              manualAbortRef.current = controller;
              fetchDataRef.current(controller.signal);
            }}
            className="mt-3 px-4 py-2 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 transition-all"
          >
            Retry
          </button>
        </div>
      )}

      {loading && !error ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-2xl" />
          <Skeleton className="h-48 rounded-2xl" />
        </div>
      ) : !error && snapshots.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/60 p-16 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-muted/50 flex items-center justify-center mb-5">
            <svg className="w-8 h-8 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1.5">No performance data yet</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-sm mx-auto">
            Click "Take Snapshot" to capture your current account state. Do this daily to build your performance history.
          </p>
          <button
            onClick={handleTakeSnapshot}
            disabled={snapshotting}
            aria-label="Take performance snapshot"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 transition-all shadow-lg shadow-primary/25 disabled:opacity-50"
          >
            {snapshotting ? "Capturing..." : "Take First Snapshot"}
          </button>
        </div>
      ) : !error ? (
        <>
          {snapshots.length > 0 && (() => {
            const latest = snapshots[snapshots.length - 1];
            const fmt = (v: number) => v < 0 ? `-$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            const items = [
              { label: "Balance", value: latest.wallet_balance, color: "" },
              { label: "Equity", value: latest.equity, color: "" },
              { label: "Unrealized P&L", value: latest.unrealised_pnl, color: latest.unrealised_pnl >= 0 ? "text-emerald-400" : "text-red-400" },
              { label: "Realized P&L", value: latest.realised_pnl, color: latest.realised_pnl >= 0 ? "text-emerald-400" : "text-red-400" },
            ];
            return (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {items.map((item) => (
                  <div key={item.label} className="rounded-2xl border border-border/50 bg-card p-4">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{item.label}</p>
                    <p className={`text-xl font-bold tabular-nums ${item.color || "text-foreground"}`}>{fmt(item.value)}</p>
                  </div>
                ))}
              </div>
            );
          })()}

          {analytics && <KpiCards analytics={analytics} />}

          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <h3 className="text-sm font-semibold mb-4 text-muted-foreground uppercase tracking-wider">Equity Curve</h3>
            <EquityCurveChart snapshots={snapshots} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-border/50 bg-card p-5">
              <h3 className="text-sm font-semibold mb-4 text-muted-foreground uppercase tracking-wider">Drawdown</h3>
              <DrawdownChart snapshots={snapshots} />
            </div>
            <div className="rounded-2xl border border-border/50 bg-card p-5">
              <h3 className="text-sm font-semibold mb-4 text-muted-foreground uppercase tracking-wider">Realized P&L</h3>
              <DailyPnlChart snapshots={snapshots} />
            </div>
          </div>

          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <h3 className="text-sm font-semibold mb-4 text-muted-foreground uppercase tracking-wider">Monthly P&L</h3>
            <MonthlyPnlGrid snapshots={snapshots} />
          </div>
        </>
      ) : null}

      {/* Cleanup Dialog */}
      {showCleanup && (
        <CleanupDialog
          accountId={selectedAccount !== "portfolio" ? selectedAccount : null}
          onComplete={handleCleanupComplete}
          onClose={() => setShowCleanup(false)}
        />
      )}
    </div>
  );
}
