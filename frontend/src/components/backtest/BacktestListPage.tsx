import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
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

  // Clear-all: deletes every terminal run (running/pending are preserved server-side).
  const clearAllMutation = useMutation({
    mutationFn: () => backtestApi.removeAll(),
    onSuccess: (res) => {
      toast.success(`Deleted ${res?.deleted ?? 0} backtest${(res?.deleted ?? 0) === 1 ? "" : "s"}.`);
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["backtest", "list"] });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to clear backtests");
    },
  });

  // ── Sort + filter (client-side, over the already-loaded list) ──
  type StatusFilter = "all" | "completed" | "failed" | "cancelled" | "running";
  type SortKey = "created" | "net_profit" | "return" | "status";
  type SortDir = "asc" | "desc";
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [sortKey, setSortKey] = React.useState<SortKey>("created");
  const [sortDir, setSortDir] = React.useState<SortDir>("desc");

  const allRuns = data ?? [];

  const visibleRuns = React.useMemo(() => {
    const filtered =
      statusFilter === "all"
        ? allRuns
        : allRuns.filter((r) =>
            statusFilter === "running" ? isActiveStatus(r.status) : r.status === statusFilter,
          );
    // Nulls (N/A metrics, e.g. failed runs) always sort to the bottom regardless of dir.
    const numOr = (v: number | null | undefined) =>
      v == null || !Number.isFinite(v) ? null : v;
    const cmp = (a: BacktestRun, b: BacktestRun): number => {
      let av: number | string | null;
      let bv: number | string | null;
      switch (sortKey) {
        case "net_profit":
          av = numOr(netProfit(a));
          bv = numOr(netProfit(b));
          break;
        case "return":
          av = numOr(netProfitPct(a));
          bv = numOr(netProfitPct(b));
          break;
        case "status":
          av = a.status;
          bv = b.status;
          break;
        case "created":
        default:
          av = a.created_at ?? "";
          bv = b.created_at ?? "";
          break;
      }
      // Push nulls to the bottom in BOTH directions.
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      let base: number;
      if (typeof av === "number" && typeof bv === "number") base = av - bv;
      else base = String(av).localeCompare(String(bv));
      return sortDir === "asc" ? base : -base;
    };
    return [...filtered].sort(cmp);
  }, [allRuns, statusFilter, sortKey, sortDir]);

  const runs = visibleRuns;

  const toggleSelect = (runId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else if (next.size < MAX_COMPARE_RUNS) next.add(runId);
      return next;
    });
  };

  const handleDelete = (runId: string) => {
    // In-app confirm (replaces the native window.confirm) — guard against accidental
    // clicks, matching the app's dialog style.
    setConfirm({ kind: "single", runId });
  };

  const handleClearAll = () => {
    const terminalCount = allRuns.filter((r) => isTerminalStatus(r.status)).length;
    if (terminalCount === 0) {
      toast.info("No finished backtests to clear.");
      return;
    }
    setConfirm({ kind: "all", count: terminalCount });
  };

  // Pending confirmation (null when no dialog is open).
  type Confirm =
    | { kind: "single"; runId: string }
    | { kind: "all"; count: number }
    | null;
  const [confirm, setConfirm] = React.useState<Confirm>(null);

  const confirmInFlight =
    confirm?.kind === "single" ? deletingId === confirm.runId : clearAllMutation.isPending;

  const runConfirm = () => {
    if (!confirm) return;
    if (confirm.kind === "single") {
      const runId = confirm.runId;
      setDeletingId(runId);
      removeMutation.mutate(runId, {
        onSettled: () => setDeletingId(null),
        onSuccess: () => setConfirm(null),
      });
    } else {
      clearAllMutation.mutate(undefined, { onSuccess: () => setConfirm(null) });
    }
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
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            aria-label="Filter by status"
            className="h-8 rounded-[var(--neu-radius-sm)] border border-[color:var(--neu-stroke-soft)]/60 bg-[var(--neu-surface-inset)]/40 px-2 text-xs text-[var(--neu-text)]"
          >
            <option value="all">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="running">Running</option>
          </select>
          {/* Sort key */}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            aria-label="Sort by"
            className="h-8 rounded-[var(--neu-radius-sm)] border border-[color:var(--neu-stroke-soft)]/60 bg-[var(--neu-surface-inset)]/40 px-2 text-xs text-[var(--neu-text)]"
          >
            <option value="created">Sort: Created</option>
            <option value="net_profit">Sort: Net Profit</option>
            <option value="return">Sort: Return</option>
            <option value="status">Sort: Status</option>
          </select>
          {/* Sort direction toggle */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
            aria-label={`Sort direction: ${sortDir === "asc" ? "ascending" : "descending"}`}
            title={sortDir === "asc" ? "Ascending" : "Descending"}
          >
            {sortDir === "asc" ? "↑ Asc" : "↓ Desc"}
          </Button>
          {selected.size >= MIN_COMPARE_RUNS ? (
            <Button variant="outline" size="sm" onClick={() => onCompare?.(Array.from(selected))}>
              Compare ({selected.size})
            </Button>
          ) : null}
          {allRuns.some((r) => isTerminalStatus(r.status)) ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleClearAll}
              disabled={clearAllMutation.isPending}
              className="text-[var(--neu-danger)]"
            >
              {clearAllMutation.isPending ? "Clearing…" : "Clear all"}
            </Button>
          ) : null}
          <Button size="sm" onClick={onCreate}>
            New Backtest
          </Button>
        </div>
      </div>

      {runs.length === 0 ? (
        allRuns.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-sm text-[var(--neu-text-muted)]">No backtests yet.</p>
            <Button onClick={onCreate}>Run your first backtest</Button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-sm text-[var(--neu-text-muted)]">
              No backtests match the “{statusFilter}” filter.
            </p>
            <Button variant="outline" size="sm" onClick={() => setStatusFilter("all")}>
              Show all
            </Button>
          </div>
        )
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

      {/* In-app confirm dialog (replaces native window.confirm) for delete + clear-all. */}
      <Dialog open={confirm !== null} onOpenChange={(o) => !o && !confirmInFlight && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm?.kind === "all" ? "Clear all backtests" : "Delete backtest"}
            </DialogTitle>
            <DialogDescription>
              {confirm?.kind === "all"
                ? `Delete all ${confirm.count} finished backtest${confirm.count === 1 ? "" : "s"}? Running backtests are kept.`
                : "Delete this backtest run and its results?"}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-[var(--neu-text-muted)]">This action cannot be undone.</p>
          <DialogFooter>
            <Button
              variant="outline"
              className="cursor-pointer"
              onClick={() => setConfirm(null)}
              disabled={confirmInFlight}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              className="cursor-pointer"
              onClick={runConfirm}
              disabled={confirmInFlight}
            >
              {confirmInFlight
                ? confirm?.kind === "all"
                  ? "Clearing…"
                  : "Deleting…"
                : confirm?.kind === "all"
                  ? `Delete ${confirm.count}`
                  : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
