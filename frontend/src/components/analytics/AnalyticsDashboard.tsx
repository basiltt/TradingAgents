/**
 * @module AnalyticsDashboard
 * @description Full-page analytics dashboard showing equity curve, drawdown profile,
 * daily PnL bar chart, monthly PnL heat-grid, and performance KPI cards. Supports
 * portfolio-level aggregation or single-account drill-down, with configurable
 * timeframe periods and account-type filters. Filter state is persisted to
 * localStorage. Can be rendered standalone or embedded inside AccountDetailView.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { accountsApi, type DailySnapshot, type PerformanceAnalytics, type DashboardCard } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { EquityCurveChart } from "./EquityCurveChart";
import { DrawdownChart } from "./DrawdownChart";
import { DailyPnlChart } from "./DailyPnlChart";
import { KpiCards } from "./KpiCards";
import { MonthlyPnlGrid } from "./MonthlyPnlGrid";
import { AccountSelector } from "@/components/ui/AccountSelector";
import { PageHeader } from "@/components/layout/PageHeader";
import { CleanupDialog } from "./CleanupDialog";
import { NeuSelect } from "@/design-system/neumorphism";
import { readJson, writeJson } from "@/lib/storage";
import { logger } from "@/lib/logger";

const PERIODS = ["1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H", "1D", "3D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;
type Period = (typeof PERIODS)[number];
type AccountType = "live" | "demo";
const SUB_DAY_PERIODS = new Set(["1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H"]);

const STORAGE_KEY = "analytics-filters";

function loadFilters(): { accountType: AccountType; period: Period; selectedAccount: string } {
  const parsed = readJson<Partial<{ accountType: AccountType; period: Period; selectedAccount: string }>>(STORAGE_KEY, {});
  return {
    accountType: (["live", "demo"] as const).includes(parsed.accountType as AccountType) ? (parsed.accountType as AccountType) : "live",
    period: PERIODS.includes(parsed.period as Period) ? (parsed.period as Period) : "1M",
    selectedAccount: parsed.selectedAccount || "portfolio",
  };
}

function saveFilters(filters: { accountType: AccountType; period: Period; selectedAccount: string }) {
  writeJson(STORAGE_KEY, filters);
}

/** Props for {@link AnalyticsDashboard}. */
interface Props {
  /** When provided, locks the dashboard to this account; hides the account selector. */
  accountId?: string;
  /** When `true`, renders without the standalone page header (for embedding inside another view). */
  embedded?: boolean;
}

/**
 * Renders the analytics dashboard for either a single account or the full portfolio.
 *
 * In standalone mode the component shows a `PageHeader`, an account/type selector, and
 * a period picker whose state is persisted to `localStorage`. In embedded mode (inside
 * `AccountDetailView`) the header and account selector are hidden and the `accountId`
 * prop pins the data scope.
 *
 * Data is fetched via `accountsApi.getSnapshots` / `getPortfolioSnapshots` and
 * `getAnalytics` / `getPortfolioAnalytics`. All in-flight requests are cancelled on
 * re-fetch or unmount via `AbortController`.
 *
 * @param props - See {@link Props}.
 * @returns Chart widgets, KPI cards, and optional tooling dialogs, or loading/error states.
 *
 * @example
 * // Full-page standalone usage
 * <AnalyticsDashboard />
 *
 * // Embedded inside a detail view
 * <AnalyticsDashboard accountId="acc_abc123" embedded />
 */
