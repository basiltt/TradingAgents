import { useState, useCallback } from "react";
import { accountsApi } from "@/api/client";
import type { MasterCloseAllResult, DemoResetBalanceResult } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setFilterType, setLoading, setError } from "@/store/accounts-slice";
import { useAccountPolling } from "@/hooks/useAccountPolling";
import { AccountCard } from "./AccountCard";
import { AddAccountDialog } from "./AddAccountDialog";
import { Skeleton } from "@/components/ui/skeleton";

/** Top-level accounts dashboard: fetches account cards, displays stats/filters, and renders AccountCard grid. */
export function AccountsDashboard() {
  const dispatch = useAppDispatch();
  const { dashboard, filterType, status, error } = useAppSelector((s) => s.accounts);
  const [addOpen, setAddOpen] = useState(false);
  const [killOpen, setKillOpen] = useState(false);
  const [killLoading, setKillLoading] = useState(false);
  const [killResult, setKillResult] = useState<MasterCloseAllResult | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetAmount, setResetAmount] = useState("100");
  const [resetResult, setResetResult] = useState<DemoResetBalanceResult | null>(null);
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

  const filtered = dashboard.filter((card) => {
    if (filterType === "all") return true;
    return card.account_type === filterType;
  });

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

  if (status === "loading" && dashboard.length === 0) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-56" />
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-56 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  if (status === "error" && dashboard.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Trading Accounts</h1>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <p className="text-destructive text-sm">{error || "Failed to load accounts."}</p>
          <button
            onClick={() => fetchDashboard()}
            className="mt-4 px-4 py-2 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 transition-all"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Trading Accounts</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Monitor and manage your connected trading accounts
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 self-start sm:self-auto">
          {hasDemoAccounts && (
            <button
              onClick={() => setResetOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-500 font-medium text-sm hover:bg-amber-500/20 active:scale-[0.98] transition-all"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Reset Balance
            </button>
          )}
          {allPositionsCount > 0 && (
            <button
              onClick={() => setKillOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-red-500/30 bg-red-500/10 text-red-500 font-medium text-sm hover:bg-red-500/20 active:scale-[0.98] transition-all"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              Close All
            </button>
          )}
          <button
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Account
          </button>
        </div>
      </div>

      {/* Stats row */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <div className="text-2xl font-bold tabular-nums">${totalEquity.toFixed(2)}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Total Equity</div>
          </div>
          <div className={`rounded-2xl border p-5 ${totalPnl >= 0 ? "border-emerald-500/20 bg-emerald-500/[0.04]" : "border-red-500/20 bg-red-500/[0.04]"}`}>
            <div className={`text-2xl font-bold tabular-nums ${totalPnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
              ${totalPnl.toFixed(2)}
            </div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Unrealised PnL</div>
          </div>
          <div className={`rounded-2xl border p-5 ${totalTodayPnl >= 0 ? "border-emerald-500/20 bg-emerald-500/[0.04]" : "border-red-500/20 bg-red-500/[0.04]"}`}>
            <div className={`text-2xl font-bold tabular-nums ${totalTodayPnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
              ${totalTodayPnl.toFixed(2)}
            </div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Today's PnL</div>
          </div>
          <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-blue-500">{activeCount}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Active</div>
          </div>
          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <div className="text-2xl font-bold tabular-nums">{totalPositions}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Positions</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-1.5 p-1 rounded-xl bg-muted/50 w-fit">
        {(["all", "demo", "live"] as const).map((type) => (
          <button
            key={type}
            onClick={() => dispatch(setFilterType(type))}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${
              filterType === type
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {type.charAt(0).toUpperCase() + type.slice(1)}
          </button>
        ))}
      </div>

      {/* Empty state */}
      {filtered.length === 0 && status !== "loading" && (
        <div className="rounded-2xl border border-dashed border-border/60 p-16 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-muted/50 flex items-center justify-center mb-5">
            <svg className="w-8 h-8 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1.5">No accounts connected</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-xs mx-auto">
            Connect your Bybit trading account to start monitoring your portfolio in real-time.
          </p>
          <button
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 transition-all shadow-lg shadow-primary/25"
          >
            Connect Account
          </button>
        </div>
      )}

      {/* Account Cards */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((card) => (
            <AccountCard key={card.id} card={card} onRefresh={fetchDashboard} />
          ))}
        </div>
      )}

      <AddAccountDialog open={addOpen} onOpenChange={setAddOpen} onCreated={fetchDashboard} />

      {/* Master Kill Switch Dialog */}
      {killOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => { if (!killLoading) { setKillOpen(false); setKillResult(null); } }} />
          <div className="relative bg-card border border-border rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4">
            {!killResult ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center">
                    <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold">Close All Positions</h3>
                    <p className="text-xs text-muted-foreground">Master Kill Switch</p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground mb-2">
                  This will immediately:
                </p>
                <ul className="text-sm text-muted-foreground mb-5 space-y-1 list-disc list-inside">
                  <li>Close <span className="text-foreground font-medium">all open positions</span> on every active account</li>
                  <li>Delete <span className="text-foreground font-medium">all conditional close rules</span></li>
                  <li>Affects <span className="text-foreground font-medium">{allActiveCount} accounts</span> with <span className="text-foreground font-medium">{allPositionsCount} positions</span></li>
                </ul>
                <p className="text-sm text-red-400 font-medium mb-1">This action cannot be undone.</p>
                <p className="text-xs text-muted-foreground mb-5">Note: Active scheduled scans will not be paused. Pause them separately to prevent new trades from opening.</p>
                <div className="flex gap-3">
                  <button
                    onClick={() => setKillOpen(false)}
                    disabled={killLoading}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-border text-sm font-medium hover:bg-muted/50 transition-all"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      setKillLoading(true);
                      try {
                        const res = await accountsApi.masterCloseAll();
                        setKillResult(res);
                        fetchDashboard(true);
                      } catch (e: unknown) {
                        setKillResult({ accounts_processed: 0, total_positions_closed: 0, accounts_failed: 1, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
                      } finally {
                        setKillLoading(false);
                      }
                    }}
                    disabled={killLoading}
                    className="flex-1 px-4 py-2.5 rounded-xl bg-red-600 text-white text-sm font-medium hover:bg-red-700 active:scale-[0.98] transition-all disabled:opacity-50"
                  >
                    {killLoading ? "Closing..." : "Close Everything"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 className="text-lg font-semibold mb-3">Result</h3>
                <div className="space-y-2 text-sm mb-5">
                  <p>Accounts processed: <span className="font-medium">{killResult.accounts_processed}</span></p>
                  <p>Positions closed: <span className="font-medium text-emerald-500">{killResult.total_positions_closed}</span></p>
                  {killResult.accounts_failed > 0 && (
                    <p>Accounts failed: <span className="font-medium text-red-500">{killResult.accounts_failed}</span></p>
                  )}
                  {killResult.results.filter(r => r.status === "error").length > 0 && (
                    <div className="mt-3 max-h-32 overflow-y-auto space-y-1">
                      {killResult.results.filter(r => r.status === "error").map((r, i) => (
                        <p key={i} className="text-xs text-red-400">{r.name || r.account_id}: {r.reason}</p>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => { setKillOpen(false); setKillResult(null); }}
                  className="w-full px-4 py-2.5 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 transition-all"
                >
                  Done
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Demo Reset Balance Dialog */}
      {resetOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => { if (!resetLoading) { setResetOpen(false); setResetResult(null); } }} />
          <div className="relative bg-card border border-border rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4">
            {!resetResult ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                    <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold">Reset Demo Balance</h3>
                    <p className="text-xs text-muted-foreground">Set all demo accounts to a target USDT balance</p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground mb-4">
                  This will adjust the USDT balance on all active demo accounts to match your target amount (adds or removes funds as needed).
                </p>
                <div className="mb-5">
                  <label className="text-sm font-medium mb-1.5 block">Target Balance (USDT)</label>
                  <input
                    type="number"
                    value={resetAmount}
                    onChange={(e) => setResetAmount(e.target.value)}
                    min="1"
                    max="100000"
                    step="1"
                    className="w-full px-3 py-2.5 rounded-xl border border-border bg-background text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary/50"
                    placeholder="100"
                  />
                  <p className="text-xs text-muted-foreground mt-1.5">Max: 100,000 USDT per Bybit demo limits</p>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => setResetOpen(false)}
                    disabled={resetLoading}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-border text-sm font-medium hover:bg-muted/50 transition-all"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      const amount = parseFloat(resetAmount);
                      if (!amount || amount <= 0 || amount > 100000) return;
                      setResetLoading(true);
                      try {
                        const res = await accountsApi.demoResetBalance(amount);
                        setResetResult(res);
                        fetchDashboard(true);
                      } catch (e: unknown) {
                        setResetResult({ target_balance: amount, accounts_processed: 0, success: 0, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
                      } finally {
                        setResetLoading(false);
                      }
                    }}
                    disabled={resetLoading || !resetAmount || parseFloat(resetAmount) <= 0}
                    className="flex-1 px-4 py-2.5 rounded-xl bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 active:scale-[0.98] transition-all disabled:opacity-50"
                  >
                    {resetLoading ? "Resetting..." : "Set Balance"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 className="text-lg font-semibold mb-3">Result</h3>
                <div className="space-y-2 text-sm mb-5">
                  <p>Target: <span className="font-medium">${resetResult.target_balance} USDT</span></p>
                  <p>Accounts processed: <span className="font-medium">{resetResult.accounts_processed}</span></p>
                  <p>Successful: <span className="font-medium text-emerald-500">{resetResult.success}</span></p>
                  {resetResult.results.filter(r => r.status === "error").length > 0 && (
                    <div className="mt-3 max-h-32 overflow-y-auto space-y-1">
                      {resetResult.results.filter(r => r.status === "error").map((r, i) => (
                        <p key={i} className="text-xs text-red-400">{r.name || r.account_id}: {r.reason}</p>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => { setResetOpen(false); setResetResult(null); }}
                  className="w-full px-4 py-2.5 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 transition-all"
                >
                  Done
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
