import { useState, useEffect } from "react";
import { Link } from "@tanstack/react-router";
import { formatDurationBetween } from "@/lib/format";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, type ScanResultItem } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useScanFilters, ScanResultFiltersBar } from "@/components/scanner/ScanResultFilters";
import { PlaceTradeDialog } from "@/components/scanner/PlaceTradeDialog";
import { DIRECTION_CONFIG } from "@/components/scanner/constants";
import { NeuScoreBar } from "@/design-system/neumorphism";

// Custom ScoreBar removed in favor of design system's NeuScoreBar

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
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2.5 text-left px-4.5 py-3.5 hover:bg-[color-mix(in_oklch,var(--neu-accent)_4%,var(--neu-surface-base))] transition-colors cursor-pointer select-none font-bold text-xs uppercase tracking-wider text-[var(--neu-text-strong)]"
      >
        <svg
          className={cn("w-4 h-4 transition-transform duration-200 text-[var(--neu-text-muted)] shrink-0", open && "rotate-90")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", dotColor)} />
        <span>{title} ({count})</span>
      </button>
      {open && (
        <div className="border-t border-[color:var(--neu-stroke-soft)] bg-[var(--neu-surface-base)]">
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
          <tr className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] bg-[var(--neu-surface-deep)] border-none">
            <th className="text-left px-4 py-3 font-bold">#</th>
            <th className="text-left px-4 py-3 font-bold">Symbol</th>
            <th className="text-left px-4 py-3 font-bold hidden md:table-cell">Signal</th>
            <th className="text-left px-4 py-3 font-bold hidden md:table-cell">Confidence</th>
            <th className="text-left px-4 py-3 font-bold">Strength</th>
            <th className="text-left px-4 py-3 font-bold hidden md:table-cell">Status</th>
            <th className="text-right px-4 py-3 font-bold"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--neu-stroke-strong)]/20 bg-transparent">
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            const copied = copiedTicker === r.ticker;
            return (
              <tr key={r.ticker} className="hover:bg-[color-mix(in_oklch,var(--neu-accent)_4%,var(--neu-surface-base))] border-b border-[var(--neu-stroke-strong)]/30 last:border-none transition-colors group">
                <td className="px-4 py-3 text-[var(--neu-text-muted)] font-mono text-xs">{i + 1}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => handleCopy(r.ticker)}
                    title="Tap to copy"
                    className={cn(
                      "font-mono font-bold transition-all duration-150 rounded-[var(--neu-radius-sm)] px-2.5 py-1 -mx-2 active:scale-95 cursor-pointer border border-transparent text-sm",
                      copied
                        ? "text-[var(--neu-success)] bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]"
                        : "text-[var(--neu-text-strong)] group-hover:text-[var(--neu-accent)] hover:bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))] hover:border-[color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-stroke-soft))]",
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
                <td className="px-4 py-3 hidden md:table-cell">
                  <span className={cn("px-2.5 py-1 rounded-[var(--neu-radius-sm)] text-[10px] font-bold uppercase tracking-wider border border-transparent shadow-[var(--neu-shadow-pill)]", dir.label === "Buy" ? "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]" : dir.label === "Sell" ? "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]" : "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)]")}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs font-semibold capitalize hidden md:table-cell text-[var(--neu-text-muted)]">{r.confidence}</td>
                <td className="px-4 py-3">
                  <NeuScoreBar
                    score={r.score}
                    direction={r.direction === "buy" ? "buy" : r.direction === "sell" ? "sell" : "neutral"}
                  />
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  {r.status !== "completed" && r.decision_summary ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger className="cursor-help flex">
                          <span
                            className={cn(
                              "inline-flex items-center px-2.5 py-0.5 rounded-[var(--neu-radius-pill)] text-[10px] font-bold uppercase tracking-wider border shadow-[var(--neu-shadow-pill)]",
                              r.status === "failed" || r.status === "cancelled"
                                ? "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]"
                                : "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))]"
                            )}
                          >
                            {r.status}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent
                          side="top"
                          className="max-w-sm bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-xs text-[var(--neu-text-muted)] font-semibold leading-relaxed rounded-[var(--neu-radius-md)] shadow-[var(--neu-shadow-float)] p-3 backdrop-blur-xl"
                        >
                          {r.decision_summary}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    <span
                      className={cn(
                        "inline-flex items-center px-2.5 py-0.5 rounded-[var(--neu-radius-pill)] text-[10px] font-bold uppercase tracking-wider border shadow-[var(--neu-shadow-pill)]",
                        r.status === "completed"
                          ? "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]"
                          : "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)]"
                      )}
                    >
                      {r.status}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2.5">
                    {isCrypto && onTrade && (r.direction === "buy" || r.direction === "sell") && (
                      tradedSymbols?.has(r.ticker) ? (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-[var(--neu-radius-pill)] bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] inline-flex items-center gap-1.5 shadow-[var(--neu-shadow-pill)]">
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                          Traded
                        </span>
                      ) : (
                        <button
                          onClick={() => onTrade(r.ticker, r.direction as "buy" | "sell")}
                          className={cn(
                            "text-[10px] font-bold uppercase tracking-wider px-3.5 py-1.5 rounded-[var(--neu-radius-pill)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] hover:shadow-[var(--neu-shadow-raised-hover)] transition-all cursor-pointer active:scale-95 border-none",
                            r.direction === "buy"
                              ? "bg-[var(--neu-success)]"
                              : "bg-[var(--neu-danger)]"
                          )}
                        >
                          Trade
                        </button>
                      )
                    )}
                    {r.run_id && (
                      <Link
                        to="/analysis/$runId"
                        params={{ runId: r.run_id }}
                        className="text-[10px] font-bold uppercase tracking-wider px-3.5 py-1.5 rounded-[var(--neu-radius-pill)] bg-[var(--neu-surface-raised)] text-[var(--neu-text-strong)] border-none shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] hover:shadow-[var(--neu-shadow-raised-hover)] transition-all"
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
                           <TooltipContent
                            side="left"
                            className="max-w-sm bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-xs text-[var(--neu-text-muted)] font-semibold leading-relaxed rounded-[var(--neu-radius-md)] shadow-[var(--neu-shadow-float)] p-3 backdrop-blur-xl"
                          >
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
  const [isAutoTrading, setIsAutoTrading] = useState(false);
  const handleTradeSuccess = (symbol: string) => setTradedSymbols((prev) => new Set(prev).add(symbol));

  const { data: scan, isLoading, error } = useQuery({
    queryKey: ["scan", scanId],
    queryFn: ({ signal }) => apiClient.getScan(scanId, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "running") return 3000;
      if (isAutoTrading) return 3000;
      return false;
    },
  });

  // Stop polling once auto_trade_summaries arrive
  const autoTradeSummaries = scan?.auto_trade_summaries;
  useEffect(() => {
    if (isAutoTrading && autoTradeSummaries && autoTradeSummaries.length > 0) {
      setIsAutoTrading(false);
    }
  }, [isAutoTrading, autoTradeSummaries]);

  const autoTradeMutation = useMutation({
    mutationFn: () => apiClient.triggerAutoTrade(scanId),
    onSuccess: () => {
      setIsAutoTrading(true);
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["scan", scanId] });
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
        <Link to="/scanner/history" className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] flex items-center gap-1.5 transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to history
        </Link>
        <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-6 text-center text-[var(--neu-danger)] font-semibold">
          Scan not found or failed to load.
        </div>
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
          <Link to="/scanner/history" className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] flex items-center gap-1.5 mb-3 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Back to history
          </Link>
          <h1 className="text-xl font-bold flex items-center gap-2">
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
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-danger)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-all disabled:opacity-50 border-none cursor-pointer"
          >
            {cancelMutation.isPending ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
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
                onClick={() => autoTradeMutation.mutate()}
                disabled={isAutoTrading || autoTradeMutation.isPending}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-success)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-all border-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isAutoTrading || autoTradeMutation.isPending ? (
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                )}
                {isAutoTrading ? "Executing Trades..." : "Auto Trade"}
              </button>
            )}
            <button
              onClick={handleDeleteClick}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-surface-raised)] text-[var(--neu-danger)] hover:text-[var(--neu-danger)] shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] transition-all border-none cursor-pointer"
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
      <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-5 space-y-5">
        <div>
          <div className="flex items-center gap-3 mb-3">
            {scan.status === "completed" ? (
              <div className="w-8 h-8 rounded-xl bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]">
                <svg className="w-4 h-4 text-[var(--neu-success)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            ) : scan.status === "running" ? (
              <div className="w-8 h-8 rounded-xl bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))]">
                <svg className="w-4 h-4 text-[var(--neu-accent)] animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              </div>
            ) : (
              <div className="w-8 h-8 rounded-xl bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
                <svg className="w-4 h-4 text-[var(--neu-danger)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
            )}
            <span className="text-sm font-bold uppercase tracking-wider text-[var(--neu-text-strong)]">{scan.status === "completed" ? "Scan Complete" : scan.status}</span>
            {scan.started_at && (
              <span className="inline-flex items-center gap-1.5 text-xs text-[var(--neu-text-muted)] font-mono tabular-nums">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {scan.completed_at ? formatDurationBetween(scan.started_at, scan.completed_at) : "Running"}
              </span>
            )}
          </div>

          <div className="text-xs text-[var(--neu-text-muted)]/80 uppercase tracking-wider font-semibold">
            {scan.completed + scan.failed} / {scan.total} symbols &bull; {formatDate(scan.started_at)}
          </div>
        </div>

        {scan.status === "running" && (
          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)]">
              <span>{scan.completed + scan.failed} / {scan.total} symbols</span>
              <span>{progress}%</span>
            </div>
            <div className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-pill)] p-1 border-none">
              <div className="h-3 rounded-[var(--neu-radius-pill)] gradient-primary transition-all duration-500" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {/* Summary boxes */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 text-center border-none">
            <div className="text-2xl font-bold text-[var(--neu-success)] leading-none">{buyResults.length}</div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] mt-2">Buy Signals</div>
          </div>
          <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 text-center border-none">
            <div className="text-2xl font-bold text-[var(--neu-danger)] leading-none">{sellResults.length}</div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] mt-2">Sell Signals</div>
          </div>
          <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 text-center border-none col-span-2 sm:col-span-1">
            <div className="text-2xl font-bold text-[var(--neu-warning)] leading-none">{holdResults.length}</div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] mt-2">Hold / Neutral</div>
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
          <div className="relative bg-[var(--neu-surface-base)] border border-[color:var(--neu-stroke-soft)] rounded-[var(--neu-radius-lg)] shadow-[var(--neu-shadow-float)] p-6 max-w-sm w-full mx-4 space-y-5">
            <h3 className="text-lg font-bold text-[var(--neu-danger)] flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              Delete Scan
            </h3>

            {deleteConfirm.loading ? (
              <div className="flex items-center gap-2 text-sm text-[var(--neu-text-muted)]">
                <div className="w-4 h-4 border-2 border-[var(--neu-text-muted)] border-t-transparent rounded-full animate-spin" />
                Checking associated data...
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm">This will permanently delete this scan and all its results.</p>
                {(deleteConfirm.analysisCount ?? 0) > 0 && (
                  <div className="p-3 rounded-lg bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
                    <p className="text-sm font-medium text-[var(--neu-danger)]">
                      {deleteConfirm.analysisCount} analysis record{deleteConfirm.analysisCount !== 1 ? "s" : ""} will also be deleted.
                    </p>
                    <p className="text-xs text-[var(--neu-text-muted)] mt-1">
                      This includes all associated reports and agent outputs.
                    </p>
                  </div>
                )}
                <p className="text-xs text-[var(--neu-text-muted)]">This action cannot be undone.</p>
              </div>
            )}

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2.5 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-surface-raised)] text-[var(--neu-text-strong)] hover:translate-y-[-1px] shadow-[var(--neu-shadow-pill)] transition-all border-none cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate()}
                disabled={deleteConfirm.loading || deleteMutation.isPending}
                className="px-4 py-2.5 rounded-[var(--neu-radius-pill)] text-sm font-medium bg-[var(--neu-danger)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-colors disabled:opacity-50 flex items-center gap-2 border-none cursor-pointer"
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