export function AnalyticsDashboard({ accountId, embedded = false }: Props) {
  const [snapshots, setSnapshots] = useState<DailySnapshot[]>([]);
  const [analytics, setAnalytics] = useState<PerformanceAnalytics | null>(null);
  const [accounts, setAccounts] = useState<DashboardCard[]>([]);
  const savedFilters = accountId ? null : loadFilters();
  const [selectedAccount, setSelectedAccount] = useState<string>(
    accountId || savedFilters?.selectedAccount || "portfolio",
  );
  const [period, setPeriod] = useState<Period>(
    accountId ? "1M" : (savedFilters?.period || "1M"),
  );
  const [accountType, setAccountType] = useState<AccountType>(
    accountId ? "live" : (savedFilters?.accountType || "live"),
  );
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

  // AI-CONTEXT: Single source of truth for "abort any in-flight manual fetch, start
  // a fresh one, and show the loading state." Replaces the 4 hand-inlined copies of
  // the abort→new-controller→setLoading→fetch dance (snapshot, toggle-inclusion,
  // cleanup-complete, retry button). Reads fetchData via the ref so this callback is
  // stable and always invokes the latest closure. Errors are surfaced unless the
  // fetch was aborted (a superseding refetch), matching the prior per-handler logic.
  const refetch = useCallback(() => {
    manualAbortRef.current?.abort();
    const controller = new AbortController();
    manualAbortRef.current = controller;
    setLoading(true);
    return fetchDataRef.current(controller.signal);
  }, []);

  useEffect(() => {
    return () => manualAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!accountId) {
      const controller = new AbortController();
      accountsApi.getDashboard({ account_type: accountType }, controller.signal).then(setAccounts).catch((e) => {
        if (e?.name !== "AbortError") setError("Failed to load accounts");
      });
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
      await refetch();
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
        await refetch();
      }
    } catch (e) {
      // AI-CONTEXT: The toggle is non-critical, so we don't block the UI with an
      // error banner — but a silently-failing analytics-inclusion write should still
      // be observable (the user's intent didn't persist).
      logger.warn("AnalyticsDashboard", "setAnalyticsInclusion failed", {
        accountId: id,
        include,
        message: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const handleCleanupComplete = () => {
    refetch().catch((e) => {
      if (e?.name !== "AbortError") setError("Failed to refresh data");
    });
  };

  const latestSnapshot = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;

  return (
    <div className="space-y-3 sm:space-y-5 pb-8">
      {!embedded && (
        <PageHeader
          eyebrow="Analytics"
          title="Performance"
          description=""
          stats={[
            {
              label: "Scope",
              value: selectedAccount === "portfolio" ? "Portfolio" : "Account",
              tone: "accent",
            },
            {
              label: "Period",
              value: period,
              tone: "neutral",
            },
            {
              label: "Snapshots",
              value: String(snapshots.length),
              tone: snapshots.length > 0 ? "success" : "neutral",
            },
            {
              label: "State",
              value: loading ? "Loading" : error ? "Issue" : "Live",
              tone: loading ? "warning" : error ? "danger" : "success",
            },
          ]}
          actions={
            <div className="flex flex-wrap gap-2">
              <button
                id="analytics-cleanup-button"
                onClick={() => setShowCleanup(true)}
                className="touch-target inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-border/70 bg-card/72 px-3.5 py-2.5 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)] hover:border-primary/25 hover:bg-card/88"
              >
                <svg className="size-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                Cleanup
              </button>
              <button
                id="analytics-take-snapshot-button"
                onClick={handleTakeSnapshot}
                disabled={snapshotting}
                aria-label="Take performance snapshot"
                className="touch-target inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-primary/20 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <svg className="size-4 text-current" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {snapshotting ? "Capturing..." : "Take Snapshot"}
              </button>
            </div>
          }
        >
          <div className="flex flex-wrap gap-2">
            <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground shadow-[var(--shadow-soft)]">
              {accountType}
            </span>
            <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
              {selectedAccount === "portfolio" ? "All included accounts" : selectedAccount}
            </span>
            {SUB_DAY_PERIODS.has(period) ? (
              <span className="inline-flex min-h-8 items-center gap-2 rounded-full border border-emerald-500/22 bg-emerald-500/12 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-500 shadow-[var(--shadow-soft)]">
                <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Auto-capturing every 65s
              </span>
            ) : null}
          </div>
        </PageHeader>
      )}

      <div className="grid gap-3 sm:gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(19rem,0.8fr)]">
        <Card>
          <CardContent className="grid gap-3 sm:gap-4 p-3 sm:p-4 lg:grid-cols-[auto_minmax(0,1fr)] lg:items-start">
            {!accountId ? (
              <div className="flex items-center gap-1 rounded-[calc(var(--radius)*1.15)] border border-border/60 bg-muted/30 p-1 shadow-[var(--shadow-soft)]">
                {(["live", "demo"] as const).map((t) => (
                  <button
                    key={t}
                    id={`analytics-account-type-${t}`}
                    onClick={() => {
                      setAccountType(t);
                      setSelectedAccount("portfolio");
                      setAccounts([]);
                    }}
                    className={`rounded-[calc(var(--radius)*0.95)] px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] transition-all duration-200 ${
                      accountType === t
                        ? "bg-card text-foreground shadow-[var(--shadow-soft)]"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
              {!accountId ? (
                <div className="space-y-2">
                  <p className="section-eyebrow">Analytics scope</p>
                  <AccountSelector
                    accounts={accounts}
                    selectedAccount={selectedAccount}
                    onSelect={setSelectedAccount}
                    onToggleInclusion={handleToggleInclusion}
                  />
                </div>
              ) : null}

              <div className="space-y-2 lg:min-w-[20rem]">
                <p className="section-eyebrow">Timeframe</p>
                {/* Desktop view: Horizontal scrolling buttons */}
                <div className="hidden sm:flex no-scrollbar gap-1 overflow-x-auto rounded-[calc(var(--radius)*1.15)] border border-border/60 bg-muted/28 p-1 shadow-[var(--shadow-soft)]">
                  {PERIODS.map((p) => (
                    <button
                      key={p}
                      id={`analytics-period-${p}`}
                      onClick={() => setPeriod(p)}
                      className={`shrink-0 rounded-[calc(var(--radius)*0.9)] px-3 py-2 text-[10px] font-black uppercase tracking-[0.18em] transition-all duration-200 ${
                        period === p
                          ? "bg-card text-foreground shadow-[var(--shadow-soft)]"
                          : "text-muted-foreground/80 hover:text-foreground"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
                {/* Mobile view: Neumorphic dropdown */}
                <div className="sm:hidden">
                  <NeuSelect
                    options={PERIODS.map((p) => ({ value: p, label: p }))}
                    value={period}
                    onChange={(val) => setPeriod(val as Period)}
                    placeholder="Select Timeframe"
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:grid-cols-3 xl:grid-cols-1">
            <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/58 p-3.5 shadow-[var(--shadow-soft)]">
              <p className="section-eyebrow">Latest equity</p>
              <p className="mt-2 text-2xl font-semibold tracking-[-0.05em] text-foreground">
                {latestSnapshot ? `$${latestSnapshot.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
              </p>
            </div>
            <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/58 p-3.5 shadow-[var(--shadow-soft)]">
              <p className="section-eyebrow">Realized PnL</p>
              <p className={`mt-2 text-2xl font-semibold tracking-[-0.05em] ${latestSnapshot && latestSnapshot.realised_pnl < 0 ? "text-destructive" : "text-emerald-500"}`}>
                {latestSnapshot
                  ? `${latestSnapshot.realised_pnl < 0 ? "-" : "+"}$${Math.abs(latestSnapshot.realised_pnl).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : "—"}
              </p>
            </div>
            <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/58 p-3.5 shadow-[var(--shadow-soft)]">
              <p className="section-eyebrow">Capture cadence</p>
              <p className="mt-2 text-lg font-semibold tracking-[-0.04em] text-foreground">
                {SUB_DAY_PERIODS.has(period) ? "Live pulse" : "Manual snapshots"}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {embedded ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            id="analytics-embedded-cleanup-button"
            onClick={() => setShowCleanup(true)}
            className="inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.05)] border border-border/70 bg-card/72 px-3 py-2 text-xs font-bold uppercase tracking-[0.18em] text-foreground shadow-[var(--shadow-soft)] hover:border-primary/25"
          >
            Cleanup
          </button>
          <button
            id="analytics-embedded-snapshot-button"
            onClick={handleTakeSnapshot}
            disabled={snapshotting}
            aria-label="Take performance snapshot"
            className="inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.05)] border border-primary/20 bg-primary px-3 py-2 text-xs font-bold uppercase tracking-[0.18em] text-primary-foreground shadow-[var(--shadow-accent)] hover:brightness-110 disabled:opacity-50"
          >
            {snapshotting ? "Capturing..." : "Take Snapshot"}
          </button>
        </div>
      ) : null}

      {error ? (
        <Card className="border-destructive/25 bg-destructive/6">
          <CardContent className="flex flex-col items-center gap-3 p-6 text-center sm:flex-row sm:text-left">
            <div className="flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.35)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <svg className="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0 3.75h.008v.008H12v-.008z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.29 3.86 1.82 18a2.25 2.25 0 0 0 1.93 3.37h16.5A2.25 2.25 0 0 0 22.18 18L13.71 3.86a2.25 2.25 0 0 0-3.42 0Z" />
              </svg>
            </div>
            <div className="space-y-1.5">
              <p className="section-eyebrow">Analytics feed issue</p>
              <h3 className="text-lg font-semibold tracking-tight text-foreground">{error}</h3>
              <p className="text-sm text-muted-foreground">
                Retry the analytics query without leaving the current monitoring surface.
              </p>
            </div>
            <button
              id="analytics-retry-button"
              onClick={() => {
                setError(null);
                refetch().catch((e) => {
                  if (e?.name !== "AbortError") setError("Failed to refresh data");
                });
              }}
              className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.1)] border border-primary/20 bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)] hover:brightness-110"
            >
              Retry
            </button>
          </CardContent>
        </Card>
      ) : loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-[calc(var(--radius)*1.35)]" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-[calc(var(--radius)*1.55)]" />
          <Skeleton className="h-48 rounded-[calc(var(--radius)*1.55)]" />
        </div>
      ) : snapshots.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center">
            <div className="gradient-primary flex size-14 items-center justify-center rounded-[calc(var(--radius)*1.55)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <svg className="size-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
              </svg>
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">No history yet</p>
              <h3 className="text-xl font-semibold tracking-tight">Capture the first analytics snapshot</h3>
              <p className="max-w-xl text-sm text-muted-foreground">
                Take a snapshot to start building performance history for the selected account scope and timeframe.
              </p>
            </div>
            <button
              id="analytics-first-snapshot-button"
              onClick={handleTakeSnapshot}
              disabled={snapshotting}
              aria-label="Take performance snapshot"
              className="inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.1)] border border-primary/20 bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)] hover:brightness-110 disabled:opacity-50"
            >
              {snapshotting ? "Capturing..." : "Take first snapshot"}
            </button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4 animate-fade-in">
          {latestSnapshot ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Balance", value: latestSnapshot.wallet_balance, color: "text-foreground" },
                { label: "Equity", value: latestSnapshot.equity, color: "text-foreground" },
                {
                  label: "Unrealized P&L",
                  value: latestSnapshot.unrealised_pnl,
                  color: latestSnapshot.unrealised_pnl >= 0 ? "text-emerald-500 dark:text-emerald-400" : "text-destructive",
                },
                {
                  label: "Realized P&L",
                  value: latestSnapshot.realised_pnl,
                  color: latestSnapshot.realised_pnl >= 0 ? "text-emerald-500 dark:text-emerald-400" : "text-destructive",
                },
              ].map((item) => (
                <Card key={item.label}>
                  <CardContent className="p-4">
                    <p className="section-eyebrow">{item.label}</p>
                    <p className={`mt-3 text-2xl font-semibold tracking-[-0.05em] ${item.color}`}>
                      {`${item.value < 0 ? "-" : "$"}${item.value < 0 ? "$" : ""}${Math.abs(item.value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.replace("$$", "$")}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : null}

          {analytics ? <KpiCards analytics={analytics} /> : null}

          <Card>
            <CardContent className="p-4.5">
              <div className="mb-4 flex items-center gap-2">
                <div className="gradient-primary flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.2)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <svg className="size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div>
                  <p className="section-eyebrow">Trendline</p>
                  <h3 className="text-lg font-semibold tracking-tight">Equity curve</h3>
                </div>
              </div>
              <EquityCurveChart snapshots={snapshots} />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardContent className="p-4.5">
                <div className="mb-4 flex items-center gap-2">
                  <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.2)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
                    <svg className="size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 17h8m0 0V9m0 8-8-8-4 4-6-6" />
                    </svg>
                  </div>
                  <div>
                    <p className="section-eyebrow">Risk</p>
                    <h3 className="text-lg font-semibold tracking-tight">Drawdown profile</h3>
                  </div>
                </div>
                <DrawdownChart snapshots={snapshots} />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4.5">
                <div className="mb-4 flex items-center gap-2">
                  <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.2)] bg-emerald-500/12 text-emerald-500 shadow-[var(--shadow-soft)]">
                    <svg className="size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 8h6m-6 4h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2Z" />
                    </svg>
                  </div>
                  <div>
                    <p className="section-eyebrow">Flow</p>
                    <h3 className="text-lg font-semibold tracking-tight">Daily realized P&L</h3>
                  </div>
                </div>
                <DailyPnlChart snapshots={snapshots} />
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="p-4.5">
              <div className="mb-4 flex items-center gap-2">
                <div className="gradient-primary flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.2)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <svg className="size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z" />
                  </svg>
                </div>
                <div>
                  <p className="section-eyebrow">Seasonality</p>
                  <h3 className="text-lg font-semibold tracking-tight">Monthly P&L grid</h3>
                </div>
              </div>
              <MonthlyPnlGrid snapshots={snapshots} />
            </CardContent>
          </Card>
        </div>
      )}

      {showCleanup ? (
        <CleanupDialog
          accountId={selectedAccount !== "portfolio" ? selectedAccount : null}
          onComplete={handleCleanupComplete}
          onClose={() => setShowCleanup(false)}
        />
      ) : null}
    </div>
  );
}
