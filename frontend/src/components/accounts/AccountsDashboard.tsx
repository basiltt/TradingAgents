import { useEffect, useState, useCallback } from "react";
import { accountsApi, type DashboardCard } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setFilterType, setLoading, setError } from "@/store/accounts-slice";
import { AccountCard } from "./AccountCard";
import { AddAccountDialog } from "./AddAccountDialog";
import { Button } from "@/components/ui/button";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";

export function AccountsDashboard() {
  const dispatch = useAppDispatch();
  const { dashboard, filterType, status, error } = useAppSelector((s) => s.accounts);
  const [addOpen, setAddOpen] = useState(false);
  useAccountWebSocket();

  const fetchDashboard = useCallback(async () => {
    dispatch(setLoading());
    try {
      const cards = await accountsApi.getDashboard();
      dispatch(setDashboard(cards));
    } catch (e: any) {
      dispatch(setError(e.message || "Failed to load accounts"));
    }
  }, [dispatch]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const filtered = dashboard.filter((card) => {
    if (filterType === "all") return true;
    return card.account_type === filterType;
  });

  const totalEquity = filtered
    .reduce((sum, c) => { const v = parseFloat(c.total_equity || "0"); return sum + (isNaN(v) ? 0 : v); }, 0)
    .toFixed(2);
  const totalPnl = filtered
    .reduce((sum, c) => { const v = parseFloat(c.total_perp_upl || "0"); return sum + (isNaN(v) ? 0 : v); }, 0)
    .toFixed(2);

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trading Accounts</h1>
        <Button onClick={() => setAddOpen(true)}>+ Add Account</Button>
      </div>

      {/* Aggregate Summary */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="rounded-lg border p-4">
            <p className="text-sm text-muted-foreground">Total Equity</p>
            <p className="text-2xl font-bold">${totalEquity}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-sm text-muted-foreground">Unrealised PnL</p>
            <p className={`text-2xl font-bold ${parseFloat(totalPnl) >= 0 ? "text-green-600" : "text-red-600"}`}>
              ${totalPnl}
            </p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-sm text-muted-foreground">Active Accounts</p>
            <p className="text-2xl font-bold">{filtered.filter((c) => c.status === "active").length}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
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

      {/* Account Cards */}
      {status === "loading" && dashboard.length === 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-lg border animate-pulse bg-muted" />
          ))}
        </div>
      )}

      {status === "error" && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-red-700">{error}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={fetchDashboard}>
            Retry
          </Button>
        </div>
      )}

      {filtered.length === 0 && status !== "loading" && (
        <div className="text-center py-12">
          <p className="text-lg text-muted-foreground mb-4">No accounts connected yet</p>
          <Button onClick={() => setAddOpen(true)}>Connect your first account</Button>
        </div>
      )}

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
