import { useEffect, useRef, useState, type JSX } from "react";
import { useNavigate } from "@tanstack/react-router";
import { accountsApi, type WalletBalance, type Position, type OpenOrder, type PnlSummary } from "@/api/client";
import { NeuTabs } from "@/design-system/neumorphism";
import { WalletPanel } from "./WalletPanel";
import { PositionsTable } from "./PositionsTable";
import { OrdersTable } from "./OrdersTable";
import { PnLPanel } from "./PnLPanel";
import { AnalyticsDashboard } from "@/components/analytics/AnalyticsDashboard";
import { useAppDispatch, useAppSelector } from "@/store";
import type { RootState } from "@/store";
import { fetchAIManagerStatus } from "@/store/ai-manager-slice";
import { AIMonitorPanel } from "./AIMonitorPanel";
import { removeAccount } from "@/store/accounts-slice";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { NeuInput } from "@/design-system/neumorphism/inputs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AccountDetailViewProps {
  accountId: string;
}

export function AccountDetailView({ accountId }: AccountDetailViewProps) {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const status = useAppSelector((s: RootState) => s.aiManager.statusByAccount[accountId]);
  const [wallet, setWallet] = useState<WalletBalance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [pnlSummary, setPnlSummary] = useState<PnlSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("wallet");
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [showCredentials, setShowCredentials] = useState(false);
  const [credKey, setCredKey] = useState("");
  const [credSecret, setCredSecret] = useState("");
  const [credSaving, setCredSaving] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; });

  useEffect(() => {
    dispatch(fetchAIManagerStatus(accountId));
    // Retry after 5s in case backend is still starting up the AI manager task
    const retryTimer = setTimeout(() => {
      if (!statusRef.current) dispatch(fetchAIManagerStatus(accountId));
    }, 5000);
    return () => clearTimeout(retryTimer);
  }, [dispatch, accountId]);

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

  const renderDialogs = () => (
    <>
      {/* Update Credentials Dialog */}
      <Dialog open={showCredentials} onOpenChange={(open) => {
        if (!credSaving) setShowCredentials(open);
      }}>
        <DialogContent showCloseButton={!credSaving} className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Update API Credentials</DialogTitle>
            <DialogDescription>
              Enter the API credentials for your exchange connection.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 my-2">
            <NeuInput
              type="text"
              placeholder="API Key"
              value={credKey}
              onChange={(e) => setCredKey(e.target.value)}
              disabled={credSaving}
            />
            <NeuInput
              type="password"
              placeholder="API Secret"
              value={credSecret}
              onChange={(e) => setCredSecret(e.target.value)}
              disabled={credSaving}
            />
          </div>
          {credError && <p className="text-destructive text-xs">{credError}</p>}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCredentials(false)}
              disabled={credSaving}
              className="flex-1 sm:flex-initial"
            >
              Cancel
            </Button>
            <Button
              onClick={async () => {
                if (!credKey.trim() || !credSecret.trim()) {
                  setCredError("Both fields are required");
                  return;
                }
                setCredSaving(true);
                setCredError(null);
                try {
                  await accountsApi.rotateCredentials(accountId, { api_key: credKey.trim(), api_secret: credSecret.trim() });
                  setShowCredentials(false);
                  setCredKey("");
                  setCredSecret("");
                  window.location.reload();
                } catch (e: unknown) {
                  const err = e as { detail?: string; message?: string };
                  setCredError(err.detail || err.message || "Failed to update");
                } finally {
                  setCredSaving(false);
                }
              }}
              disabled={credSaving}
              className="flex-1 sm:flex-initial flex items-center justify-center gap-2"
            >
              {credSaving && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteConfirm} onOpenChange={(open) => {
        if (!deleting) setDeleteConfirm(open);
      }}>
        <DialogContent showCloseButton={!deleting} className="max-w-sm">
          <DialogHeader>
            <div className="w-10 h-10 rounded-[calc(var(--radius)*1.2)] bg-red-500/10 flex items-center justify-center mb-2">
              <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </div>
            <DialogTitle>Delete account?</DialogTitle>
            <DialogDescription>
              This will permanently remove this account and all its data. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirm(false)}
              disabled={deleting}
              className="flex-1 sm:flex-initial"
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
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
              className="flex-1 sm:flex-initial flex items-center justify-center gap-2"
            >
              {deleting && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );

  if (loading) {
    return (
      <div className="space-y-5">
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
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => navigate({ to: "/accounts" })}
              className="shrink-0 rounded-xl"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </Button>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">Account Detail</h1>
          </div>
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Button
              variant="outline"
              onClick={() => setShowCredentials(true)}
              className="flex-1 sm:flex-initial"
            >
              Update Credentials
            </Button>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={() => setDeleteConfirm(true)}
              className="flex-1 sm:flex-initial"
            >
              {deleting ? "Deleting..." : "Delete Account"}
            </Button>
          </div>
        </div>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-5 text-center">
          <p className="text-destructive text-sm">{error}</p>
        </div>
        {renderDialogs()}
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => navigate({ to: "/accounts" })}
            className="shrink-0 rounded-xl"
            aria-label="Back to accounts"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </Button>
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">Account Detail</h1>
            <p className="text-sm text-muted-foreground/60 mt-0.5">
              {positions.length} position{positions.length !== 1 ? "s" : ""} · {orders.length} order{orders.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Button
            variant="outline"
            onClick={() => setShowCredentials(true)}
            className="flex-1 sm:flex-initial"
          >
            Update Credentials
          </Button>
          <Button
            variant="destructive"
            disabled={deleting}
            onClick={() => setDeleteConfirm(true)}
            className="flex-1 sm:flex-initial"
          >
            {deleting ? "Deleting..." : "Delete Account"}
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      {wallet && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 neu-grid-enter">
          {kpis.map((kpi) => (
            <div
              key={kpi.label}
              className="rounded-2xl p-4 space-y-2.5 transition-all duration-200 hover:scale-[1.02]"
              style={{
                background: "var(--neu-surface-base)",
                boxShadow: "var(--neu-shadow-pill)",
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">
                  {kpi.label}
                </span>
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                  kpi.color === "emerald" ? "text-emerald-500" :
                  kpi.color === "red" ? "text-red-500" :
                  "text-muted-foreground/60"
                }`}
                  style={{
                    background: "var(--neu-surface-deep)",
                    boxShadow: "var(--neu-shadow-inset)",
                  }}
                >
                  {kpiIcons[kpi.icon]}
                </div>
              </div>
              <div>
                <span className={`text-xl font-bold tabular-nums tracking-tight ${
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
      <NeuTabs
        value={activeTab}
        onValueChange={setActiveTab}
        variant="inset"
        items={[
          { value: "wallet", label: "Wallet", content: wallet ? <WalletPanel wallet={wallet} /> : null },
          { value: "positions", label: <>Positions{positions.length > 0 && <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full bg-[color-mix(in_oklch,var(--neu-accent)_15%,var(--neu-surface-base))] text-[var(--neu-accent)] font-semibold tabular-nums">{positions.length}</span>}</>, content: <PositionsTable positions={positions} /> },
          { value: "orders", label: <>Orders{orders.length > 0 && <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full bg-[color-mix(in_oklch,var(--neu-accent)_15%,var(--neu-surface-base))] text-[var(--neu-accent)] font-semibold tabular-nums">{orders.length}</span>}</>, content: <OrdersTable orders={orders} /> },
          { value: "pnl", label: "PnL", content: <PnLPanel pnlSummary={pnlSummary} accountId={accountId} /> },
          { value: "analytics", label: "Analytics", content: <AnalyticsDashboard accountId={accountId} embedded /> },
          {
            value: "ai-monitor",
            label: (
              <div className="flex items-center gap-1.5">
                <span>AI Monitor</span>
                {status?.enabled && (
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    status.state === "monitoring" ? "bg-blue-400 animate-pulse" :
                    status.state === "executing" ? "bg-green-400 animate-pulse" :
                    status.state === "analyzing" ? "bg-yellow-400 animate-pulse" :
                    status.state === "paused" ? "bg-orange-400" :
                    "bg-muted-foreground/30"
                  }`} />
                )}
              </div>
            ),
            content: <AIMonitorPanel accountId={accountId} />
          },
        ]}
      />

      {renderDialogs()}
    </div>
  );
}
