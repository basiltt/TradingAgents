import { useState, useMemo, useEffect } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { parseTradeCard, type TradeCardData } from "@/components/analysis/parseTradeCard";

const STATUS_CONFIG: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; dot: string }> = {
  running: { variant: "default", dot: "bg-primary animate-pulse" },
  completed: { variant: "secondary", dot: "bg-emerald-500" },
  failed: { variant: "destructive", dot: "bg-destructive" },
  cancelled: { variant: "outline", dot: "bg-muted-foreground" },
  pending: { variant: "outline", dot: "bg-amber-500" },
};

const ACTION_COLORS: Record<string, string> = {
  buy: "text-emerald-500",
  sell: "text-red-500",
  hold: "text-amber-500",
  long: "text-emerald-500",
  short: "text-red-500",
};

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "confidence-desc", label: "Confidence ↓" },
  { value: "confidence-asc", label: "Confidence ↑" },
  { value: "signal-strongest", label: "Strongest signal" },
  { value: "ticker-az", label: "Ticker A → Z" },
  { value: "ticker-za", label: "Ticker Z → A" },
] as const;

type SortOption = (typeof SORT_OPTIONS)[number]["value"];

const STATUS_FILTERS = ["running", "completed", "failed", "cancelled"] as const;
const PAGE_SIZES = [10, 25, 50, 100] as const;

function actionColor(action?: string) {
  if (!action) return "text-muted-foreground";
  return ACTION_COLORS[action.toLowerCase()] ?? "text-muted-foreground";
}

function TradeScoreDisplay({ card }: { card: TradeCardData | null | undefined }) {
  if (!card) return null;
  const action = card.action ?? card.rating ?? "—";
  const conf = card.confidence;
  return (
    <div className="flex items-center gap-1.5 text-xs shrink-0">
      <span className={`font-bold uppercase ${actionColor(action)}`}>{action}</span>
      {conf != null && (
        <span className="text-muted-foreground">{conf}/10</span>
      )}
    </div>
  );
}

const SIGNAL_FILTERS = ["buy", "sell", "hold"] as const;
const ASSET_TYPE_FILTERS = ["crypto", "stock"] as const;
const CONFIDENCE_RANGES = [
  { value: "any", label: "Any" },
  { value: "very-high", label: "Very High (9-10)" },
  { value: "high", label: "High (7-8)" },
  { value: "medium", label: "Medium (4-6)" },
  { value: "low", label: "Low (2-3)" },
  { value: "very-low", label: "Very Low (1)" },
  { value: "none", label: "No signal" },
] as const;

type ConfidenceRange = (typeof CONFIDENCE_RANGES)[number]["value"];

