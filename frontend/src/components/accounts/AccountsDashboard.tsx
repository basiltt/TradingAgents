import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { accountsApi } from "@/api/client";
import type { MasterCloseAllResult, DemoResetBalanceResult, DashboardCard } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setFilterType, setLoading, setError } from "@/store/accounts-slice";
import { useAccountPolling } from "@/hooks/useAccountPolling";
import { AccountCard } from "./AccountCard";
import { AddAccountDialog } from "./AddAccountDialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowUp, ArrowDown } from "lucide-react";

const SORT_STORAGE_KEY = "tradingagents_accounts_sort";

type SortField = "name" | "equity" | "today_pnl" | "unrealised_pnl" | "positions" | "last_connected" | "status";
type SortDirection = "asc" | "desc";

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

const SORT_OPTIONS: Array<{ field: SortField; label: string }> = [
  { field: "name", label: "Name" },
  { field: "equity", label: "Equity" },
  { field: "today_pnl", label: "Today PnL" },
  { field: "unrealised_pnl", label: "Unreal. PnL" },
  { field: "positions", label: "Positions" },
  { field: "last_connected", label: "Last Connected" },
  { field: "status", label: "Status" },
];

function loadSortConfig(): SortConfig {
  try {
    const raw = localStorage.getItem(SORT_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { field: "name", direction: "asc" };
}

function saveSortConfig(config: SortConfig) {
  localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(config));
}

function sortAccounts(accounts: DashboardCard[], config: SortConfig): DashboardCard[] {
  const { field, direction } = config;
  const mult = direction === "asc" ? 1 : -1;

  return [...accounts].sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case "name":
        cmp = a.label.localeCompare(b.label);
        break;
      case "equity":
        cmp = parseFloat(a.total_equity || "0") - parseFloat(b.total_equity || "0");
        break;
      case "today_pnl":
        cmp = parseFloat(a.today_pnl || "0") - parseFloat(b.today_pnl || "0");
        break;
      case "unrealised_pnl":
        cmp = parseFloat(a.total_perp_upl || "0") - parseFloat(b.total_perp_upl || "0");
        break;
      case "positions":
        cmp = (a.positions_count || 0) - (b.positions_count || 0);
        break;
      case "last_connected":
        cmp = (a.last_connected_at || "").localeCompare(b.last_connected_at || "");
        break;
      case "status": {
        const order = { active: 0, stale: 1, error: 2, disabled: 3 };
        cmp = (order[a.status] ?? 4) - (order[b.status] ?? 4);
        break;
      }
    }
    return cmp * mult;
  });
}

