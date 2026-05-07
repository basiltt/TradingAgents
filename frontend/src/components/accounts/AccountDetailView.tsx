import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { accountsApi, type WalletBalance, type Position, type OpenOrder, type PnlSummary } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
          {wallet && wallet.coin.length > 0 && (
            <div className="rounded border">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="text-left p-2">Coin</th>
                    <th className="text-right p-2">Balance</th>
                    <th className="text-right p-2">Equity</th>
                    <th className="text-right p-2">Unrealised PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {wallet.coin.map((c, i) => (
                    <tr key={i} className="border-t">
                      <td className="p-2 font-medium">{c.coin}</td>
                      <td className="p-2 text-right">{parseFloat(c.walletBalance || "0").toFixed(4)}</td>
                      <td className="p-2 text-right">{parseFloat(c.equity || "0").toFixed(4)}</td>
                      <td className="p-2 text-right">{parseFloat(c.unrealisedPnl || "0").toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="positions">
          {positions.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">No open positions</p>
          ) : (
            <div className="rounded border overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="text-left p-2">Symbol</th>
                    <th className="text-left p-2">Side</th>
                    <th className="text-right p-2">Size</th>
                    <th className="text-right p-2">Entry</th>
                    <th className="text-right p-2">Mark</th>
                    <th className="text-right p-2">PnL</th>
                    <th className="text-right p-2">Leverage</th>
                    <th className="text-right p-2">Liq. Price</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, i) => {
                    const pnl = parseFloat(p.unrealisedPnl);
                    const mark = parseFloat(p.markPrice);
                    const liq = parseFloat(p.liqPrice);
                    const distToLiq = liq > 0 ? Math.abs((mark - liq) / mark * 100) : 999;
                    const liqWarning = distToLiq <= 5 ? "text-red-600 font-bold" : distToLiq <= 15 ? "text-amber-600" : "";
                    return (
                      <tr key={i} className="border-t">
                        <td className="p-2 font-medium">{p.symbol}</td>
                        <td className="p-2">
                          <Badge variant={p.side === "Buy" ? "default" : "destructive"} className="text-xs">
                            {p.side === "Buy" ? "Long" : "Short"}
                          </Badge>
                        </td>
                        <td className="p-2 text-right">{p.size}</td>
                        <td className="p-2 text-right">{parseFloat(p.avgPrice).toFixed(2)}</td>
                        <td className="p-2 text-right">{mark.toFixed(2)}</td>
                        <td className={`p-2 text-right ${pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                          ${pnl.toFixed(2)}
                        </td>
                        <td className="p-2 text-right">{p.leverage}x</td>
                        <td className={`p-2 text-right ${liqWarning}`}>
                          {liq > 0 ? `$${liq.toFixed(2)}` : "—"}
                          {distToLiq <= 15 && <span className="ml-1 text-xs">({distToLiq.toFixed(1)}%)</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="orders">
          {orders.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">No open orders</p>
          ) : (
            <div className="rounded border overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="text-left p-2">Symbol</th>
                    <th className="text-left p-2">Side</th>
                    <th className="text-left p-2">Type</th>
                    <th className="text-right p-2">Qty</th>
                    <th className="text-right p-2">Price</th>
                    <th className="text-left p-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o, i) => (
                    <tr key={i} className="border-t">
                      <td className="p-2 font-medium">{o.symbol}</td>
                      <td className="p-2">{o.side}</td>
                      <td className="p-2">{o.orderType}{o.stopOrderType ? ` (${o.stopOrderType})` : ""}</td>
                      <td className="p-2 text-right">{o.qty}</td>
                      <td className="p-2 text-right">{o.price !== "0" ? `$${parseFloat(o.price).toFixed(2)}` : "Market"}</td>
                      <td className="p-2">{o.orderStatus}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="pnl">
          {pnlSummary ? (
            <div className="space-y-4">
              <h3 className="font-semibold">7-Day PnL Summary</h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Total PnL</p>
                  <p className={`text-lg font-bold ${parseFloat(pnlSummary.total_pnl) >= 0 ? "text-green-600" : "text-red-600"}`}>
                    ${parseFloat(pnlSummary.total_pnl).toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Win Rate</p>
                  <p className="text-lg font-bold">{pnlSummary.win_rate.toFixed(1)}%</p>
                  <p className="text-xs text-muted-foreground">{pnlSummary.win_count}W / {pnlSummary.loss_count}L</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Avg Win / Loss</p>
                  <p className="text-sm">
                    <span className="text-green-600">${parseFloat(pnlSummary.avg_win).toFixed(2)}</span>
                    {" / "}
                    <span className="text-red-600">${parseFloat(pnlSummary.avg_loss).toFixed(2)}</span>
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground text-center py-8">No PnL data available</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
