import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { formatDurationBetween } from "@/lib/format";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, type ScanResultItem } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useScanFilters, ScanResultFiltersBar } from "@/components/scanner/ScanResultFilters";
import { PlaceTradeDialog } from "@/components/scanner/PlaceTradeDialog";
import { TradingCycleDialog } from "@/components/cycles/TradingCycleDialog";
import { DIRECTION_CONFIG } from "@/components/scanner/constants";

function ScoreBar({ score }: { score: number }) {
  const abs = Math.min(Math.abs(score), 10);
  const pct = (abs / 10) * 100;
  const color = score > 0 ? "bg-emerald-500" : score < 0 ? "bg-red-500" : "bg-muted-foreground/60";
  return (
    <div className="flex items-center gap-2.5 w-24">
      <div className="flex-1 h-2.5 rounded-full bg-muted/30 overflow-hidden border border-border/20 p-[1px]">
        <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono font-bold tracking-tight w-6 text-right tabular-nums">{score > 0 ? "+" : ""}{score}</span>
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
    <div className="glass-card border border-border/50 bg-card/65 backdrop-blur-sm rounded-2xl shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2.5 w-full text-left px-6 py-4.5 hover:bg-muted/15 transition-colors cursor-pointer select-none font-bold text-xs uppercase tracking-wider text-foreground"
      >
        <svg
          className={cn("w-4 h-4 transition-transform duration-200 text-muted-foreground shrink-0", open && "rotate-90")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", dotColor)} />
        <span>{title} ({count})</span>
      </button>
      {open && (
        <div className="border-t border-border/20">
          {children}
        </div>
      )}
    </div>
  );
}

function ResultsTable({ results, isCrypto, onTrade, tradedSymbols }: { results: ScanResultItem[]; isCrypto?: boolean; onTrade?: (symbol: string, direction: "buy" | "sell") => void; tradedSymbols?: Set<string> }) {
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
          <tr className="border-b border-border/20 text-[10px] font-black uppercase tracking-wider text-muted-foreground/80 bg-muted/5">
            <th className="text-left px-5 py-3.5 font-black">#</th>
            <th className="text-left px-5 py-3.5 font-black">Symbol</th>
            <th className="text-left px-5 py-3.5 font-black hidden md:table-cell">Signal</th>
            <th className="text-left px-5 py-3.5 font-black hidden md:table-cell">Confidence</th>
            <th className="text-left px-5 py-3.5 font-black">Strength</th>
            <th className="text-left px-5 py-3.5 font-black hidden md:table-cell">Status</th>
            <th className="text-right px-5 py-3.5 font-black"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/10">
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            const copied = copiedTicker === r.ticker;
            return (
              <tr key={r.ticker} className="hover:bg-muted/15 transition-colors group">
                <td className="px-5 py-3.5 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="px-5 py-3.5">
                  <button
                    type="button"
                    onClick={() => handleCopy(r.ticker)}
                    title="Tap to copy"
                    className={cn(
                      "font-mono font-bold transition-all duration-150 rounded-lg px-2 py-1 -mx-2 active:scale-95 cursor-pointer border border-transparent text-sm",
                      copied
                        ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/25"
                        : "text-foreground group-hover:text-primary hover:bg-primary/10 hover:border-primary/20",
                    )}
                  >
                    {copied ? (
                      <span className="flex items-center gap-1.5">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {r.ticker}
                      </span>
                    ) : r.ticker}
                  </button>
                </td>
                <td className="px-5 py-3.5 hidden md:table-cell">
                  <span className={cn("px-2 py-0.5 rounded-lg text-[10px] font-black uppercase tracking-wider border", dir.bg, dir.color, dir.label === "Buy" ? "border-emerald-500/20" : dir.label === "Sell" ? "border-red-500/20" : "border-border/40")}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-5 py-3.5 text-xs font-semibold capitalize hidden md:table-cell text-muted-foreground">{r.confidence}</td>
                <td className="px-5 py-3.5"><ScoreBar score={r.score} /></td>
                <td className="px-5 py-3.5 hidden md:table-cell">
                  {r.status !== "completed" && r.decision_summary ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <Badge variant={r.status === "completed" ? "secondary" : "destructive"} className="text-[10px] font-bold uppercase tracking-wider cursor-help rounded-xl border border-destructive/20">
                            {r.status}
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-sm bg-popover/95 border-border/50 text-xs font-semibold leading-relaxed rounded-xl shadow-xl backdrop-blur-md">
                          {r.decision_summary}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    <Badge variant={r.status === "completed" ? "secondary" : "destructive"} className="text-[10px] font-bold uppercase tracking-wider rounded-xl border border-border/30">
                      {r.status}
                    </Badge>
                  )}
                </td>
                <td className="px-5 py-3.5 text-right">
                  <div className="flex items-center justify-end gap-2.5">
                    {isCrypto && onTrade && (r.direction === "buy" || r.direction === "sell") && (
                      tradedSymbols?.has(r.ticker) ? (
                        <span className="text-[10px] font-black uppercase tracking-wider px-2.5 py-1 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                          Traded
                        </span>
                      ) : (
                        <button
                          onClick={() => onTrade(r.ticker, r.direction as "buy" | "sell")}
                          className="text-[10px] font-black uppercase tracking-wider px-3 py-1 rounded-xl bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 transition-all cursor-pointer active:scale-95"
                        >
                          Trade
                        </button>
                      )
                    )}
                    {r.run_id && (
                      <Link
                        to="/analysis/$runId"
                        params={{ runId: r.run_id }}
                        className="text-[10px] font-black uppercase tracking-wider px-3 py-1 rounded-xl bg-muted/20 text-foreground hover:bg-muted/40 transition-all border border-border/30"
                      >
                        View
                      </Link>
                    )}
                    {!r.run_id && r.status !== "completed" && r.decision_summary && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger>
                            <span className="text-xs font-bold text-muted-foreground hover:text-foreground cursor-help underline decoration-dotted">
                              Why?
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="left" className="max-w-sm bg-popover/95 border-border/50 text-xs font-semibold leading-relaxed rounded-xl shadow-xl backdrop-blur-md">
                            {r.decision_summary}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
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
  const [tradedSymbols, setTradedSymbols] = useState<Set<string>>(new Set());
  const [showCycleDialog, setShowCycleDialog] = useState(false);
  const handleTradeSuccess = (symbol: string) => setTradedSymbols((prev) => new Set(prev).add(symbol));

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
          <div className="flex items-center gap-2">
            {isCrypto && scan.status === "completed" && (
              <button
                onClick={() => setShowCycleDialog(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-700 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Start Cycle
              </button>
            )}
            <button
              onClick={handleDeleteClick}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
            >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
              Delete Scan
            </button>
          </div>
        )}
      </div>

      {/* Status card */}
      <div className="glass-card border border-border/50 bg-card/65 backdrop-blur-sm rounded-2xl shadow-sm overflow-hidden p-6 space-y-6">
        <div>
          <div className="flex items-center gap-3 mb-3">
            {scan.status === "completed" ? (
              <div className="w-8 h-8 rounded-xl bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
                <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            ) : scan.status === "running" ? (
              <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center border border-primary/20">
                <svg className="w-4 h-4 text-primary animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              </div>
            ) : (
              <div className="w-8 h-8 rounded-xl bg-destructive/10 flex items-center justify-center border border-destructive/20">
                <svg className="w-4 h-4 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
            )}
            <span className="text-sm font-black uppercase tracking-wider">{scan.status === "completed" ? "Scan Complete" : scan.status}</span>
            {scan.completed_at && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground font-mono tabular-nums">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {formatDurationBetween(scan.started_at, scan.completed_at)}
              </span>
            )}
          </div>

          <div className="text-xs text-muted-foreground/60 uppercase tracking-wider font-semibold">
            {scan.completed + scan.failed} / {scan.total} symbols &bull; {formatDate(scan.started_at)}
          </div>
        </div>

        {scan.status === "running" && (
          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-black uppercase tracking-wider text-muted-foreground/80">
              <span>{scan.completed + scan.failed} / {scan.total} symbols</span>
              <span>{progress}%</span>
            </div>
            <div className="h-3 rounded-full bg-muted/50 overflow-hidden p-[2px] border border-border/25">
              <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {/* Summary boxes */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <div className="rounded-2xl bg-emerald-500/5 border border-emerald-500/15 p-4 text-center">
            <div className="text-3xl font-black text-emerald-500 leading-none">{buyResults.length}</div>
            <div className="text-[10px] font-black uppercase tracking-wider text-muted-foreground/75 mt-2">Buy Signals</div>
          </div>
          <div className="rounded-2xl bg-red-500/5 border border-red-500/15 p-4 text-center">
            <div className="text-3xl font-black text-red-500 leading-none">{sellResults.length}</div>
            <div className="text-[10px] font-black uppercase tracking-wider text-muted-foreground/75 mt-2">Sell Signals</div>
          </div>
          <div className="rounded-2xl bg-amber-500/5 border border-amber-500/15 p-4 text-center col-span-2 sm:col-span-1">
            <div className="text-3xl font-black text-amber-500 leading-none">{holdResults.length}</div>
            <div className="text-[10px] font-black uppercase tracking-wider text-muted-foreground/75 mt-2">Hold / Neutral</div>
          </div>
        </div>
      </div>

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
          <ResultsTable results={buyResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
        </CollapsibleSection>
      )}
      {sellResults.length > 0 && (
        <CollapsibleSection title="Sell Signals" count={sellResults.length} dotColor="bg-red-500">
          <ResultsTable results={sellResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
        </CollapsibleSection>
      )}
      {holdResults.length > 0 && (
        <CollapsibleSection title="Hold / Neutral" count={holdResults.length} dotColor="bg-amber-500">
          <ResultsTable results={holdResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
        </CollapsibleSection>
      )}

      {/* Place Trade Dialog */}
      {tradeTarget && (
        <PlaceTradeDialog
          open={!!tradeTarget}
          onOpenChange={(open) => { if (!open) setTradeTarget(null); }}
          symbol={tradeTarget.symbol}
          signalDirection={tradeTarget.direction}
          onTradeSuccess={handleTradeSuccess}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => !deleteMutation.isPending && setDeleteConfirm(null)}
          />
          <div className="relative bg-card/85 border border-border/50 rounded-2xl shadow-2xl p-7 max-w-sm w-full mx-4 space-y-5 backdrop-blur-md">
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

      <TradingCycleDialog
        open={showCycleDialog}
        onOpenChange={setShowCycleDialog}
        scanId={scanId}
        scanLabel={`Scan ${scanId.slice(0, 8)}`}
      />
    </div>
  );
}