/** Top-level accounts dashboard: fetches account cards, displays stats/filters, and renders AccountCard grid. */
export function AccountsDashboard() {
  const dispatch = useAppDispatch();
  const { dashboard, filterType, status, error } = useAppSelector((s) => s.accounts);
  const [addOpen, setAddOpen] = useState(false);
  const [killOpen, setKillOpen] = useState(false);
  const [killLoading, setKillLoading] = useState(false);
  const [killResult, setKillResult] = useState<MasterCloseAllResult | null>(null);
  const [killProgress, setKillProgress] = useState<{ current: number; total: number; accounts: Array<{ name: string; status: string; closed?: number }> }>({ current: 0, total: 0, accounts: [] });
  const killTaskId = useRef<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetAmount, setResetAmount] = useState("100");
  const [resetResult, setResetResult] = useState<DemoResetBalanceResult | null>(null);
  const [resetProgress, setResetProgress] = useState<{ current: number; total: number; accounts: Array<{ name: string; status: string; amount?: number }> }>({ current: 0, total: 0, accounts: [] });
  const [sortConfig, setSortConfig] = useState<SortConfig>(loadSortConfig);
  const resetTaskId = useRef<string | null>(null);
  const [resetSelectedIds, setResetSelectedIds] = useState<string[]>([]);
  useAccountPolling();

  /** Fetch dashboard cards; if silent, skips loading state to avoid UI flicker during polling. */
  const fetchDashboard = useCallback(async (silent = false) => {
    if (!silent) dispatch(setLoading());
    try {
      const cards = await accountsApi.getDashboard();
      dispatch(setDashboard(cards));
    } catch (e: unknown) {
      const msg = (e as { message?: string }).message || "Failed to load accounts";
      if (!silent) dispatch(setError(msg));
      else console.warn("[AccountsDashboard] silent fetch failed:", msg);
    }
  }, [dispatch]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    const onProgress = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (killTaskId.current && d.task_id !== killTaskId.current) return;
      setKillProgress(p => ({
        current: d.current,
        total: d.total,
        accounts: [...p.accounts, { name: d.account?.name || "", status: d.account?.status || "", closed: d.account?.closed }],
      }));
    };
    const onComplete = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (killTaskId.current && d.task_id !== killTaskId.current) return;
      setKillResult({ accounts_processed: d.accounts_processed, total_positions_closed: d.total_positions_closed, accounts_failed: d.accounts_failed, results: d.results });
      setKillLoading(false);
      killTaskId.current = null;
      fetchDashboard(true);
    };
    const onResetProgress = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (resetTaskId.current && d.task_id !== resetTaskId.current) return;
      setResetProgress(p => ({
        current: d.current,
        total: d.total,
        accounts: [...p.accounts, { name: d.account?.name || "", status: d.account?.status || "", amount: d.account?.amount }],
      }));
    };
    const onResetComplete = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (resetTaskId.current && d.task_id !== resetTaskId.current) return;
      setResetResult({ target_balance: d.target_balance, accounts_processed: d.accounts_processed, success: d.success, results: d.results });
      setResetLoading(false);
      resetTaskId.current = null;
      fetchDashboard(true);
    };
    window.addEventListener("master_close_progress", onProgress);
    window.addEventListener("master_close_complete", onComplete);
    window.addEventListener("demo_reset_progress", onResetProgress);
    window.addEventListener("demo_reset_complete", onResetComplete);
    return () => {
      window.removeEventListener("master_close_progress", onProgress);
      window.removeEventListener("master_close_complete", onComplete);
      window.removeEventListener("demo_reset_progress", onResetProgress);
      window.removeEventListener("demo_reset_complete", onResetComplete);
    };
  }, [fetchDashboard]);

  const filtered = useMemo(() => {
    const byType = dashboard.filter((card) => {
      if (filterType === "all") return true;
      return card.account_type === filterType;
    });
    return sortAccounts(byType, sortConfig);
  }, [dashboard, filterType, sortConfig]);

  /** Sum a numeric field across filtered dashboard cards.
   * @param field - Key of DashboardCard to sum.
   * @returns Numeric total of the field across all filtered cards.
   */
  const sumField = (field: keyof typeof filtered[number]) =>
    filtered.reduce((sum, c) => {
      const v = parseFloat(String(c[field] ?? "0"));
      return sum + (isNaN(v) ? 0 : v);
    }, 0);

  const totalEquity = sumField("total_equity");
  const totalPnl = sumField("total_perp_upl");
  const totalTodayPnl = sumField("today_pnl");
  const activeCount = filtered.filter((c) => c.status === "active").length;
  const totalPositions = filtered.reduce((sum, c) => sum + (c.positions_count || 0), 0);
  const allPositionsCount = dashboard.reduce((sum, c) => sum + (c.positions_count || 0), 0);
  const allActiveCount = dashboard.filter((c) => c.status === "active").length;
  const hasDemoAccounts = dashboard.some((c) => c.account_type === "demo");
  const demoAccountIds = dashboard
    .filter((c) => c.account_type === "demo" && c.is_active)
    .map((c) => c.id);

  if (status === "loading" && dashboard.length === 0) {
    return (
      <div className="space-y-5 pb-7">
        <Skeleton className="h-48 rounded-[calc(var(--radius)*2)]" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 rounded-[calc(var(--radius)*1.6)]" />
          ))}
        </div>
        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-72 rounded-[calc(var(--radius)*1.7)]" />
          ))}
        </div>
      </div>
    );
  }

  if (status === "error" && dashboard.length === 0) {
    return (
      <div className="space-y-5 pb-7">
        <PageHeader
          eyebrow="Accounts"
          title="Accounts"
          description={error || ""}
          actions={
            <Button variant="outline" onClick={() => fetchDashboard()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Accounts"
        title="Accounts"
        description=""
        actions={
          <div className="flex flex-wrap gap-2 w-full sm:w-auto sm:justify-end">
            {hasDemoAccounts ? (
              <Button
                variant="outline"
                onClick={() => {
                  setResetOpen(true);
                  setResetSelectedIds(demoAccountIds);
                }}
                className="border-amber-500/25 bg-amber-500/10 text-amber-500 hover:bg-amber-500/15 hover:text-amber-500"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Reset balance
              </Button>
            ) : null}
            {allPositionsCount > 0 ? (
              <Button
                variant="destructive"
                onClick={() => setKillOpen(true)}
                className="border-red-500/25 bg-red-500/10 text-red-500 hover:bg-red-500/15 hover:text-red-500"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Close all
              </Button>
            ) : null}
            <Button onClick={() => setAddOpen(true)}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Add account
            </Button>
          </div>
        }
        stats={[
          {
            label: "Equity",
            value: `$${totalEquity.toFixed(2)}`,
            tone: "neutral",
          },
          {
            label: "Today's PnL",
            value: `$${totalTodayPnl.toFixed(2)}`,
            tone: totalTodayPnl >= 0 ? "success" : "danger",
          },
          {
            label: "Unrealised PnL",
            value: `$${totalPnl.toFixed(2)}`,
            tone: totalPnl >= 0 ? "success" : "danger",
          },
          { label: "Open positions", value: String(totalPositions), tone: "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{dashboard.length} linked accounts</Badge>
          <Badge variant="outline">{activeCount} active in scope</Badge>
          <Badge variant="outline">{allActiveCount} active feeds</Badge>
        </div>
      </PageHeader>

      <Card className="!transform-none !shadow-[var(--neu-shadow-raised)] hover:!shadow-[var(--neu-shadow-raised)]">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {(["all", "demo", "live"] as const).map((type) => (
              <Button
                key={type}
                variant={filterType === type ? "default" : "outline"}
                size="sm"
                onClick={() => dispatch(setFilterType(type))}
              >
                {type.charAt(0).toUpperCase() + type.slice(1)}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-medium text-[var(--neu-text-muted)]">Sort:</span>
            {SORT_OPTIONS.map((opt) => {
              const isActive = sortConfig.field === opt.field;
              return (
                <Button
                  key={opt.field}
                  variant={isActive ? "default" : "ghost"}
                  size="sm"
                  onClick={() => {
                    const next: SortConfig = isActive
                      ? { field: opt.field, direction: sortConfig.direction === "asc" ? "desc" : "asc" }
                      : { field: opt.field, direction: "desc" };
                    setSortConfig(next);
                    saveSortConfig(next);
                  }}
                  className="h-7 gap-1 px-2 text-xs"
                >
                  {opt.label}
                  {isActive && (sortConfig.direction === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Empty state */}
      {filtered.length === 0 && status !== "loading" && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-4 p-6 text-center sm:p-8">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <svg className="w-5.5 h-5.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-tight">
                {dashboard.length ? "No accounts match the current filter" : "No accounts connected"}
              </h2>
              <p className="max-w-xl text-sm text-muted-foreground">
                {dashboard.length
                  ? "Change the dashboard scope to reveal a different cohort of accounts."
                  : "Connect your Bybit trading account to start monitoring equity, exposure, and execution controls in real time."}
              </p>
            </div>
            <Button onClick={() => setAddOpen(true)}>
              Connect account
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Account Cards */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3 neu-stagger">
          {filtered.map((card) => (
            <AccountCard key={card.id} card={card} onRefresh={fetchDashboard} />
          ))}
        </div>
      )}

      <AddAccountDialog open={addOpen} onOpenChange={setAddOpen} onCreated={fetchDashboard} />

      {/* Master Kill Switch Dialog */}
      {killOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => { if (!killLoading) { setKillOpen(false); setKillResult(null); setKillProgress({ current: 0, total: 0, accounts: [] }); } }} />
          <div className="relative glass-card hover:transform-none hover:translate-y-0 rounded-2xl p-5 w-full max-w-md shadow-2xl mx-4 bg-card/75 backdrop-blur-md border border-border/40">
            {!killLoading && !killResult ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center glow-destructive">
                    <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Close All Positions</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-red-500/80">Master Kill Switch</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mb-3 font-semibold uppercase tracking-wider">This will immediately:</p>
                <ul className="text-xs text-muted-foreground/90 mb-5 space-y-1.5">
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                    <span>Close <span className="text-foreground font-bold">all open positions</span> on every active account</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                    <span>Delete <span className="text-foreground font-bold">all conditional close rules</span></span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                    <span>Affects <span className="text-foreground font-bold">{allActiveCount} accounts</span> with <span className="text-foreground font-bold">{allPositionsCount} positions</span></span>
                  </li>
                </ul>
                <div className="rounded-xl bg-red-500/5 border border-red-500/10 p-3 mb-5">
                  <p className="text-xs text-red-500 font-bold uppercase tracking-wide mb-1">This action cannot be undone.</p>
                  <p className="text-[11px] text-muted-foreground/80 leading-relaxed">Note: Active scheduled scans will not be paused. Pause them separately to prevent new trades from opening.</p>
                </div>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={() => setKillOpen(false)}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={async () => {
                      setKillLoading(true);
                      setKillProgress({ current: 0, total: 0, accounts: [] });
                      try {
                        const res = await accountsApi.masterCloseAll();
                        killTaskId.current = res.task_id;
                        setKillProgress(p => ({ ...p, total: res.accounts_total }));
                        if (!res.task_id) {
                          setKillResult({ accounts_processed: 0, total_positions_closed: 0, accounts_failed: 0, results: [] });
                          setKillLoading(false);
                        }
                      } catch (e: unknown) {
                        setKillResult({ accounts_processed: 0, total_positions_closed: 0, accounts_failed: 1, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
                        setKillLoading(false);
                      }
                    }}
                    className="flex-1 border-red-500/25 bg-red-500/10 text-red-500 hover:bg-red-500/15"
                  >
                    Close Everything
                  </Button>
                </div>
              </>
            ) : killLoading ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center animate-pulse glow-destructive">
                    <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Closing Positions...</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">{killProgress.current} / {killProgress.total} accounts</p>
                  </div>
                </div>
                {killProgress.total > 0 && (
                  <div className="mb-4">
                    <div className="h-2 rounded-full bg-muted/50 overflow-hidden border border-border/20">
                      <div
                        className="h-full bg-red-500 transition-all duration-300 ease-out rounded-full glow-destructive"
                        style={{ width: `${(killProgress.current / killProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                )}
                <div className="max-h-48 overflow-y-auto space-y-1.5 custom-scrollbar pr-1">
                  {killProgress.accounts.map((a, i) => (
                    <div key={i} className="flex items-center justify-between text-xs px-3 py-2 rounded-xl bg-muted/20 border border-border/20">
                      <span className="truncate mr-2 font-semibold">{a.name}</span>
                      <span className={`text-[10px] font-black uppercase tracking-wider shrink-0 ${a.status === "closed" ? "text-emerald-500" : a.status === "error" ? "text-red-500" : "text-muted-foreground"}`}>
                        {a.status === "closed" ? `${a.closed || 0} closed` : a.status}
                      </span>
                    </div>
                  ))}
                </div>
                <Button
                  variant="link"
                  onClick={() => { setKillOpen(false); setKillLoading(false); setKillResult(null); setKillProgress({ current: 0, total: 0, accounts: [] }); killTaskId.current = null; fetchDashboard(true); }}
                  className="mt-5 w-full text-[10px] font-black uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors cursor-pointer text-center"
                >
                  Dismiss (continues in background)
                </Button>
              </>
            ) : killResult ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center glow-success">
                    <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Action Complete</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-emerald-500">Master Switch Executed</p>
                  </div>
                </div>
                <div className="space-y-2.5 text-xs mb-5 rounded-xl border border-border/40 bg-muted/10 p-3.5">
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Accounts processed:</span>
                    <span className="font-bold text-foreground">{killResult.accounts_processed}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Positions closed:</span>
                    <span className="font-bold text-emerald-500">{killResult.total_positions_closed}</span>
                  </div>
                  {killResult.accounts_failed > 0 && (
                    <div className="flex justify-between items-center">
                      <span className="text-muted-foreground">Accounts failed:</span>
                      <span className="font-bold text-red-500">{killResult.accounts_failed}</span>
                    </div>
                  )}
                  {killResult.results.filter(r => r.status === "error").length > 0 && (
                    <div className="mt-3 max-h-32 overflow-y-auto space-y-1.5 border-t border-border/40 pt-2.5 pr-1 custom-scrollbar">
                      {killResult.results.filter(r => r.status === "error").map((r, i) => (
                        <p key={i} className="text-[11px] text-red-400 font-semibold">{r.name || r.account_id}: {r.reason}</p>
                      ))}
                    </div>
                  )}
                </div>
                <Button
                  onClick={() => { setKillOpen(false); setKillResult(null); setKillProgress({ current: 0, total: 0, accounts: [] }); }}
                  className="w-full"
                >
                  Done
                </Button>
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* Demo Reset Balance Dialog */}
      {resetOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => { if (!resetLoading) { setResetOpen(false); setResetResult(null); setResetProgress({ current: 0, total: 0, accounts: [] }); } }} />
          <div className="relative glass-card hover:transform-none hover:translate-y-0 rounded-2xl p-5 w-full max-w-md shadow-2xl mx-4 bg-card/75 backdrop-blur-md border border-border/40">
            {!resetLoading && !resetResult ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center glow-success">
                    <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Reset Demo Balance</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-amber-500/80">Set demo accounts to target USDT balance</p>
                  </div>
                </div>
                <div className="mb-4 space-y-1.5">
                  <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground/80 block">Target Balance (USDT)</label>
                  <input
                    type="number"
                    value={resetAmount}
                    onChange={(e) => setResetAmount(e.target.value)}
                    min="1"
                    max="100000"
                    step="1"
                    className="w-full h-10 px-4 py-2 rounded-xl border border-border/40 bg-muted/20 text-sm font-semibold tabular-nums focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/50 transition-all duration-200"
                    placeholder="100"
                  />
                  <p className="text-[10px] text-muted-foreground/70">Max: 100,000 USDT per Bybit demo limits</p>
                </div>
                <div className="mb-5">
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground/80">Accounts</label>
                    <Button
                      variant="link"
                      size="xs"
                      onClick={() => {
                        const demoIds = dashboard.filter(c => c.account_type === "demo" && c.is_active).map(c => c.id);
                        setResetSelectedIds(prev => prev.length === demoIds.length ? [] : demoIds);
                      }}
                      className="h-auto p-0 text-[10px] font-black uppercase tracking-wider"
                    >
                      {resetSelectedIds.length === dashboard.filter(c => c.account_type === "demo" && c.is_active).length ? "Deselect all" : "Select all"}
                    </Button>
                  </div>
                  <div className="max-h-40 overflow-y-auto space-y-1.5 border border-border/40 rounded-xl p-2 bg-muted/10 custom-scrollbar pr-1">
                    {dashboard.filter(c => c.account_type === "demo" && c.is_active).map(acct => (
                      <label key={acct.id} className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-muted/30 cursor-pointer border border-transparent hover:border-border/30 transition-colors">
                        <input
                          type="checkbox"
                          checked={resetSelectedIds.includes(acct.id)}
                          onChange={(e) => {
                            setResetSelectedIds(prev => e.target.checked ? [...prev, acct.id] : prev.filter(id => id !== acct.id));
                          }}
                          className="w-4 h-4 rounded border-border text-primary focus:ring-primary/50"
                        />
                        <span className="text-sm font-semibold text-foreground truncate">{acct.label}</span>
                        <span className="text-xs text-muted-foreground ml-auto font-medium tabular-nums">${parseFloat(String(acct.total_equity ?? "0")).toFixed(2)}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={() => { setResetOpen(false); setResetSelectedIds([]); }}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={async () => {
                      const amount = parseFloat(resetAmount);
                      if (!amount || amount <= 0 || amount > 100000) return;
                      if (resetSelectedIds.length === 0) return;
                      setResetLoading(true);
                      setResetProgress({ current: 0, total: 0, accounts: [] });
                      try {
                        const allDemoIds = dashboard.filter(c => c.account_type === "demo" && c.is_active).map(c => c.id);
                        const ids = resetSelectedIds.length === allDemoIds.length ? undefined : resetSelectedIds;
                        const res = await accountsApi.demoResetBalance(amount, ids);
                        resetTaskId.current = res.task_id;
                        setResetProgress(p => ({ ...p, total: res.accounts_total }));
                        if (!res.task_id) {
                          setResetResult({ target_balance: amount, accounts_processed: 0, success: 0, results: [] });
                          setResetLoading(false);
                        }
                      } catch (e: unknown) {
                        setResetResult({ target_balance: amount, accounts_processed: 0, success: 0, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
                        setResetLoading(false);
                      }
                    }}
                    disabled={!resetAmount || parseFloat(resetAmount) <= 0 || resetSelectedIds.length === 0}
                    className="flex-1 border-amber-500/25 bg-amber-500/10 text-amber-500 hover:bg-amber-500/15 disabled:opacity-50"
                  >
                    Set Balance
                  </Button>
                </div>
              </>
            ) : resetLoading ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center animate-pulse glow-success">
                    <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Resetting Balances...</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">{resetProgress.current} / {resetProgress.total} accounts</p>
                  </div>
                </div>
                {resetProgress.total > 0 && (
                  <div className="mb-4">
                    <div className="h-2 rounded-full bg-muted/50 overflow-hidden border border-border/20">
                      <div
                        className="h-full bg-amber-500 transition-all duration-300 ease-out rounded-full glow-success"
                        style={{ width: `${(resetProgress.current / resetProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                )}
                <div className="max-h-48 overflow-y-auto space-y-1.5 custom-scrollbar pr-1">
                  {resetProgress.accounts.map((a, i) => (
                    <div key={i} className="flex items-center justify-between text-xs px-3 py-2 rounded-xl bg-muted/20 border border-border/20">
                      <span className="truncate mr-2 font-semibold">{a.name}</span>
                      <span className={`text-[10px] font-black uppercase tracking-wider shrink-0 ${a.status === "error" ? "text-red-500" : a.status === "unchanged" ? "text-muted-foreground" : "text-emerald-500"}`}>
                        {a.status === "added" || a.status === "reduced" ? `${a.status} $${a.amount || 0}` : a.status}
                      </span>
                    </div>
                  ))}
                </div>
                <Button
                  variant="link"
                  onClick={() => { setResetOpen(false); setResetLoading(false); setResetResult(null); setResetProgress({ current: 0, total: 0, accounts: [] }); resetTaskId.current = null; fetchDashboard(true); }}
                  className="mt-5 w-full text-[10px] font-black uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors cursor-pointer text-center"
                >
                  Dismiss (continues in background)
                </Button>
              </>
            ) : resetResult ? (
              <>
                <div className="flex items-center gap-3.5 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center glow-success">
                    <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">Action Complete</h3>
                    <p className="text-[10px] font-black uppercase tracking-wider text-emerald-500">Demo Balances Reset</p>
                  </div>
                </div>
                <div className="space-y-2.5 text-xs mb-5 rounded-xl border border-border/40 bg-muted/10 p-3.5">
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Target balance:</span>
                    <span className="font-bold text-foreground">${resetResult.target_balance} USDT</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Accounts processed:</span>
                    <span className="font-bold text-foreground">{resetResult.accounts_processed}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Successful:</span>
                    <span className="font-bold text-emerald-500">{resetResult.success}</span>
                  </div>
                  {resetResult.results.filter(r => r.status === "error").length > 0 && (
                    <div className="mt-3 max-h-32 overflow-y-auto space-y-1.5 border-t border-border/40 pt-2.5 pr-1 custom-scrollbar">
                      {resetResult.results.filter(r => r.status === "error").map((r, i) => (
                        <p key={i} className="text-[11px] text-red-400 font-semibold">{r.name || r.account_id}: {r.reason}</p>
                      ))}
                    </div>
                  )}
                </div>
                <Button
                  onClick={() => { setResetOpen(false); setResetResult(null); setResetProgress({ current: 0, total: 0, accounts: [] }); setResetSelectedIds([]); }}
                  className="w-full"
                >
                  Done
                </Button>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
