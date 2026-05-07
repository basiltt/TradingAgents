import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { accountsApi, type WalletBalance, type Position, type OpenOrder, type PnlSummary } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WalletPanel } from "./WalletPanel";
import { PositionsTable } from "./PositionsTable";
import { OrdersTable } from "./OrdersTable";
import { PnLPanel } from "./PnLPanel";

interface AccountDetailViewProps {
  accountId: string;
}

export function AccountDetailView({ accountId }: AccountDetailViewProps) {
  const navigate = useNavigate();
  const [wallet, setWallet] = useState<WalletBalance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [pnlSummary, setPnlSummary] = useState<PnlSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("wallet");

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
      } catch (e: any) {
        if (e.name !== "AbortError") setError(e.detail || e.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [accountId]);

  if (loading) {
    return (
      <div className="p-4 space-y-4">
        <div className="h-8 w-48 animate-pulse bg-muted rounded" />
        <div className="h-64 animate-pulse bg-muted rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="rounded border border-red-200 bg-red-50 p-4">
          <p className="text-red-700">{error}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => navigate({ to: "/accounts" })}>
            Back to Accounts
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate({ to: "/accounts" })}>
          ← Back
        </Button>
        <h1 className="text-xl font-bold">Account Detail</h1>
      </div>

      {/* Wallet Summary */}
      {wallet && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Equity</p>
            <p className="text-lg font-bold">${parseFloat(wallet.totalEquity).toFixed(2)}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Balance</p>
            <p className="text-lg font-bold">${parseFloat(wallet.totalWalletBalance).toFixed(2)}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Available</p>
            <p className="text-lg font-bold">${parseFloat(wallet.totalAvailableBalance).toFixed(2)}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Unrealised PnL</p>
            <p className={`text-lg font-bold ${parseFloat(wallet.totalPerpUPL) >= 0 ? "text-green-600" : "text-red-600"}`}>
              ${parseFloat(wallet.totalPerpUPL).toFixed(2)}
            </p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="wallet">Wallet</TabsTrigger>
          <TabsTrigger value="positions">Positions ({positions.length})</TabsTrigger>
          <TabsTrigger value="orders">Orders ({orders.length})</TabsTrigger>
          <TabsTrigger value="pnl">PnL</TabsTrigger>
        </TabsList>

        <TabsContent value="wallet">
          {wallet && <WalletPanel wallet={wallet} />}
        </TabsContent>

        <TabsContent value="positions">
          <PositionsTable positions={positions} />
        </TabsContent>

        <TabsContent value="orders">
          <OrdersTable orders={orders} />
        </TabsContent>

        <TabsContent value="pnl">
          <PnLPanel pnlSummary={pnlSummary} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
