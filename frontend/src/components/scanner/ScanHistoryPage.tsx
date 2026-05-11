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
    refetchInterval: (query) => {
      const scans = query.state.data?.scans;
      const hasRunning = scans?.some((s) => s.status === "running");
      return hasRunning ? 3000 : 15000;
    },
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
  const totalBuy = scans.reduce((sum, s) => sum + (s.direction_counts?.buy ?? 0), 0);
  const totalSell = scans.reduce((sum, s) => sum + (s.direction_counts?.sell ?? 0), 0);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-56" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-52 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold tracking-tight">Scan History</h1>
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
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <div className="text-2xl font-bold tabular-nums">{totalScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Total Scans</div>
          </div>
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-emerald-500">{completedScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Completed</div>
          </div>
          <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-blue-500">{runningScans}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Running</div>
          </div>
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-emerald-500">{totalBuy}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Buy Signals</div>
          </div>
          <div className="rounded-2xl border border-red-500/20 bg-red-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-red-500">{totalSell}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Sell Signals</div>
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
        /* Scan cards grid */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {scans.map((scan) => {
            const dc = scan.direction_counts ?? {};
            const buy = dc.buy ?? 0;
            const sell = dc.sell ?? 0;
            const total = Object.values(dc).reduce((a, b) => a + b, 0);
            const dur = formatDuration(scan.started_at, scan.completed_at);
            const progress = scan.total > 0 ? Math.round(((scan.completed + scan.failed) / scan.total) * 100) : 0;

            return (
              <Link
                key={scan.scan_id}
                to={`/scanner/${scan.scan_id}`}
                className="group rounded-2xl border border-border/40 bg-card hover:border-border/60 transition-all duration-300 hover:shadow-xl hover:shadow-primary/5 block overflow-hidden relative"
              >
                {/* Subtle gradient overlay on hover */}
                <div className="absolute inset-0 bg-gradient-to-br from-primary/[0.02] via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />

                {/* Header */}
                <div className="relative flex items-center justify-between px-5 pt-5 pb-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ring-1 ring-inset ${
                      scan.status === "completed" ? "bg-emerald-500/10 ring-emerald-500/20" :
                      scan.status === "running" ? "bg-blue-500/10 ring-blue-500/20" :
                      scan.status === "failed" ? "bg-red-500/10 ring-red-500/20" :
                      "bg-muted/50 ring-border/30"
                    }`}>
                      {scan.status === "completed" ? (
                        <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      ) : scan.status === "running" ? (
                        <svg className="w-4 h-4 text-blue-500 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      ) : scan.status === "failed" ? (
                        <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      ) : (
                        <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                        </svg>
                      )}
                    </div>
                    <div className="flex flex-col">
                      <span className={`text-xs font-bold uppercase tracking-wider ${
                        scan.status === "completed" ? "text-emerald-500" :
                        scan.status === "running" ? "text-blue-500" :
                        scan.status === "failed" ? "text-red-500" :
                        "text-muted-foreground"
                      }`}>{scan.status}</span>
                      {dur && (
                        <span className="text-[10px] text-muted-foreground/40 font-mono leading-tight">{dur}</span>
                      )}
                    </div>
                  </div>
                  {scan.status !== "running" && (
                    <button
                      onClick={(e) => handleDeleteClick(e, scan.scan_id)}
                      className="p-1.5 rounded-lg text-muted-foreground/20 hover:text-red-500 hover:bg-red-500/10 transition-all opacity-0 group-hover:opacity-100"
                      title="Delete scan"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>

                {/* Results highlight */}
                <div className="relative px-5 pb-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-3xl font-extrabold tabular-nums tracking-tight">{total}</span>
                    <span className="text-sm text-muted-foreground/40 font-medium">results</span>
                    {scan.interval && (
                      <span className="ml-auto px-2 py-0.5 rounded-md bg-primary/10 border border-primary/20 text-[10px] font-bold text-primary uppercase tracking-wider">
                        {scan.interval}
                      </span>
                    )}
                  </div>
                </div>

                {/* Scan progress bar */}
                <div className="relative px-5 pb-4 pt-1.5">
                  <div className="flex items-center gap-2.5">
                    <div className="flex-1 h-1.5 rounded-full bg-muted/20 overflow-hidden">
                      {(() => {
                        const pct = scan.total > 0 ? ((scan.completed + scan.failed) / scan.total) * 100 : 0;
                        const buyPct = total > 0 ? (buy / total) * 100 : 0;
                        const sellPct = total > 0 ? (sell / total) * 100 : 0;
                        return (
                          <div className="h-full flex" style={{ width: `${pct}%` }}>
                            {buyPct > 0 && <div className="h-full bg-emerald-500 transition-all duration-700" style={{ width: `${buyPct}%` }} />}
                            {sellPct > 0 && <div className="h-full bg-red-500 transition-all duration-700" style={{ width: `${sellPct}%` }} />}
                            <div className="h-full flex-1 bg-muted-foreground/20 transition-all duration-700" />
                          </div>
                        );
                      })()}
                    </div>
                    <span className="text-[10px] text-muted-foreground/40 tabular-nums font-medium shrink-0">
                      {scan.completed + scan.failed}/{scan.total}
                    </span>
                  </div>
                </div>

                {/* Running scan extra progress */}
                {scan.status === "running" && (
                  <div className="mx-5 mb-3 rounded-lg bg-blue-500/[0.06] border border-blue-500/10 px-3 py-2">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] text-blue-400 font-semibold uppercase tracking-wider">Scanning...</span>
                      <span className="text-[10px] text-blue-400/70 font-mono tabular-nums">{progress}%</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-blue-500/10 overflow-hidden">
                      <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-500" style={{ width: `${progress}%` }}>
                        <div className="w-full h-full animate-pulse bg-white/20" />
                      </div>
                    </div>
                  </div>
                )}

                {/* Signal metrics */}
                <div className="relative grid grid-cols-3 gap-2.5 px-5 pb-4">
                  <div className="rounded-xl bg-emerald-500/[0.05] border border-emerald-500/10 px-3 py-2.5 text-center">
                    <div className={`text-base font-bold tabular-nums ${buy > 0 ? "text-emerald-500" : "text-muted-foreground/30"}`}>{buy}</div>
                    <div className="text-[9px] text-muted-foreground/50 uppercase tracking-wider font-semibold mt-0.5">Buy</div>
                  </div>
                  <div className="rounded-xl bg-red-500/[0.05] border border-red-500/10 px-3 py-2.5 text-center">
                    <div className={`text-base font-bold tabular-nums ${sell > 0 ? "text-red-500" : "text-muted-foreground/30"}`}>{sell}</div>
                    <div className="text-[9px] text-muted-foreground/50 uppercase tracking-wider font-semibold mt-0.5">Sell</div>
                  </div>
                  <div className="rounded-xl bg-muted/[0.3] border border-border/20 px-3 py-2.5 text-center">
                    <div className="text-base font-bold tabular-nums text-muted-foreground/60">{total - buy - sell}</div>
                    <div className="text-[9px] text-muted-foreground/50 uppercase tracking-wider font-semibold mt-0.5">Hold</div>
                  </div>
                </div>

                {/* Footer */}
                <div className="relative flex items-center justify-between px-5 py-2.5 border-t border-border/20">
                  <span className="text-[11px] text-muted-foreground/40 font-medium">
                    {formatDate(scan.started_at)}
                  </span>
                  <div className="flex items-center gap-1 text-muted-foreground/25 group-hover:text-primary/50 transition-colors">
                    <span className="text-[10px] font-medium opacity-0 group-hover:opacity-100 transition-opacity">View details</span>
                    <svg className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
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
