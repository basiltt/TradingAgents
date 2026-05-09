import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient, type ScanStatus } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatDuration(startedAt: string, completedAt: string | null): string {
  if (!startedAt) return "";
  const diff = Math.max(0, (completedAt ? new Date(completedAt).getTime() : Date.now()) - new Date(startedAt).getTime());
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "bg-blue-500 animate-pulse shadow-blue-500/50",
    completed: "bg-emerald-500 shadow-emerald-500/50",
    failed: "bg-red-500 shadow-red-500/50",
    cancelled: "bg-zinc-400 shadow-zinc-400/50",
  };
  return <span className={`w-2 h-2 rounded-full shadow-[0_0_6px] ${colors[status] ?? colors.cancelled}`} />;
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-24 h-2 rounded-full bg-white/[0.06] overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono tabular-nums opacity-70">{value}</span>
    </div>
  );
}

interface DeleteConfirmState {
  scanId: string;
  analysisCount: number | null;
  loading: boolean;
}

export function ScanHistoryPage() {
  const queryClient = useQueryClient();
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["scans"],
    queryFn: ({ signal }) => apiClient.listScans(signal),
    refetchInterval: 15000,
  });

  const deleteMutation = useMutation({
    mutationFn: (scanId: string) => apiClient.deleteScan(scanId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scans"] });
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      setDeleteConfirm(null);
    },
  });

  const handleDeleteClick = async (e: React.MouseEvent, scanId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDeleteConfirm({ scanId, analysisCount: null, loading: true });
    try {
      const preview = await apiClient.deleteScanPreview(scanId);
      setDeleteConfirm({ scanId, analysisCount: preview.analysis_count, loading: false });
    } catch {
      setDeleteConfirm({ scanId, analysisCount: 0, loading: false });
    }
  };

  const scans: ScanStatus[] = data?.scans ?? [];

  const totalScans = scans.length;
  const completedScans = scans.filter((s) => s.status === "completed").length;
  const runningScans = scans.filter((s) => s.status === "running").length;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}
        </div>
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Scan History</h1>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <p className="text-destructive text-sm">Failed to load scan history.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Scan History</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Browse and manage your market scan results
          </p>
        </div>
        <Link
          to="/scanner"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          New Scan
        </Link>
      </div>

      {/* Stats row */}
      {totalScans > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-2xl border border-border/50 bg-card/50 backdrop-blur p-5">
            <div className="text-3xl font-bold tabular-nums">{totalScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Total Scans</div>
          </div>
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5">
            <div className="text-3xl font-bold tabular-nums text-emerald-500">{completedScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Completed</div>
          </div>
          <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.04] p-5">
            <div className="text-3xl font-bold tabular-nums text-blue-500">{runningScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Running</div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {scans.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/60 p-16 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-muted/50 flex items-center justify-center mb-5">
            <svg className="w-8 h-8 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1.5">No scans yet</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-xs mx-auto">
            Start your first market scan to analyze all available Bybit USDT perpetual futures.
          </p>
          <Link
            to="/scanner"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 transition-all shadow-lg shadow-primary/25"
          >
            Start Scan
          </Link>
        </div>
      ) : (
        /* Scan list */
        <div className="space-y-2">
          {scans.map((scan) => {
            const results = scan.results || [];
            const buy = results.filter((r) => r.direction === "buy").length;
            const sell = results.filter((r) => r.direction === "sell").length;
            const total = results.length;
            const dur = formatDuration(scan.started_at, scan.completed_at);

            return (
              <Link
                key={scan.scan_id}
                to={`/scanner/${scan.scan_id}`}
                className="group block rounded-xl border border-border/40 bg-card hover:bg-card/80 hover:border-border/70 transition-all duration-200 hover:shadow-lg hover:shadow-black/5"
              >
                <div className="flex items-center gap-5 px-5 py-4">
                  {/* Status + date */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5 mb-1.5">
                      <StatusDot status={scan.status} />
                      <span className="text-sm font-semibold capitalize">{scan.status}</span>
                      <span className="text-[11px] text-muted-foreground/70">
                        {formatDate(scan.started_at)}
                      </span>
                      {dur && (
                        <span className="text-[11px] text-muted-foreground/50 font-mono">
                          {dur}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground/70">
                        {scan.completed + scan.failed}
                        <span className="text-muted-foreground/50">/{scan.total}</span>
                      </span>
                      <span className="text-muted-foreground/30">symbols</span>
                      {total > 0 && (
                        <>
                          <span className="text-muted-foreground/20 mx-1">&middot;</span>
                          <span className="text-muted-foreground/40">{total} results</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Signal breakdown mini-bars */}
                  {total > 0 && (
                    <div className="hidden sm:flex items-center gap-5">
                      <div className="text-right space-y-1">
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-500/80 w-8">Buy</span>
                          <MiniBar value={buy} max={total} color="bg-emerald-500" />
                        </div>
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-[11px] uppercase tracking-wider font-semibold text-red-500/80 w-8">Sell</span>
                          <MiniBar value={sell} max={total} color="bg-red-500" />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    {scan.status !== "running" && (
                      <button
                        onClick={(e) => handleDeleteClick(e, scan.scan_id)}
                        className="p-2 rounded-lg text-muted-foreground/40 hover:text-red-500 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                        title="Delete scan"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    )}
                    <div className="p-2 rounded-lg text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-colors">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-md"
            onClick={() => !deleteMutation.isPending && setDeleteConfirm(null)}
          />
          <div className="relative bg-card border border-border/50 rounded-2xl shadow-2xl p-7 max-w-sm w-full mx-4 space-y-5">
            <div className="w-12 h-12 rounded-2xl bg-red-500/10 flex items-center justify-center">
              <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </div>

            <div>
              <h3 className="text-lg font-bold mb-1">Delete scan?</h3>
              {deleteConfirm.loading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground mt-3">
                  <div className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                  Checking associated data...
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    This will permanently delete this scan and all its results.
                  </p>
                  {(deleteConfirm.analysisCount ?? 0) > 0 && (
                    <div className="p-3.5 rounded-xl bg-red-500/[0.06] border border-red-500/15">
                      <p className="text-sm font-medium text-red-500">
                        {deleteConfirm.analysisCount} analysis record{deleteConfirm.analysisCount !== 1 ? "s" : ""} will also be deleted
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Including all reports and agent outputs
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center gap-2.5 pt-1">
              <button
                onClick={() => setDeleteConfirm(null)}
                disabled={deleteMutation.isPending}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirm.scanId)}
                disabled={deleteConfirm.loading || deleteMutation.isPending}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {deleteMutation.isPending && (
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
