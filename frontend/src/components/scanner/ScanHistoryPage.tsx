import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDurationBetween } from "@/lib/format";
import { Link } from "@tanstack/react-router";
import { apiClient, type ScanStatus } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

function getScannerWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/v1/scanner`;
}

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


interface DeleteConfirmState {
  scanId: string;
  analysisCount: number | null;
  loading: boolean;
}

export function ScanHistoryPage() {
  const queryClient = useQueryClient();
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["scans"],
    queryFn: ({ signal }) => apiClient.listScans(signal),
    refetchInterval: (query) => {
      const scans = query.state.data?.scans;
      const hasRunning = scans?.some((s) => s.status === "running");
      return hasRunning ? 2_000 : 30_000;
    },
  });

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let debounceTimer: ReturnType<typeof setTimeout>;
    let disposed = false;
    // AI-CONTEXT: BFCache eligibility. An open WebSocket makes the page
    // ineligible for Chrome's back/forward cache, so a backgrounded tab (e.g.
    // the user switching to another app on mobile) gets discarded and FULLY
    // RELOADED on return instead of restored instantly. We close the socket on
    // `pagehide` and reconnect on `pageshow`/visibility. `suppressReconnect`
    // tells the onclose handler to stand down for the intentional pagehide
    // close, so it doesn't immediately re-open (which would defeat BFCache and
    // race the pageshow reconnect into a duplicate connection).
    let suppressReconnect = false;
    let ws: WebSocket;

    function connect() {
      if (disposed) return;
      const existing = wsRef.current;
      if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;
      ws = new WebSocket(getScannerWsUrl());
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "scan_list_changed") {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
              queryClient.invalidateQueries({ queryKey: ["scans"] });
            }, 500);
          } else if (msg.type === "heartbeat") {
            ws.send(JSON.stringify({ type: "pong" }));
          }
        } catch { /* ignore malformed */ }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (disposed || suppressReconnect) return;
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 3_000);
      };

      ws.onerror = () => ws.close();
    }

    function handlePageHide() {
      suppressReconnect = true;
      clearTimeout(reconnectTimer);
      const current = wsRef.current;
      wsRef.current = null;
      current?.close();
    }

    function handlePageShow() {
      if (disposed) return;
      suppressReconnect = false;
      const current = wsRef.current;
      if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) return;
      clearTimeout(reconnectTimer);
      connect();
    }

    function handleVisibility() {
      if (document.visibilityState !== "visible") return;
      handlePageShow();
    }

    connect();
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      disposed = true;
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibility);
      clearTimeout(reconnectTimer);
      clearTimeout(debounceTimer);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [queryClient]);

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
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight">Scan History</h1>
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-5 text-center">
          <p className="text-destructive text-sm">Failed to load scan history.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Scanner"
        title="Scan History"
        description=""
        actions={          <Link
            to="/scanner"
            className="touch-target inline-flex items-center justify-center gap-2 rounded-[var(--neu-radius-sm)] border-none gradient-primary px-4 py-2.5 text-xs font-bold uppercase tracking-[0.16em] text-[var(--neu-accent-ink)] shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] transition-all hover:shadow-[var(--neu-shadow-raised-hover)] duration-150 active:scale-95 cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New scan
          </Link>
        }
        stats={[
          { label: "Total scans", value: String(totalScans), tone: "accent" },
          { label: "Completed", value: String(completedScans), tone: completedScans ? "success" : "neutral" },
          { label: "Running", value: String(runningScans), tone: runningScans ? "accent" : "neutral" },
          { label: "Buy signals", value: String(totalBuy), tone: totalBuy ? "success" : "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{totalSell} sell signals</Badge>
        </div>
      </PageHeader>
 
      {/* Empty state */}
      {scans.length === 0 ? (
        <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-8 text-center">
          <div className="w-12 h-12 mx-auto rounded-[calc(var(--radius)*1.05)] border border-[color:var(--neu-stroke-soft)] bg-[var(--neu-surface-base)] text-[var(--neu-text-muted)] shadow-[var(--neu-shadow-raised)] flex items-center justify-center mb-4">
            <svg className="w-6 h-6 text-[var(--neu-text-muted)]/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1.5 text-[var(--neu-text-strong)]">No scans yet</h3>
          <p className="text-sm text-[var(--neu-text-muted)] mb-6 max-w-xs mx-auto">
            Start your first market scan to analyze all available Bybit USDT perpetual futures.
          </p>
          <Link
            to="/scanner"
            className="inline-flex items-center justify-center gap-2 rounded-[var(--neu-radius-sm)] border-none gradient-primary px-4 py-2.5 text-xs font-bold uppercase tracking-[0.16em] text-[var(--neu-accent-ink)] shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] transition-all hover:shadow-[var(--neu-shadow-raised-hover)] duration-150 active:scale-95 cursor-pointer"
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
            const dur = formatDurationBetween(scan.started_at, scan.completed_at, "");
            const progress = scan.total > 0 ? Math.round(((scan.completed + scan.failed) / scan.total) * 100) : 0;

            return (
              <Link
                key={scan.scan_id}
                to={`/scanner/${scan.scan_id}`}
                className="group rounded-[var(--neu-radius-lg)] border-none bg-[var(--neu-surface-base)] neu-surface-raised neu-card-hover block overflow-hidden relative active:scale-[0.99]"
              >
                {/* Header */}
                <div className="relative flex items-center justify-between px-4 pt-4 pb-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 border ${
                      scan.status === "completed" ? "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]" :
                      scan.status === "running" ? "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]" :
                      scan.status === "failed" ? "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]" :
                      "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-pill)]"
                    }`}>
                      {scan.status === "completed" ? (
                        <svg className="w-4 h-4 text-[var(--neu-success)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      ) : scan.status === "running" ? (
                        <svg className="w-4 h-4 text-[var(--neu-accent)] animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      ) : scan.status === "failed" ? (
                        <svg className="w-4 h-4 text-[var(--neu-danger)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      ) : (
                        <svg className="w-4 h-4 text-[var(--neu-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                        </svg>
                      )}
                    </div>
                    <div className="flex flex-col">
                      <span className={`text-xs font-bold uppercase tracking-wider ${
                        scan.status === "completed" ? "text-[var(--neu-success)]" :
                        scan.status === "running" ? "text-[var(--neu-accent)]" :
                        scan.status === "failed" ? "text-[var(--neu-danger)]" :
                        "text-[var(--neu-text-muted)]"
                      }`}>{scan.status}</span>
                      {dur && (
                        <span className="text-[10px] text-[var(--neu-text-muted)]/40 font-mono leading-tight">{dur}</span>
                      )}
                    </div>
                  </div>
                  {scan.status !== "running" && (
                    <button
                      onClick={(e) => handleDeleteClick(e, scan.scan_id)}
                      className="p-1.5 rounded-lg text-[var(--neu-text-muted)]/20 hover:text-[var(--neu-danger)] hover:bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] transition-all opacity-0 group-hover:opacity-100 cursor-pointer"
                      title="Delete scan"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>

                {/* Results highlight */}
                <div className="relative px-4 pb-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-extrabold tabular-nums tracking-tight text-[var(--neu-text-strong)]">{total}</span>
                    <span className="text-sm text-[var(--neu-text-muted)]/40 font-medium">results</span>
                    {scan.interval && (
                      <span className="ml-auto px-2.5 py-0.5 rounded-full border border-transparent shadow-[var(--neu-shadow-pill)] bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] text-[9px] font-bold uppercase tracking-wider">
                        {scan.interval}
                      </span>
                    )}
                  </div>
                </div>

                {/* Scan progress bar */}
                <div className="relative px-4 pb-3.5 pt-1.5">
                  <div className="flex items-center gap-2.5">
                    <div className="flex-1 h-2 rounded-[var(--neu-radius-pill)] bg-[var(--neu-surface-deep)] overflow-hidden p-0.5 shadow-[var(--neu-shadow-inset)]">
                      {(() => {
                        const pct = scan.total > 0 ? ((scan.completed + scan.failed) / scan.total) * 100 : 0;
                        const buyPct = total > 0 ? (buy / total) * 100 : 0;
                        const sellPct = total > 0 ? (sell / total) * 100 : 0;
                        return (
                          <div className="h-full flex rounded-[var(--neu-radius-pill)] overflow-hidden" style={{ width: `${pct}%` }}>
                            {buyPct > 0 && <div className="h-full bg-[var(--neu-success)] transition-all duration-700" style={{ width: `${buyPct}%` }} />}
                            {sellPct > 0 && <div className="h-full bg-[var(--neu-danger)] transition-all duration-700" style={{ width: `${sellPct}%` }} />}
                            <div className="h-full flex-1 bg-[var(--neu-text-muted)]/20 transition-all duration-700" />
                          </div>
                        );
                      })()}
                    </div>
                    <span className="text-[10px] text-[var(--neu-text-muted)]/40 tabular-nums font-semibold shrink-0">
                      {scan.completed + scan.failed}/{scan.total}
                    </span>
                  </div>
                </div>

                {/* Running scan extra progress */}
                {scan.status === "running" && (
                  <div className="mx-4 mb-3 rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-3 border-none">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] text-[var(--neu-accent)] font-semibold uppercase tracking-wider">Scanning...</span>
                      <span className="text-[10px] text-[var(--neu-accent)]/80 font-mono tabular-nums">{progress}%</span>
                    </div>
                    <div className="w-full h-2 rounded-[var(--neu-radius-pill)] bg-[var(--neu-surface-deep)] overflow-hidden p-0.5">
                      <div className="h-full rounded-[var(--neu-radius-pill)] gradient-primary transition-all duration-500" style={{ width: `${progress}%` }}>
                        <div className="w-full h-full animate-pulse bg-white/20" />
                      </div>
                    </div>
                  </div>
                )}

                {/* Signal metrics */}
                <div className="relative grid grid-cols-3 gap-2 px-4 pb-3.5">
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className={`text-base font-extrabold tabular-nums ${buy > 0 ? "text-[var(--neu-success)]" : "text-[var(--neu-text-muted)]/30"}`}>{buy}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Buy</div>
                  </div>
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className={`text-base font-extrabold tabular-nums ${sell > 0 ? "text-[var(--neu-danger)]" : "text-[var(--neu-text-muted)]/30"}`}>{sell}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Sell</div>
                  </div>
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className="text-base font-extrabold tabular-nums text-[var(--neu-text-muted)]/60">{total - buy - sell}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Hold</div>
                  </div>
                </div>

                {/* Footer */}
                <div className="relative flex items-center justify-between px-4 py-2.5 border-t border-[color:var(--neu-stroke-soft)]">
                  <span className="text-[11px] text-[var(--neu-text-muted)]/50 font-medium">
                    {formatDate(scan.started_at)}
                  </span>
                  <div className="flex items-center gap-1 text-[var(--neu-text-muted)]/30 group-hover:text-[var(--neu-accent)]/80 transition-colors">
                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] opacity-0 group-hover:opacity-100 transition-opacity">View details</span>
                    <svg className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
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
          <div className="relative bg-[var(--neu-surface-base)] border border-[color:var(--neu-stroke-soft)] rounded-[var(--neu-radius-lg)] shadow-[var(--neu-shadow-float)] p-6 max-w-sm w-full mx-4 space-y-5">
            <div className="w-10 h-10 rounded-[calc(var(--radius)*1.2)] bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
              <svg className="w-5 h-5 text-[var(--neu-danger)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </div>

            <div>
              <h3 className="text-lg font-bold mb-1 text-[var(--neu-text-strong)]">Delete scan?</h3>
              {deleteConfirm.loading ? (
                <div className="flex items-center gap-2 text-sm text-[var(--neu-text-muted)] mt-3">
                  <div className="w-4 h-4 border-2 border-[var(--neu-text-muted)] border-t-transparent rounded-full animate-spin" />
                  Checking associated data...
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-[var(--neu-text-muted)] leading-relaxed">
                    This will permanently delete this scan and all its results.
                  </p>
                  {(deleteConfirm.analysisCount ?? 0) > 0 && (
                    <div className="p-3.5 rounded-xl bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
                      <p className="text-sm font-medium text-[var(--neu-danger)]">
                        {deleteConfirm.analysisCount} analysis record{deleteConfirm.analysisCount !== 1 ? "s" : ""} will also be deleted
                      </p>
                      <p className="text-xs text-[var(--neu-text-muted)] mt-1">
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
                className="flex-1 px-4 py-2.5 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-surface-raised)] text-[var(--neu-text-strong)] hover:translate-y-[-1px] shadow-[var(--neu-shadow-pill)] transition-all border-none cursor-pointer active:scale-95 flex items-center justify-center"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirm.scanId)}
                disabled={deleteConfirm.loading || deleteMutation.isPending}
                className="flex-1 px-4 py-2.5 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-danger)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-colors disabled:opacity-50 flex items-center justify-center gap-2 border-none cursor-pointer active:scale-95"
              >
                {deleteMutation.isPending && (
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
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
