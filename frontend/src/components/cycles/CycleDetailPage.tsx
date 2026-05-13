import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cyclesApi, ApiError } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, isActive } from "./utils";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  placing_trades: "default",
  running: "default",
  stopping: "secondary",
  completed: "secondary",
  stopped: "outline",
  failed: "destructive",
};

const TRADE_STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  submitted: "default",
  filled: "secondary",
  failed: "destructive",
  cancelled: "outline",
};

export function CycleDetailPage({ cycleId }: { cycleId: string }) {
  const id = Number(cycleId);
  const queryClient = useQueryClient();
  const [confirmStop, setConfirmStop] = useState(false);

  const { data: cycle, isLoading, error, refetch } = useQuery({
    queryKey: ["cycles", id],
    queryFn: ({ signal }) => cyclesApi.get(id, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isActive(status) ? 5000 : false;
    },
  });

  const stopMutation = useMutation({
    mutationFn: () => cyclesApi.stop(id),
    onSuccess: () => {
      toast.success("Cycle stop requested");
      queryClient.invalidateQueries({ queryKey: ["cycles"] });
      setConfirmStop(false);
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message);
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !cycle) {
    return (
      <div className="space-y-6">
        <Link to="/cycles" className="text-sm text-primary hover:underline flex items-center gap-1">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to cycles
        </Link>
        <Card>
          <CardContent className="py-8 text-center text-destructive">
            <p>Cycle not found or failed to load.</p>
            <button onClick={() => refetch()} className="text-sm text-primary hover:underline mt-2">Retry</button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const canStop = isActive(cycle.status) && cycle.status !== "stopping";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link to="/cycles" className="text-sm text-primary hover:underline flex items-center gap-1 mb-3">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Back to cycles
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            Cycle #{cycle.id}
            <Badge variant={STATUS_VARIANT[cycle.status] ?? "outline"}>
              {cycle.status.replace("_", " ")}
            </Badge>
          </h1>
        </div>
        {canStop && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setConfirmStop(true)}
          >
            Stop Cycle
          </Button>
        )}
      </div>

      {/* Configuration */}
      <Card>
        <CardContent className="py-5">
          <h2 className="font-semibold text-sm mb-3">Configuration</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground text-xs">Direction</span>
              <p className="font-medium capitalize">{cycle.trade_direction}</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Leverage</span>
              <p className="font-medium">{cycle.leverage}x</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Capital %</span>
              <p className="font-medium">{cycle.capital_pct}%</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Max Trades</span>
              <p className="font-medium">{cycle.max_trades}</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Target</span>
              <p className="font-medium">
                {cycle.target_type === "percentage" ? `${cycle.target_value}%` : `$${cycle.target_value}`}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Max Drawdown</span>
              <p className="font-medium">{cycle.max_drawdown_pct}%</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Min Score</span>
              <p className="font-medium">{cycle.min_score}</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Min Confidence</span>
              <p className="font-medium capitalize">{cycle.min_confidence}</p>
            </div>
            {cycle.take_profit_pct != null && (
              <div>
                <span className="text-muted-foreground text-xs">TP %</span>
                <p className="font-medium">{cycle.take_profit_pct}%</p>
              </div>
            )}
            {cycle.stop_loss_pct != null && (
              <div>
                <span className="text-muted-foreground text-xs">SL %</span>
                <p className="font-medium">{cycle.stop_loss_pct}%</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Status */}
      <Card>
        <CardContent className="py-5">
          <h2 className="font-semibold text-sm mb-3">Status</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground text-xs">Trades Placed</span>
              <p className="font-medium text-emerald-500">{cycle.trades_placed}</p>
            </div>
            <div>
              <span className="text-muted-foreground text-xs">Trades Failed</span>
              <p className="font-medium text-destructive">{cycle.trades_failed}</p>
            </div>
            {cycle.initial_equity != null && (
              <div>
                <span className="text-muted-foreground text-xs">Initial Equity</span>
                <p className="font-medium">${cycle.initial_equity.toFixed(2)}</p>
              </div>
            )}
            {cycle.final_pnl != null && (
              <div>
                <span className="text-muted-foreground text-xs">Final PnL</span>
                <p className={`font-medium ${cycle.final_pnl >= 0 ? "text-emerald-500" : "text-destructive"}`}>
                  {cycle.final_pnl >= 0 ? "+" : ""}${cycle.final_pnl.toFixed(2)}
                </p>
              </div>
            )}
            <div>
              <span className="text-muted-foreground text-xs">Created</span>
              <p className="font-medium">{formatDate(cycle.created_at)}</p>
            </div>
            {cycle.started_at && (
              <div>
                <span className="text-muted-foreground text-xs">Started</span>
                <p className="font-medium">{formatDate(cycle.started_at)}</p>
              </div>
            )}
            {cycle.completed_at && (
              <div>
                <span className="text-muted-foreground text-xs">Completed</span>
                <p className="font-medium">{formatDate(cycle.completed_at)}</p>
              </div>
            )}
            {cycle.stop_reason && (
              <div>
                <span className="text-muted-foreground text-xs">Stop Reason</span>
                <p className="font-medium text-orange-500">{cycle.stop_reason}</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Trades */}
      {cycle.trades && cycle.trades.length > 0 && (
        <Card>
          <CardContent className="py-5">
            <h2 className="font-semibold text-sm mb-3">Trades ({cycle.trades.length})</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="Cycle trades">
                <thead>
                  <tr className="border-b border-border/50 text-xs text-muted-foreground">
                    <th className="text-left px-3 py-2 font-medium">Symbol</th>
                    <th className="text-left px-3 py-2 font-medium">Side</th>
                    <th className="text-right px-3 py-2 font-medium">Qty</th>
                    <th className="text-right px-3 py-2 font-medium">Entry Price</th>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium hidden md:table-cell">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {cycle.trades.map((t) => (
                    <tr key={t.id} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                      <td className="px-3 py-2 font-mono font-semibold">{t.symbol}</td>
                      <td className="px-3 py-2">
                        <span className={t.side === "Buy" ? "text-emerald-500" : "text-red-500"}>
                          {t.side}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{t.qty ?? "—"}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {t.entry_price != null ? `$${t.entry_price}` : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={TRADE_STATUS_VARIANT[t.status] ?? "outline"}>
                          {t.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs text-destructive hidden md:table-cell max-w-48 truncate">
                        {t.error_msg ?? ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stop Confirmation */}
      {confirmStop && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="alertdialog" aria-modal="true" aria-labelledby="stop-cycle-title" onKeyDown={(e) => { if (e.key === "Escape" && !stopMutation.isPending) setConfirmStop(false); }}>
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-md"
            onClick={() => !stopMutation.isPending && setConfirmStop(false)}
          />
          <div className="relative bg-card border border-border/50 rounded-2xl shadow-2xl p-7 max-w-sm w-full mx-4 space-y-5">
            <div className="w-12 h-12 rounded-2xl bg-red-500/10 flex items-center justify-center">
              <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <h3 id="stop-cycle-title" className="text-lg font-bold mb-1">Stop Trading Cycle?</h3>
              <p className="text-sm text-muted-foreground">
                This will cancel any pending trades and close all positions opened by this cycle.
              </p>
            </div>
            <div className="flex items-center gap-2.5 pt-1">
              <button
                onClick={() => setConfirmStop(false)}
                disabled={stopMutation.isPending}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => stopMutation.mutate()}
                disabled={stopMutation.isPending}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {stopMutation.isPending && (
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                )}
                Stop Cycle
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