export function HistoryList() {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [signalFilter, setSignalFilter] = useState<Set<string>>(new Set());
  const [assetTypeFilter, setAssetTypeFilter] = useState<Set<string>>(new Set());
  const [confidenceRange, setConfidenceRange] = useState<ConfidenceRange>("any");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [sort, setSort] = useState<SortOption>("newest");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(25);

  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analyses"],
    queryFn: ({ signal }) => apiClient.listAnalyses({ limit: 10000 }, signal),
    staleTime: 15_000,
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      const hasRunning = items?.some((i) => i.status === "running");
      return hasRunning ? 5000 : 30_000;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: string) => apiClient.deleteAnalysis(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      setConfirmId(null);
    },
  });

  const deleteAllMutation = useMutation({
    mutationFn: () => apiClient.deleteAllAnalyses(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      setConfirmDeleteAll(false);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => apiClient.cancelAnalysis(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
    },
  });

  const allItems = data?.items ?? [];

  const completedRunIds = useMemo(
    () => allItems.filter((i) => i.status === "completed").map((i) => i.run_id),
    [allItems]
  );

  // Only fetch scores in batches — prioritize current page, then progressively load rest
  const BATCH_SIZE = 50;
  const [scoreBatchIndex, setScoreBatchIndex] = useState(0);

  const scoreBatchIds = useMemo(
    () => completedRunIds.slice(0, (scoreBatchIndex + 1) * BATCH_SIZE),
    [completedRunIds, scoreBatchIndex]
  );

  const scoreQueries = useQueries({
    queries: scoreBatchIds.map((runId) => ({
      queryKey: ["trade-score", runId],
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const snap = await apiClient.getSnapshot(runId, signal);
        return parseTradeCard(snap.reports);
      },
      staleTime: Infinity,
      gcTime: 30 * 60 * 1000,
    })),
  });

  // Progressively load more batches
  const allBatchesLoaded = scoreBatchIds.length >= completedRunIds.length;
  const currentBatchDone = scoreQueries.every((q) => !q.isLoading);
  useEffect(() => {
    if (currentBatchDone && !allBatchesLoaded) {
      const t = setTimeout(() => setScoreBatchIndex((i) => i + 1), 100);
      return () => clearTimeout(t);
    }
  }, [currentBatchDone, allBatchesLoaded]);

  const scoreMap = useMemo(() => {
    const map = new Map<string, TradeCardData | null | undefined>();
    // Mark all completed as undefined first
    completedRunIds.forEach((id) => map.set(id, undefined));
    // Then fill in loaded ones
    scoreBatchIds.forEach((id, i) => {
      const q = scoreQueries[i];
      if (!q || q.isLoading) return;
      map.set(id, q.data ?? null);
    });
    return map;
  }, [completedRunIds, scoreBatchIds, scoreQueries]);

  const getConfidence = (runId: string): number => scoreMap.get(runId)?.confidence ?? 0;
  const getSignalStrength = (runId: string): number => {
    const card = scoreMap.get(runId);
    if (!card) return 0;
    const action = (card.action ?? card.rating ?? "").toLowerCase();
    const conf = card.confidence ?? 0;
    if (action === "short" || action === "sell") return -conf;
    if (action === "long" || action === "buy") return conf;
    return 0;
  };

  const filtered = useMemo(() => {
    let items = [...allItems];

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      items = items.filter(
        (i) =>
          i.ticker.toLowerCase().includes(q) ||
          i.run_id.toLowerCase().includes(q)
      );
    }

    if (statusFilter.size > 0) {
      items = items.filter((i) => statusFilter.has(i.status));
    }

    if (signalFilter.size > 0) {
      items = items.filter((i) => {
        if (i.status !== "completed") return false;
        const card = scoreMap.get(i.run_id);
        if (card === undefined) return false; // score not loaded yet — hide until confirmed
        if (!card) return signalFilter.has("hold");
        const action = (card.action ?? card.rating ?? "hold").toLowerCase();
        if (action === "buy" || action === "long") return signalFilter.has("buy");
        if (action === "sell" || action === "short") return signalFilter.has("sell");
        return signalFilter.has("hold");
      });
    }

    if (assetTypeFilter.size > 0) {
      items = items.filter((i) => {
        const at = i.asset_type ?? "crypto";
        return assetTypeFilter.has(at);
      });
    }

    if (confidenceRange !== "any") {
      items = items.filter((i) => {
        if (scoreMap.get(i.run_id) === undefined) return false; // not loaded yet
        const conf = getConfidence(i.run_id);
        switch (confidenceRange) {
          case "very-high": return conf >= 9;
          case "high": return conf >= 7 && conf <= 8;
          case "medium": return conf >= 4 && conf <= 6;
          case "low": return conf >= 2 && conf <= 3;
          case "very-low": return conf === 1;
          case "none": return conf === 0;
          default: return true;
        }
      });
    }

    if (dateFrom) {
      items = items.filter((i) => (i.analysis_date ?? i.started_at ?? "") >= dateFrom);
    }
    if (dateTo) {
      const toEnd = dateTo + "T23:59:59";
      items = items.filter((i) => (i.analysis_date ?? i.started_at ?? "") <= toEnd);
    }

    items.sort((a, b) => {
      switch (sort) {
        case "oldest":
          return (a.analysis_date ?? "").localeCompare(b.analysis_date ?? "");
        case "ticker-az":
          return a.ticker.localeCompare(b.ticker);
        case "ticker-za":
          return b.ticker.localeCompare(a.ticker);
        case "confidence-desc":
          return getConfidence(b.run_id) - getConfidence(a.run_id);
        case "confidence-asc":
          return getConfidence(a.run_id) - getConfidence(b.run_id);
        case "signal-strongest":
          return Math.abs(getSignalStrength(b.run_id)) - Math.abs(getSignalStrength(a.run_id));
        case "newest":
        default:
          return (b.analysis_date ?? "").localeCompare(a.analysis_date ?? "");
      }
    });

    return items;
  }, [allItems, search, statusFilter, signalFilter, assetTypeFilter, confidenceRange, dateFrom, dateTo, sort, scoreMap]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const paged = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize);

  const toggleStatus = (s: string) => {
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
    setPage(0);
  };

  const toggleSignal = (s: string) => {
    setSignalFilter((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
    setPage(0);
  };

  const toggleAssetType = (s: string) => {
    setAssetTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
    setPage(0);
  };

  const activeFilterCount = signalFilter.size + assetTypeFilter.size + (confidenceRange !== "any" ? 1 : 0) + (dateFrom ? 1 : 0) + (dateTo ? 1 : 0);

  const clearAllFilters = () => {
    setStatusFilter(new Set());
    setSignalFilter(new Set());
    setAssetTypeFilter(new Set());
    setConfidenceRange("any");
    setDateFrom("");
    setDateTo("");
    setPage(0);
  };

  const buyCount = useMemo(() => {
    let count = 0;
    scoreMap.forEach((card) => {
      if (!card) return;
      const a = (card.action ?? card.rating ?? "").toLowerCase();
      if (a === "buy" || a === "long") count++;
    });
    return count;
  }, [scoreMap]);

  const sellCount = useMemo(() => {
    let count = 0;
    scoreMap.forEach((card) => {
      if (!card) return;
      const a = (card.action ?? card.rating ?? "").toLowerCase();
      if (a === "sell" || a === "short") count++;
    });
    return count;
  }, [scoreMap]);

  const completedCount = allItems.filter((i) => i.status === "completed").length;
  const runningCount = allItems.filter((i) => i.status === "running").length;

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Analysis History</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Browse past analyses and their results
            {allItems.length > 0 && (
              <span className="ml-1.5 text-foreground font-medium">
                {filtered.length !== allItems.length
                  ? `${filtered.length} of ${allItems.length}`
                  : `${allItems.length} total`}
              </span>
            )}
            {(signalFilter.size > 0 || confidenceRange !== "any") && !allBatchesLoaded && (
              <span className="ml-1.5 text-muted-foreground text-xs animate-pulse">loading scores…</span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {allItems.length > 0 && (
            confirmDeleteAll ? (
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => deleteAllMutation.mutate()}
                  disabled={deleteAllMutation.isPending}
                  className="px-4 py-2.5 text-sm font-medium rounded-xl bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors inline-flex items-center gap-2"
                >
                  {deleteAllMutation.isPending && (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  )}
                  {deleteAllMutation.isPending ? "Deleting…" : "Confirm Delete All"}
                </button>
                <button
                  onClick={() => setConfirmDeleteAll(false)}
                  className="px-4 py-2.5 text-sm font-medium rounded-xl bg-secondary hover:bg-secondary/80 transition-colors"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDeleteAll(true)}
                className="p-2.5 rounded-xl border border-red-500/30 text-red-500 hover:bg-red-500/10 transition-colors"
                title="Delete All"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            )
          )}
          <Link
            to="/analysis/new"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/25"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Analysis
          </Link>
        </div>
      </div>

      {/* Stats row */}
      {allItems.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="rounded-2xl border border-border/50 bg-card p-5">
            <div className="text-2xl font-bold tabular-nums">{allItems.length}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Total</div>
          </div>
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-emerald-500">{completedCount}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Completed</div>
          </div>
          <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-blue-500">{runningCount}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Running</div>
          </div>
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-emerald-500">{buyCount}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Buy Signals</div>
          </div>
          <div className="rounded-2xl border border-red-500/20 bg-red-500/[0.04] p-5">
            <div className="text-2xl font-bold tabular-nums text-red-500">{sellCount}</div>
            <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wider font-medium">Sell Signals</div>
          </div>
        </div>
      )}

      {/* ── Search + Filters + Sort ── */}
      {allItems.length > 0 && (
        <div className="flex flex-col gap-3">
          {/* Row 1: Search + Sort */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(0); }}
                placeholder="Search ticker or run ID…"
                className="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-border/50 bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow"
              />
            </div>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortOption)}
              className="shrink-0 px-3 py-2.5 text-xs rounded-xl border border-border/50 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 [&>option]:bg-background [&>option]:text-foreground"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          {/* Row 2: Status filter pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
            {STATUS_FILTERS.map((s) => {
              const active = statusFilter.has(s);
              const cfg = STATUS_CONFIG[s];
              return (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors whitespace-nowrap capitalize ${
                    active
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border/50 text-muted-foreground hover:border-primary/40"
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                  {s}
                </button>
              );
            })}
            {statusFilter.size > 0 && (
              <button
                onClick={() => { setStatusFilter(new Set()); setPage(0); }}
                className="px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground whitespace-nowrap"
              >
                Clear
              </button>
            )}
            <span className="mx-1 w-px h-4 bg-border/50" />
            <button
              onClick={() => setShowAdvancedFilters((v) => !v)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors whitespace-nowrap ${
                showAdvancedFilters || activeFilterCount > 0
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border/50 text-muted-foreground hover:border-primary/40"
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
              </svg>
              Filters
              {activeFilterCount > 0 && (
                <span className="w-4 h-4 rounded-full bg-primary text-white text-[10px] font-bold flex items-center justify-center">
                  {activeFilterCount}
                </span>
              )}
            </button>
          </div>

          {/* Advanced Filters Panel */}
          {showAdvancedFilters && (
            <div className="rounded-2xl border border-border/50 bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Advanced Filters</span>
                {activeFilterCount > 0 && (
                  <button onClick={clearAllFilters} className="text-xs text-primary hover:underline">
                    Clear all filters
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {/* Signal Direction */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Signal</label>
                  <div className="flex flex-wrap gap-1">
                    {SIGNAL_FILTERS.map((s) => {
                      const active = signalFilter.has(s);
                      const colors: Record<string, string> = { buy: "text-emerald-500", sell: "text-red-500", hold: "text-amber-500" };
                      return (
                        <button
                          key={s}
                          onClick={() => toggleSignal(s)}
                          className={`px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors capitalize ${
                            active
                              ? "border-primary bg-primary/10 text-primary"
                              : `border-border/50 ${colors[s]} hover:border-primary/40`
                          }`}
                        >
                          {s}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Confidence */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Confidence</label>
                  <select
                    value={confidenceRange}
                    onChange={(e) => { setConfidenceRange(e.target.value as ConfidenceRange); setPage(0); }}
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-border/50 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 [&>option]:bg-background [&>option]:text-foreground"
                  >
                    {CONFIDENCE_RANGES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>

                {/* Asset Type */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Asset Type</label>
                  <div className="flex flex-wrap gap-1">
                    {ASSET_TYPE_FILTERS.map((at) => {
                      const active = assetTypeFilter.has(at);
                      return (
                        <button
                          key={at}
                          onClick={() => toggleAssetType(at)}
                          className={`px-2 py-1 text-xs font-medium rounded border transition-colors capitalize ${
                            active
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border text-muted-foreground hover:border-primary/40"
                          }`}
                        >
                          {at}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Date Range */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Date Range</label>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="date"
                      value={dateFrom}
                      onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
                      className="flex-1 px-2 py-1.5 text-xs rounded border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                    />
                    <span className="text-xs text-muted-foreground">→</span>
                    <input
                      type="date"
                      value={dateTo}
                      onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
                      className="flex-1 px-2 py-1.5 text-xs rounded border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Content ── */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-[72px] w-full rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-destructive/10 flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="font-semibold text-destructive mb-1">Error loading history</p>
          <p className="text-sm text-muted-foreground">Could not connect to the API. Is the backend running?</p>
        </div>
      ) : allItems.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/60 p-16 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-muted/50 flex items-center justify-center mb-5">
            <svg className="w-8 h-8 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1.5">No analyses yet</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-xs mx-auto">
            Start your first analysis to see results here.
          </p>
          <Link to="/analysis/new" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 transition-all shadow-lg shadow-primary/25">
            New Analysis
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/60 p-12 text-center">
          <p className="text-sm text-muted-foreground">No results match your filters.</p>
        </div>
      ) : (
        <>
          {/* ── Desktop: table layout ── */}
          <div className="hidden md:block rounded-2xl border border-border/50 bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
                  <th className="text-left px-4 py-2.5 font-medium">Ticker</th>
                  <th className="text-left px-4 py-2.5 font-medium">Status</th>
                  <th className="text-left px-4 py-2.5 font-medium">Signal</th>
                  <th className="text-left px-4 py-2.5 font-medium">Models</th>
                  <th className="text-left px-4 py-2.5 font-medium">Date</th>
                  <th className="text-left px-4 py-2.5 font-medium">Run ID</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {paged.map((item) => {
                  const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
                  return (
                    <tr key={item.run_id} className="group border-b border-border/50 last:border-0 hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-2.5">
                        <Link to="/analysis/$runId" params={{ runId: item.run_id }} className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-muted flex items-center justify-center shrink-0 group-hover:bg-primary/10 transition-colors">
                            <span className="font-mono font-bold text-[10px] text-foreground">{item.ticker.slice(0, 4)}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold font-mono text-sm">{item.ticker}</span>
                            {item.asset_type === "crypto" && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 font-medium leading-none">CRYPTO</span>
                            )}
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium capitalize">
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                          {item.status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        {item.status === "completed"
                          ? <TradeScoreDisplay card={scoreMap.get(item.run_id)} />
                          : <span className="text-xs text-muted-foreground">—</span>
                        }
                      </td>
                      <td className="px-4 py-2.5">
                        {(() => {
                          const cfg = item.config ?? {};
                          const deep = String(cfg.deep_think_llm ?? "");
                          const quick = String(cfg.quick_think_llm ?? "");
                          if (!deep && !quick) return <span className="text-xs text-muted-foreground">—</span>;
                          if (deep === quick) {
                            return <span className="text-[10px] font-mono text-muted-foreground">{deep}</span>;
                          }
                          return (
                            <div className="flex flex-col gap-0.5">
                              {deep && <span className="text-[10px] font-mono text-muted-foreground" title="Deep think model">{deep}</span>}
                              {quick && quick !== deep && <span className="text-[10px] font-mono text-muted-foreground/60" title="Quick think model">{quick}</span>}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                        {item.analysis_date}{" "}
                        <span className="text-muted-foreground/60">
                          {new Date(item.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground/50 font-mono max-w-[180px] truncate">
                        {item.run_id}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {item.status === "running" && (
                            <button
                              onClick={() => cancelMutation.mutate(item.run_id)}
                              disabled={cancelMutation.isPending}
                              className="px-2 py-1 text-xs font-medium rounded-md border border-amber-500/30 text-amber-500 hover:bg-amber-500/10 transition-colors disabled:opacity-50"
                            >
                              {cancelMutation.isPending ? "…" : "Cancel"}
                            </button>
                          )}
                          {confirmId === item.run_id ? (
                            <div className="flex items-center gap-1">
                              <button onClick={() => deleteMutation.mutate(item.run_id)} disabled={deleteMutation.isPending} className="px-2 py-1 text-xs font-medium rounded bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50">
                                {deleteMutation.isPending ? "…" : "Delete"}
                              </button>
                              <button onClick={() => setConfirmId(null)} className="px-2 py-1 text-xs font-medium rounded bg-muted text-muted-foreground hover:opacity-90">No</button>
                            </div>
                          ) : (
                            <button onClick={() => setConfirmId(item.run_id)} className="p-1.5 rounded-md opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all" title="Delete">
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── Mobile: card layout ── */}
          <div className="md:hidden space-y-2">
            {paged.map((item) => {
              const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
              return (
                <div key={item.run_id} className="group rounded-2xl border border-border/40 bg-card hover:bg-card/80 hover:border-border/70 transition-all duration-200 hover:shadow-lg hover:shadow-black/5 overflow-hidden">
                  <div className="py-3 px-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-xl bg-muted flex items-center justify-center shrink-0 group-hover:bg-primary/10 transition-colors">
                        <span className="font-mono font-bold text-xs text-foreground">{item.ticker.slice(0, 4)}</span>
                      </div>
                      <Link to="/analysis/$runId" params={{ runId: item.run_id }} className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-semibold font-mono text-sm">{item.ticker}</span>
                          {item.asset_type === "crypto" && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 font-medium leading-none">CRYPTO</span>
                          )}
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium capitalize">
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                            {item.status}
                          </span>
                          {item.status === "completed" && <TradeScoreDisplay card={scoreMap.get(item.run_id)} />}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-muted-foreground">{item.analysis_date}</span>
                          <span className="text-xs text-muted-foreground/60">
                            {new Date(item.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                        </div>
                      </Link>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {item.status === "running" && (
                          <button onClick={() => cancelMutation.mutate(item.run_id)} disabled={cancelMutation.isPending} className="px-2 py-1 text-xs font-medium rounded-md border border-amber-500/30 text-amber-500 hover:bg-amber-500/10 transition-colors disabled:opacity-50">
                            {cancelMutation.isPending ? "…" : "Cancel"}
                          </button>
                        )}
                        {confirmId === item.run_id ? (
                          <div className="flex items-center gap-1">
                            <button onClick={() => deleteMutation.mutate(item.run_id)} disabled={deleteMutation.isPending} className="px-2 py-1 text-xs font-medium rounded bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50">
                              {deleteMutation.isPending ? "…" : "Delete"}
                            </button>
                            <button onClick={() => setConfirmId(null)} className="px-2 py-1 text-xs font-medium rounded bg-muted text-muted-foreground hover:opacity-90">No</button>
                          </div>
                        ) : (
                          <button onClick={() => setConfirmId(item.run_id)} className="p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all" title="Delete">
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {/* end mobile cards */}

          {/* ── Pagination ── */}
          {filtered.length > pageSize && (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between pt-1">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>
                  {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, filtered.length)} of {filtered.length}
                </span>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
                  className="px-2 py-1 rounded-lg border border-border/50 bg-background text-foreground text-xs focus:outline-none [&>option]:bg-background [&>option]:text-foreground"
                >
                  {PAGE_SIZES.map((s) => (
                    <option key={s} value={s}>{s} / page</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-muted disabled:opacity-40 transition-colors"
                >
                  Prev
                </button>
                <span className="px-3 py-1.5 text-xs text-muted-foreground">
                  {safePage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage >= totalPages - 1}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-muted disabled:opacity-40 transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {deleteAllMutation.isPending && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-4 bg-card border rounded-2xl p-8 shadow-2xl">
            <div className="w-10 h-10 border-[3px] border-red-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-medium">Deleting all analyses…</p>
            <p className="text-xs text-muted-foreground">This may take a while for large histories</p>
          </div>
        </div>
      )}
    </div>
  );
}
