import { useEffect, useState, useCallback } from "react";
import { accountsApi } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setFilterType, setLoading, setError } from "@/store/accounts-slice";
import { AccountCard } from "./AccountCard";
import { AddAccountDialog } from "./AddAccountDialog";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";
import { Skeleton } from "@/components/ui/skeleton";

export function AccountsDashboard() {
  const dispatch = useAppDispatch();
  const { dashboard, filterType, status, error } = useAppSelector((s) => s.accounts);
  const [addOpen, setAddOpen] = useState(false);
  useAccountWebSocket();

  const fetchDashboard = useCallback(async (silent = false) => {
    if (!silent) dispatch(setLoading());
    try {
      const cards = await accountsApi.getDashboard();
      dispatch(setDashboard(cards));
    } catch (e: unknown) {
      if (!silent) dispatch(setError((e as { message?: string }).message || "Failed to load accounts"));
    }
  }, [dispatch]);

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(() => fetchDashboard(true), 3_000);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  const filtered = dashboard.filter((card) => {
    if (filterType === "all") return true;
    return card.account_type === filterType;
  });

  const totalEquity = filtered.reduce((sum, c) => {
    const v = parseFloat(c.total_equity || "0");
    return sum + (isNaN(v) ? 0 : v);
  }, 0);
  const totalPnl = filtered.reduce((sum, c) => {
    const v = parseFloat(c.total_perp_upl || "0");
    return sum + (isNaN(v) ? 0 : v);
  }, 0);
  const totalTodayPnl = filtered.reduce((sum, c) => {
    const v = parseFloat(c.today_pnl || "0");
    return sum + (isNaN(v) ? 0 : v);
  }, 0);
  const activeCount = filtered.filter((c) => c.status === "active").length;
  const totalPositions = filtered.reduce((sum, c) => sum + (c.positions_count || 0), 0);

  if (status === "loading" && dashboard.length === 0) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-56" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-56 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  if (status === "error" && dashboard.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold tracking-tight">Trading Accounts</h1>
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
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trading Accounts</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Monitor and manage your connected trading accounts
          </p>
        </div>
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((card) => (
            <AccountCard key={card.id} card={card} onRefresh={fetchDashboard} />
          ))}
        </div>
      )}

      <AddAccountDialog open={addOpen} onOpenChange={setAddOpen} onCreated={fetchDashboard} />
    </div>
  );
}
