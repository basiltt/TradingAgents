import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { cyclesApi, type CycleResponse } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatDate, isActive } from "./utils";

const STATUS_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Pending", variant: "outline" },
  placing_trades: { label: "Placing", variant: "default" },
  running: { label: "Running", variant: "default" },
  stopping: { label: "Stopping", variant: "secondary" },
  completed: { label: "Completed", variant: "secondary" },
  stopped: { label: "Stopped", variant: "outline" },
  failed: { label: "Failed", variant: "destructive" },
};

export function CycleListPage() {
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["cycles", offset, limit],
    queryFn: ({ signal }) => cyclesApi.list({ offset, limit }, signal),
    refetchInterval: (query) => {
      const hasActive = query.state.data?.items?.some((c) => isActive(c.status));
      return hasActive ? 5000 : 30000;
    },
  });

  const items: CycleResponse[] = data?.items ?? [];
  const total = data?.total ?? 0;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-56" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold tracking-tight">Trading Cycles</h1>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <p className="text-destructive text-sm mb-3">Failed to load trading cycles.</p>
          <button
            onClick={() => refetch()}
            className="text-sm text-primary hover:underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trading Cycles</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Monitor and manage your automated trading cycles
          </p>
        </div>
        <Link
          to="/scanner/history"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          New Cycle
        </Link>
      </div>

      {items.length === 0 ? (
        <div className="rounded-2xl border border-border/50 bg-card p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </div>
          <p className="text-muted-foreground text-sm mb-3">No trading cycles yet</p>
          <Link to="/scanner/history" className="text-sm text-primary hover:underline">
            Start one from Scan History
          </Link>
        </div>
      ) : (
        <>
          {/* Mobile card layout */}
          <div className="grid grid-cols-1 gap-3 sm:hidden">
            {items.map((cycle) => {
              const cfg = STATUS_CONFIG[cycle.status] ?? STATUS_CONFIG.pending;
              return (
                <Link
                  key={cycle.id}
                  to="/cycles/$cycleId"
                  params={{ cycleId: String(cycle.id) }}
                  className="block rounded-xl border border-border/50 bg-card p-4 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-sm font-semibold">Cycle #{cycle.id}</span>
                    <Badge variant={cfg.variant}>{cfg.label}</Badge>
                  </div>
                  <div className="text-xs text-muted-foreground space-y-1">
                    <p>Trades: {cycle.trades_placed} placed, {cycle.trades_failed} failed</p>
                    <p>{formatDate(cycle.created_at)}</p>
                    {cycle.stop_reason && <p className="text-orange-500">Reason: {cycle.stop_reason}</p>}
                  </div>
                </Link>
              );
            })}
          </div>

          {/* Desktop table */}
          <div className="hidden sm:block rounded-2xl border border-border/50 bg-card overflow-hidden">
            <table className="w-full text-sm" aria-label="Trading cycles">
              <thead>
                <tr className="border-b border-border/50 text-xs text-muted-foreground">
                  <th className="text-left px-4 py-3 font-medium">Cycle</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-left px-4 py-3 font-medium">Trades</th>
                  <th className="text-left px-4 py-3 font-medium">Created</th>
                  <th className="text-left px-4 py-3 font-medium">Completed</th>
                  <th className="text-right px-4 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((cycle) => {
                  const cfg = STATUS_CONFIG[cycle.status] ?? STATUS_CONFIG.pending;
                  return (
                    <tr key={cycle.id} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3 font-mono font-semibold">#{cycle.id}</td>
                      <td className="px-4 py-3">
                        <Badge variant={cfg.variant}>{cfg.label}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-emerald-500">{cycle.trades_placed}</span>
                        {cycle.trades_failed > 0 && (
                          <span className="text-destructive ml-1">/ {cycle.trades_failed} failed</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDate(cycle.created_at)}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDate(cycle.completed_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          to="/cycles/$cycleId"
                          params={{ cycleId: String(cycle.id) }}
                          className="text-xs text-primary hover:underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > limit && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  disabled={offset === 0}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setOffset(offset + limit)}
                  disabled={offset + limit >= total}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
