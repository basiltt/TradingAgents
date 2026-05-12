import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, type ScanResultItem } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useScanFilters, ScanResultFiltersBar } from "@/components/scanner/ScanResultFilters";
import { PlaceTradeDialog } from "@/components/scanner/PlaceTradeDialog";

const DIRECTION_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  buy: { label: "BUY", color: "text-emerald-400", bg: "bg-emerald-500/10" },
  sell: { label: "SELL", color: "text-red-400", bg: "bg-red-500/10" },
  hold: { label: "HOLD", color: "text-amber-400", bg: "bg-amber-500/10" },
  unknown: { label: "—", color: "text-muted-foreground", bg: "bg-muted" },
};

function ScoreBar({ score }: { score: number }) {
  const abs = Math.min(Math.abs(score), 10);
  const pct = (abs / 10) * 100;
  const color = score > 0 ? "bg-emerald-500" : score < 0 ? "bg-red-500" : "bg-muted-foreground";
  return (
    <div className="flex items-center gap-2 w-24">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-6 text-right">{score > 0 ? "+" : ""}{score}</span>
    </div>
  );
}

function copyToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text).catch(() => {});
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function formatDuration(startedAt: string, completedAt: string | null): string {
  if (!startedAt) return "—";
  const diff = Math.max(0, (completedAt ? new Date(completedAt).getTime() : Date.now()) - new Date(startedAt).getTime());
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function CollapsibleSection({
  title,
  count,
  dotColor,
  defaultOpen = false,
  children,
}: {
  title: string;
  count: number;
  dotColor: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-5 py-4 text-left hover:bg-muted/30 transition-colors"
      >
        <svg
          className={cn("w-4 h-4 text-muted-foreground transition-transform", open && "rotate-90")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span className={cn("w-2.5 h-2.5 rounded-full", dotColor)} />
        <span className="font-semibold text-sm">{title} ({count})</span>
      </button>
      {open && <CardContent className="pt-0 pb-4">{children}</CardContent>}
    </Card>
  );
}

function ResultsTable({ results, isCrypto, onTrade }: { results: ScanResultItem[]; isCrypto?: boolean; onTrade?: (symbol: string, direction: "buy" | "sell") => void }) {
  const [copiedTicker, setCopiedTicker] = useState<string | null>(null);

  function handleCopy(ticker: string) {
    copyToClipboard(ticker).then(() => {
      setCopiedTicker(ticker);
      setTimeout(() => setCopiedTicker(null), 1500);
    });
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 text-xs text-muted-foreground">
            <th className="text-left px-4 py-2.5 font-medium">#</th>
            <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Signal</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Confidence</th>
            <th className="text-left px-4 py-2.5 font-medium">Strength</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Status</th>
            <th className="text-right px-4 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            const copied = copiedTicker === r.ticker;
            return (
              <tr key={r.ticker} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => handleCopy(r.ticker)}
                    title="Tap to copy"
                    className={cn(
                      "font-mono font-semibold transition-all duration-150 rounded px-1 -mx-1 active:scale-95",
                      copied ? "text-emerald-400 bg-emerald-500/10" : "hover:text-primary hover:bg-primary/10",
                    )}
                  >
                    {copied ? (
                      <span className="flex items-center gap-1">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {r.ticker}
                      </span>
                    ) : r.ticker}
                  </button>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <span className={cn("px-2 py-0.5 rounded text-xs font-bold", dir.bg, dir.color)}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs capitalize hidden md:table-cell">{r.confidence}</td>
                <td className="px-4 py-3"><ScoreBar score={r.score} /></td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <Badge variant={r.status === "completed" ? "secondary" : "destructive"} className="text-xs">
                    {r.status}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    {isCrypto && onTrade && (r.direction === "buy" || r.direction === "sell") && (
                      <button
                        onClick={() => onTrade(r.ticker, r.direction as "buy" | "sell")}
                        className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20 font-medium transition-colors"
                      >
                        Trade
                      </button>
                    )}
                    {r.run_id && (
                      <Link
                        to="/analysis/$runId"
                        params={{ runId: r.run_id }}
                        className="text-xs text-primary hover:underline"
                      >
                        View
                      </Link>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface DeleteConfirmState {
  analysisCount: number | null;
  loading: boolean;
}

export function ScanDetailPage({ scanId }: { scanId: string }) {
  const queryClient = useQueryClient();
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(null);
  const [tradeTarget, setTradeTarget] = useState<{ symbol: string; direction: "buy" | "sell" } | null>(null);

  const { data: scan, isLoading, error } = useQuery({
    queryKey: ["scan", scanId],
    queryFn: ({ signal }) => apiClient.getScan(scanId, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 3000 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelScan(scanId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scan", scanId] });
      queryClient.invalidateQueries({ queryKey: ["scans"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteScan(scanId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scans"] });
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      window.history.back();
    },
  });

  const handleDeleteClick = async () => {
    setDeleteConfirm({ analysisCount: null, loading: true });
    try {
      const preview = await apiClient.deleteScanPreview(scanId);
      setDeleteConfirm({ analysisCount: preview.analysis_count, loading: false });
    } catch {
      setDeleteConfirm({ analysisCount: 0, loading: false });
    }
  };

  const results = scan?.results || [];
  const { filters: scanFilters, update: updateFilter, hasActive: hasActiveFilters, filtered: filteredResults, clearAll: clearFilters } = useScanFilters(results, "detail");

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !scan) {
    return (
      <div className="space-y-6">
        <Link to="/scanner/history" className="text-sm text-primary hover:underline flex items-center gap-1">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to history
        </Link>
        <Card>
          <CardContent className="py-8 text-center text-destructive">
            Scan not found or failed to load.
          </CardContent>
        </Card>
      </div>
    );
  }

  const buyResults = filteredResults.filter((r) => r.direction === "buy");
  const sellResults = filteredResults.filter((r) => r.direction === "sell");
  const holdResults = filteredResults.filter((r) => r.direction === "hold" || r.direction === "unknown" || !r.direction);
  const progress = scan.total > 0 ? Math.round(((scan.completed + scan.failed) / scan.total) * 100) : 0;
  const isCrypto = scan.asset_type === "crypto" || results.some((r) => /USDT$/.test(r.ticker));
  const handleTrade = isCrypto ? (symbol: string, direction: "buy" | "sell") => setTradeTarget({ symbol, direction }) : undefined;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link to="/scanner/history" className="text-sm text-primary hover:underline flex items-center gap-1 mb-3">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Back to history
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <svg className="w-6 h-6 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Scan Details
          </h1>
        </div>
        {scan.status === "running" ? (
          <button
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-destructive/10 text-destructive hover:bg-destructive/20 border border-destructive/30 transition-colors disabled:opacity-50"
          >
            {cancelMutation.isPending ? (
              <div className="w-4 h-4 border-2 border-destructive border-t-transparent rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            )}
            {cancelMutation.isPending ? "Cancelling..." : "Cancel Scan"}
          </button>
        ) : (
          <button
            onClick={handleDeleteClick}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete Scan
          </button>
        )}
      </div>

      {/* Status card */}
      <Card>
        <CardContent className="py-5">
          <div className="flex items-center gap-3 mb-3">
            {scan.status === "completed" ? (
              <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            ) : scan.status === "running" ? (
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            ) : (
              <svg className="w-5 h-5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            <span className="font-semibold capitalize">{scan.status === "completed" ? "Scan Complete" : scan.status}</span>
            {scan.completed_at && (
              <span className="text-sm text-muted-foreground">
                {formatDuration(scan.started_at, scan.completed_at)}
              </span>
            )}
          </div>

          <div className="text-xs text-muted-foreground mb-3">
            {scan.completed + scan.failed} / {scan.total} symbols &bull; {formatDate(scan.started_at)}
          </div>

          {scan.status === "running" && (
            <div className="mb-4">
              <div className="flex justify-between text-xs text-muted-foreground mb-1">
                <span>{scan.completed + scan.failed} / {scan.total}</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {/* Summary boxes */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 text-center">
              <div className="text-2xl font-bold text-emerald-500">{buyResults.length}</div>
              <div className="text-xs text-muted-foreground mt-1">Buy Signals</div>
            </div>
            <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-center">
              <div className="text-2xl font-bold text-red-500">{sellResults.length}</div>
              <div className="text-xs text-muted-foreground mt-1">Sell Signals</div>
            </div>
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-center">
              <div className="text-2xl font-bold text-amber-500">{holdResults.length}</div>
              <div className="text-xs text-muted-foreground mt-1">Hold / Neutral</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Filters */}
      {results.length > 0 && (
        <ScanResultFiltersBar
          filters={scanFilters}
          update={updateFilter}
          hasActive={hasActiveFilters}
          totalCount={results.length}
          filteredCount={filteredResults.length}
          clearAll={clearFilters}
        />
      )}

      {/* Results by direction */}
      {buyResults.length > 0 && (
        <CollapsibleSection title="Buy Signals" count={buyResults.length} dotColor="bg-emerald-500" defaultOpen>
          <ResultsTable results={buyResults} isCrypto={isCrypto} onTrade={handleTrade} />
        </CollapsibleSection>
      )}
      {sellResults.length > 0 && (
        <CollapsibleSection title="Sell Signals" count={sellResults.length} dotColor="bg-red-500">
          <ResultsTable results={sellResults} isCrypto={isCrypto} onTrade={handleTrade} />
        </CollapsibleSection>
      )}
      {holdResults.length > 0 && (
        <CollapsibleSection title="Hold / Neutral" count={holdResults.length} dotColor="bg-amber-500">
          <ResultsTable results={holdResults} isCrypto={isCrypto} onTrade={handleTrade} />
        </CollapsibleSection>
      )}

      {/* Place Trade Dialog */}
      {tradeTarget && (
        <PlaceTradeDialog
          open={!!tradeTarget}
          onOpenChange={(open) => { if (!open) setTradeTarget(null); }}
          symbol={tradeTarget.symbol}
          signalDirection={tradeTarget.direction}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => !deleteMutation.isPending && setDeleteConfirm(null)}
          />
          <div className="relative bg-card border rounded-xl shadow-2xl p-6 max-w-md w-full mx-4 space-y-4">
            <h3 className="text-lg font-bold text-destructive flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              Delete Scan
            </h3>

            {deleteConfirm.loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="w-4 h-4 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin" />
                Checking associated data...
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm">This will permanently delete this scan and all its results.</p>
                {(deleteConfirm.analysisCount ?? 0) > 0 && (
                  <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20">
                    <p className="text-sm font-medium text-destructive">
                      {deleteConfirm.analysisCount} analysis record{deleteConfirm.analysisCount !== 1 ? "s" : ""} will also be deleted.
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      This includes all associated reports and agent outputs.
                    </p>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">This action cannot be undone.</p>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate()}
                disabled={deleteConfirm.loading || deleteMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {deleteMutation.isPending && (
                  <div className="w-3.5 h-3.5 border-2 border-destructive-foreground border-t-transparent rounded-full animate-spin" />
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
