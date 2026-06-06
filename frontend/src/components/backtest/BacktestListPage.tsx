import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { backtestApi } from "@/api/client";
import { BACKTEST_POLL_INTERVAL_MS } from "@/hooks/useBacktestPolling";
import { isTerminalStatus, isActiveStatus, type BacktestRun } from "./types";
import { BacktestStatusBadge } from "./BacktestStatusBadge";
import { formatUsd, formatPct, formatDateTime, TH_CLASS, TH_CLASS_RIGHT } from "./format";
import { getBasket, removeFromBasket, MAX_COMPARE_RUNS } from "./comparisonBasket";

export interface BacktestListPageProps {
  /** Navigate to a run's results. */
  onOpen?: (runId: string) => void;
  /** Navigate to the new-backtest form. */
  onCreate?: () => void;
  /** Navigate to the compare view with the selected run ids. */
  onCompare?: (runIds: string[]) => void;
}

/** Compare supports between this many runs (inclusive). */
const MIN_COMPARE_RUNS = 2;

function netProfit(run: BacktestRun): number | null {
  return run.results?.metrics?.net_profit ?? null;
}
function netProfitPct(run: BacktestRun): number | null {
  return run.results?.metrics?.net_profit_pct ?? null;
}

export function BacktestListPage({ onOpen, onCreate, onCompare }: BacktestListPageProps) {
  const queryClient = useQueryClient();
  // Seed the selection from the comparison basket (populated via "Add to
  // comparison" on the results page) so the two entry points stay in sync.
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set(getBasket()));

  const { data, isLoading, error } = useQuery({
    queryKey: ["backtest", "list"],
    queryFn: ({ signal }) => backtestApi.list(undefined, signal),
    // Keep the list fresh while any run is still in flight.
    refetchInterval: (query) => {
      const runs = (query.state.data ?? []) as BacktestRun[];
      const anyActive = runs.some((r) => isActiveStatus(r.status));
      return anyActive ? BACKTEST_POLL_INTERVAL_MS : false;
    },
  });

  const removeMutation = useMutation({
    mutationFn: (runId: string) => backtestApi.remove(runId),
    onSuccess: (_data, runId) => {
      // Drop the deleted id from BOTH the local selection and the persistent
      // comparison basket so a phantom id can't reach the compare endpoint.
      removeFromBasket(runId);
      setSelected((prev) => {
        if (!prev.has(runId)) return prev;
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["backtest", "list"] });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to delete backtest");
    },
  });
  const [deletingId, setDeletingId] = React.useState<string | null>(null);

  const runs = data ?? [];

  const toggleSelect = (runId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else if (next.size < MAX_COMPARE_RUNS) next.add(runId);
      return next;
    });
  };

  const handleDelete = (runId: string) => {
    // Permanent removal — guard against accidental clicks like Cancel does.
    if (typeof window !== "undefined" && !window.confirm("Delete this backtest? This cannot be undone.")) {
      return;
    }
    setDeletingId(runId);
    removeMutation.mutate(runId, { onSettled: () => setDeletingId(null) });
  };

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="list-loading">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="py-10 text-center text-sm text-[var(--neu-danger)]">
        {error instanceof Error ? error.message : "Failed to load backtests."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="backtest-list-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold tracking-tight text-[var(--neu-text-strong)]">Backtests</h1>
        <div className="ml-auto flex gap-2">
          {selected.size >= MIN_COMPARE_RUNS ? (
            <Button variant="outline" size="sm" onClick={() => onCompare?.(Array.from(selected))}>
              Compare ({selected.size})
            </Button>
          ) : null}
          <Button size="sm" onClick={onCreate}>
            New Backtest
          </Button>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-sm text-[var(--neu-text-muted)]">No backtests yet.</p>
          <Button onClick={onCreate}>Run your first backtest</Button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/60">
          <table className="w-full border-collapse text-sm" data-testid="runs-table">
            <caption className="sr-only">Backtest runs</caption>
            <thead>
              <tr className="bg-[color:var(--neu-surface-inset)]/40 text-left">
                <th scope="col" className={cn("px-3 py-2", TH_CLASS)}>
                  <span className="sr-only">Select</span>
                </th>
                <th scope="col" className={cn("px-3 py-2", TH_CLASS)}>Created</th>
                <th scope="col" className={cn("px-3 py-2", TH_CLASS)}>Status</th>
                <th scope="col" className={cn("px-3 py-2", TH_CLASS_RIGHT)}>Net Profit</th>
                <th scope="col" className={cn("px-3 py-2", TH_CLASS_RIGHT)}>Return</th>
                <th scope="col" className={cn("px-3 py-2", TH_CLASS_RIGHT)}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const np = netProfit(r);
                const npp = netProfitPct(r);
                return (
                  <tr
                    key={r.id}
                    className="border-t border-[color:var(--neu-stroke-soft)]/40 hover:bg-[color:var(--neu-surface-inset)]/30"
                    data-testid="run-row"
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(r.id)}
                        onChange={() => toggleSelect(r.id)}
                        aria-label={`Select ${r.id}`}
                        disabled={r.status !== "completed"}
                      />
                    </td>
                    <td className="px-3 py-2 tabular-nums text-[var(--neu-text-muted)]">{formatDateTime(r.created_at)}</td>
                    <td className="px-3 py-2">
                      <BacktestStatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatUsd(np, { sign: true })}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatPct(npp, { sign: true })}</td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="xs" onClick={() => onOpen?.(r.id)}>
                          Open
                        </Button>
                        {isTerminalStatus(r.status) ? (
                          <Button
                            variant="ghost"
                            size="xs"
                            onClick={() => handleDelete(r.id)}
                            disabled={deletingId === r.id}
                            aria-label={`Delete ${r.id}`}
                          >
                            {deletingId === r.id ? "Deleting…" : "Delete"}
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
