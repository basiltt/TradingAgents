import { useEffect, useState, type JSX } from "react";
import { useNavigate } from "@tanstack/react-router";
import { accountsApi, type WalletBalance, type Position, type OpenOrder, type PnlSummary } from "@/api/client";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WalletPanel } from "./WalletPanel";
import { PositionsTable } from "./PositionsTable";
import { OrdersTable } from "./OrdersTable";
import { PnLPanel } from "./PnLPanel";
import { AnalyticsDashboard } from "@/components/analytics/AnalyticsDashboard";
import { useAppDispatch } from "@/store";
import { removeAccount } from "@/store/accounts-slice";
import { Skeleton } from "@/components/ui/skeleton";

interface AccountDetailViewProps {
  accountId: string;
}

export function AccountDetailView({ accountId }: AccountDetailViewProps) {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [wallet, setWallet] = useState<WalletBalance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [pnlSummary, setPnlSummary] = useState<PnlSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("wallet");
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [w, p, o] = await Promise.all([
          accountsApi.getWallet(accountId, controller.signal),
          accountsApi.getPositions(accountId, controller.signal),
          accountsApi.getOrders(accountId, controller.signal),
        ]);
        setWallet(w);
        setPositions(p);
        setOrders(o);

        const today = new Date().toISOString().split("T")[0];
        const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString().split("T")[0];
        const summary = await accountsApi.getPnlSummary(accountId, sevenDaysAgo, today, controller.signal);
        setPnlSummary(summary);
      } catch (e: unknown) {
        const err = e as { name?: string; detail?: string; message?: string };
        if (err.name !== "AbortError") setError(err.detail || err.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [accountId]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-56" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
        </div>
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate({ to: "/accounts" })}
            className="p-2 rounded-xl hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Account Detail</h1>
        </div>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <p className="text-destructive text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const equity = parseFloat(wallet?.totalEquity || "0");
  const balance = parseFloat(wallet?.totalWalletBalance || "0");
  const available = parseFloat(wallet?.totalAvailableBalance || "0");
  const uPnl = parseFloat(wallet?.totalPerpUPL || "0");
  const marginUsed = equity > 0 ? ((equity - available) / equity) * 100 : 0;

  const kpis = [
    { label: "Equity", value: `$${equity.toFixed(2)}`, icon: "equity" },
    { label: "Balance", value: `$${balance.toFixed(2)}`, icon: "balance" },
    { label: "Available", value: `$${available.toFixed(2)}`, sub: `${marginUsed.toFixed(0)}% margin used`, icon: "available" },
    { label: "Unrealised PnL", value: `$${uPnl.toFixed(2)}`, color: uPnl >= 0 ? "emerald" : "red", icon: "pnl" },
  ];

  const kpiIcons: Record<string, JSX.Element> = {
    equity: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20 12V8H6a2 2 0 01-2-2c0-1.1.9-2 2-2h12v4" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6v12a2 2 0 002 2h14v-4" />
        <circle cx="18" cy="16" r="1" />
      </svg>
    ),
    balance: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    available: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
      </svg>
    ),
    pnl: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
      </svg>
    ),
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => navigate({ to: "/accounts" })}
            className="p-2 rounded-xl hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground shrink-0"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="min-w-0">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Account Detail</h1>
            <p className="text-sm text-muted-foreground/60 mt-0.5">
              {positions.length} position{positions.length !== 1 ? "s" : ""} · {orders.length} order{orders.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>

        <button
          disabled={deleting}
          onClick={() => setDeleteConfirm(true)}
          className="px-4 py-2 rounded-xl text-sm font-medium bg-red-500/[0.08] text-red-500 border border-red-500/20 hover:bg-red-500/[0.15] hover:border-red-500/30 transition-all disabled:opacity-50 shrink-0 self-start sm:self-auto"
        >
          {deleting ? "Deleting..." : "Delete Account"}
        </button>
      </div>

      {/* KPI Cards */}
      {wallet && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {kpis.map((kpi) => (
            <div
              key={kpi.label}
              className="rounded-2xl border border-border/40 bg-card p-5 space-y-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">
                  {kpi.label}
                </span>
                <div className={`w-8 h-8 rounded-xl flex items-center justify-center ring-1 ring-inset ${
                  kpi.color === "emerald" ? "bg-emerald-500/10 ring-emerald-500/20 text-emerald-500" :
                  kpi.color === "red" ? "bg-red-500/10 ring-red-500/20 text-red-500" :
                  "bg-muted/50 ring-border/30 text-muted-foreground/60"
                }`}>
                  {kpiIcons[kpi.icon]}
                </div>
              </div>
              <div>
                <span className={`text-2xl font-bold tabular-nums tracking-tight ${
                  kpi.color === "emerald" ? "text-emerald-500" :
                  kpi.color === "red" ? "text-red-500" : ""
                }`}>
                  {kpi.value}
                </span>
                {kpi.sub && (
                  <p className="text-[10px] text-muted-foreground/50 mt-1">{kpi.sub}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-muted/30 border border-border/30 rounded-xl p-1 h-auto">
          <TabsTrigger value="wallet" className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">
            <svg className="w-4 h-4 mr-2 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20 12V8H6a2 2 0 01-2-2c0-1.1.9-2 2-2h12v4" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6v12a2 2 0 002 2h14v-4" />
            </svg>
            Wallet
          </TabsTrigger>
          <TabsTrigger value="positions" className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">
            <svg className="w-4 h-4 mr-2 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Positions
            {positions.length > 0 && (
              <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-semibold tabular-nums">
                {positions.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="orders" className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">
            <svg className="w-4 h-4 mr-2 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            Orders
            {orders.length > 0 && (
              <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-semibold tabular-nums">
                {orders.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="pnl" className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">
            <svg className="w-4 h-4 mr-2 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            PnL
          </TabsTrigger>
          <TabsTrigger value="analytics" className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">
            <svg className="w-4 h-4 mr-2 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6m6 0h6m-6 0a2 2 0 01-2-2m8 2V5a2 2 0 012-2h2a2 2 0 012 2v14" />
            </svg>
            Analytics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="wallet" className="mt-6">
          {wallet && <WalletPanel wallet={wallet} />}
        </TabsContent>

        <TabsContent value="positions" className="mt-6">
          <PositionsTable positions={positions} />
        </TabsContent>

        <TabsContent value="orders" className="mt-6">
          <OrdersTable orders={orders} />
        </TabsContent>

        <TabsContent value="pnl" className="mt-6">
          <PnLPanel pnlSummary={pnlSummary} accountId={accountId} />
        </TabsContent>

        <TabsContent value="analytics" className="mt-6">
          <AnalyticsDashboard accountId={accountId} embedded />
        </TabsContent>
      </Tabs>

      {/* Delete Confirmation Dialog */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-md" onClick={() => !deleting && setDeleteConfirm(false)} />
          <div className="relative bg-card border border-border/50 rounded-2xl shadow-2xl p-7 max-w-sm w-full mx-4 space-y-5">
            <div className="w-12 h-12 rounded-2xl bg-red-500/10 flex items-center justify-center">
              <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </div>
            <div>
              <h3 className="text-lg font-bold mb-1">Delete account?</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                This will permanently remove this account and all its data. This cannot be undone.
              </p>
            </div>
            <div className="flex items-center gap-2.5 pt-1">
              <button
                onClick={() => setDeleteConfirm(false)}
                disabled={deleting}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  setDeleting(true);
                  try {
                    await accountsApi.delete(accountId);
                    dispatch(removeAccount(accountId));
                    navigate({ to: "/accounts" });
                  } catch {
                    setDeleting(false);
                    setDeleteConfirm(false);
                  }
                }}
                disabled={deleting}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {deleting && (
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                )}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
