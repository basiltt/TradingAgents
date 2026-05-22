import { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/PageHeader";
import { parseTradeCard, type TradeCardData } from "@/components/analysis/parseTradeCard";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";

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

  const allItems = useMemo(() => data?.items ?? [], [data?.items]);

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

  const getConfidence = useCallback((runId: string): number => scoreMap.get(runId)?.confidence ?? 0, [scoreMap]);
  const getSignalStrength = useCallback((runId: string): number => {
    const card = scoreMap.get(runId);
    if (!card) return 0;
    const action = (card.action ?? card.rating ?? "").toLowerCase();
    const conf = card.confidence ?? 0;
    if (action === "short" || action === "sell") return -conf;
    if (action === "long" || action === "buy") return conf;
    return 0;
  }, [scoreMap]);

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
  }, [allItems, search, statusFilter, signalFilter, assetTypeFilter, confidenceRange, dateFrom, dateTo, sort, scoreMap, getConfidence, getSignalStrength]);

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
    <div className="space-y-5 pb-8">
      <PageHeader
        eyebrow="History"
        title="Analysis History"
        description=""
        stats={[
          { label: "Total Runs", value: String(allItems.length), tone: "neutral" },
          { label: "Completed", value: String(completedCount), tone: "success" },
          { label: "Running", value: String(runningCount), tone: runningCount > 0 ? "accent" : "neutral" },
          { label: "Buy Signals", value: String(buyCount), tone: buyCount > 0 ? "success" : "neutral" },
        ]}
        actions={
          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            {allItems.length > 0 && (
              confirmDeleteAll ? (
                <div className="flex items-center gap-2 rounded-[calc(var(--radius)*1.2)] border border-destructive/20 bg-destructive/5 p-1.5">
                  <button
                    onClick={() => deleteAllMutation.mutate()}
                    disabled={deleteAllMutation.isPending}
                    className="touch-target inline-flex items-center gap-1.5 rounded-[calc(var(--radius)*0.95)] bg-destructive px-3 py-1.75 text-xs font-extrabold uppercase tracking-wider text-destructive-foreground transition-all hover:brightness-110 active:scale-95 disabled:opacity-50"
                  >
                    {deleteAllMutation.isPending && (
                      <div className="h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                    )}
                    {deleteAllMutation.isPending ? "Deleting…" : "Confirm Delete"}
                  </button>
                  <button
                    onClick={() => setConfirmDeleteAll(false)}
                    className="touch-target rounded-[calc(var(--radius)*0.95)] border border-border/40 bg-muted px-3 py-1.75 text-xs font-extrabold uppercase tracking-wider text-foreground transition-all hover:bg-muted/80 active:scale-95"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDeleteAll(true)}
                  className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-destructive/20 bg-destructive/5 px-3 py-2.5 text-sm text-destructive shadow-[var(--shadow-soft)] transition-all hover:bg-destructive/10 hover:border-destructive/30"
                  title="Delete All Analyses"
                >
                  <svg className="size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              )
            )}
            <Link
              to="/analysis/new"
              className="touch-target inline-flex items-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-primary/20 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
            >
              <svg className="size-4 text-current" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Analysis
            </Link>
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          {allItems.length > 0 ? (
            <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
              {filtered.length !== allItems.length ? `${filtered.length} of ${allItems.length}` : `${allItems.length} total`}
            </span>
          ) : null}
          {activeFilterCount > 0 ? (
            <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
              {activeFilterCount} active filters
            </span>
          ) : null}
          <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
            {sellCount} sell signals
          </span>
          {(signalFilter.size > 0 || confidenceRange !== "any") && !allBatchesLoaded ? (
            <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
              Loading score tape…
            </span>
          ) : null}
        </div>
      </PageHeader>

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
                placeholder="Search by ticker or run ID…"
                className="w-full pl-10 pr-4 py-2 text-sm rounded-xl border border-border/50 bg-card/65 focus:outline-none focus:ring-2 focus:ring-primary/30 transition-all font-medium"
              />
            </div>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortOption)}
              className="shrink-0 px-3 py-2 text-xs rounded-xl border border-border/50 bg-card/65 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 font-bold uppercase tracking-wider cursor-pointer [&>option]:bg-card [&>option]:text-foreground"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          {/* Row 2: Status filter pills */}
          <div className="flex items-center gap-2 overflow-x-auto pb-0.5 no-scrollbar">
            {STATUS_FILTERS.map((s) => {
              const active = statusFilter.has(s);
              const cfg = STATUS_CONFIG[s];
              return (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[10px] font-extrabold uppercase tracking-wider rounded-lg border transition-all cursor-pointer whitespace-nowrap ${
                    active
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border/50 bg-card/40 text-muted-foreground hover:border-primary/40 hover:bg-card/75"
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
                className="px-2 py-1.5 text-[10px] font-black text-muted-foreground hover:text-foreground cursor-pointer uppercase tracking-wider whitespace-nowrap"
              >
                Clear
              </button>
            )}
            <span className="mx-1 w-px h-4 bg-border/50" />
            <button
              onClick={() => setShowAdvancedFilters((v) => !v)}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[10px] font-extrabold uppercase tracking-wider rounded-lg border transition-all cursor-pointer whitespace-nowrap ${
                showAdvancedFilters || activeFilterCount > 0
                  ? "border-primary bg-primary/10 text-primary shadow-sm"
                  : "border-border/50 bg-card/40 text-muted-foreground hover:border-primary/40 hover:bg-card/75"
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
              </svg>
              Advanced Filters
              {activeFilterCount > 0 && (
                <span className="w-4.5 h-4.5 rounded-full bg-primary text-primary-foreground text-[9px] font-black flex items-center justify-center">
                  {activeFilterCount}
                </span>
              )}
            </button>
          </div>

          {/* Advanced Filters Panel */}
          {showAdvancedFilters && (
            <div className="glass-card border border-border/50 bg-card/70 backdrop-blur-sm p-4.5 rounded-2xl shadow-lg space-y-4 animate-slide-in">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-extrabold text-muted-foreground uppercase tracking-wider">Configure Filter Metrics</span>
                {activeFilterCount > 0 && (
                  <button onClick={clearAllFilters} className="text-[10px] font-black uppercase tracking-wider text-primary hover:underline cursor-pointer">
                    Reset parameters
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Signal Direction */}
                <div className="space-y-1.5">
                  <label className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">Signal Action</label>
                  <div className="flex flex-wrap gap-1.5">
                    {SIGNAL_FILTERS.map((s) => {
                      const active = signalFilter.has(s);
                      const colors: Record<string, string> = { buy: "text-emerald-500 border-emerald-500/20", sell: "text-destructive border-destructive/20", hold: "text-amber-500 border-amber-500/20" };
                      return (
                        <button
                          key={s}
                          onClick={() => toggleSignal(s)}
                          className={`px-3 py-1 text-xs font-bold rounded-lg border transition-all capitalize cursor-pointer ${
                            active
                              ? "border-primary bg-primary/10 text-primary"
                              : `border-border/50 bg-card/30 hover:bg-card/75 ${colors[s] || "text-muted-foreground"}`
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
                  <label className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">Minimum Confidence</label>
                  <select
                    value={confidenceRange}
                    onChange={(e) => { setConfidenceRange(e.target.value as ConfidenceRange); setPage(0); }}
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-border/50 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 font-bold cursor-pointer [&>option]:bg-card [&>option]:text-foreground"
                  >
                    {CONFIDENCE_RANGES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>

                {/* Asset Type */}
                <div className="space-y-1.5">
                  <label className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">Asset Class</label>
                  <div className="flex flex-wrap gap-1.5">
                    {ASSET_TYPE_FILTERS.map((at) => {
                      const active = assetTypeFilter.has(at);
                      return (
                        <button
                          key={at}
                          onClick={() => toggleAssetType(at)}
                          className={`px-3 py-1 text-xs font-bold rounded-lg border transition-all capitalize cursor-pointer ${
                            active
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border/50 bg-card/30 hover:bg-card/75 text-muted-foreground"
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
                  <label className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">Date Range</label>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="date"
                      value={dateFrom}
                      onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
                      className="flex-1 px-2 py-1 text-xs rounded-lg border border-border/50 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                    <span className="text-xs text-muted-foreground font-bold">→</span>
                    <input
                      type="date"
                      value={dateTo}
                      onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
                      className="flex-1 px-2 py-1 text-xs rounded-lg border border-border/50 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
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
            <Skeleton key={i} className="h-18 w-full rounded-2xl" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-6 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto rounded-[calc(var(--radius)*1.25)] bg-destructive/10 flex items-center justify-center mb-4 border border-destructive/15">
            <svg className="w-6 h-6 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="font-bold text-destructive mb-1">Error loading history</p>
          <p className="text-sm text-muted-foreground font-medium">Could not connect to the API. Is the backend server running?</p>
        </div>
      ) : allItems.length === 0 ? (
        <div className="glass-card border border-dashed border-border/70 p-8 text-center rounded-2xl bg-card/65 animate-fade-in">
          <div className="w-12 h-12 mx-auto rounded-[calc(var(--radius)*1.25)] bg-muted/60 flex items-center justify-center mb-4 border border-border/40">
            <svg className="w-6 h-6 text-muted-foreground/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-bold mb-1.5">No analyses yet</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-xs mx-auto font-medium">
            Start your first analysis to see results here.
          </p>
          <Link to="/analysis/new" className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground font-bold text-xs uppercase tracking-wider hover:scale-[1.02] active:scale-98 transition-all shadow-lg shadow-primary/20 cursor-pointer">
            New Analysis
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="glass-card border border-dashed border-border/70 p-8 text-center rounded-2xl bg-card/65">
          <p className="text-sm text-muted-foreground font-medium">No results match your selected filter criteria.</p>
        </div>
      ) : (
        <>
          {/* ── Desktop: table layout ── */}
          <div className="hidden md:block glass-card border border-border/50 bg-card/65 backdrop-blur-sm rounded-2xl overflow-hidden shadow-sm">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border/40 bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider font-extrabold">
                  <th className="text-left px-4 py-3">Ticker</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Signal</th>
                  <th className="text-left px-4 py-3">Models</th>
                  <th className="text-left px-4 py-3">Date</th>
                  <th className="text-left px-4 py-3">Run ID</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((item) => {
                  const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
                  return (
                    <tr key={item.run_id} className="group border-b border-border/30 last:border-0 hover:bg-muted/15 transition-colors duration-150">
                      <td className="px-4 py-3.5">
                        <Link to="/analysis/$runId" params={{ runId: item.run_id }} className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-lg bg-muted/70 flex items-center justify-center shrink-0 border border-border/40 group-hover:bg-primary/10 group-hover:border-primary/20 transition-all duration-200">
                            <span className="font-mono font-black text-[10px] text-foreground/80">{item.ticker.slice(0, 4)}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold font-mono text-sm group-hover:text-primary transition-colors">{item.ticker}</span>
                            {item.asset_type === "crypto" && (
                              <span className="text-[9px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400 font-extrabold leading-none border border-amber-500/20">CRYPTO</span>
                            )}
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-3.5">
                        {item.status !== "completed" && item.status !== "running" && item.error ? (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger>
                                <span className="inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wider cursor-help">
                                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                                  {item.status}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="max-w-sm font-medium">
                                {item.error}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wider">
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                            {item.status}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        {item.status === "completed"
                          ? <TradeScoreDisplay card={scoreMap.get(item.run_id)} />
                          : <span className="text-xs text-muted-foreground/50 font-medium">—</span>
                        }
                      </td>
                      <td className="px-4 py-3.5">
                        {(() => {
                          const cfg = item.config ?? {};
                          const deep = String(cfg.deep_think_llm ?? "");
                          const quick = String(cfg.quick_think_llm ?? "");
                          if (!deep && !quick) return <span className="text-xs text-muted-foreground/50 font-medium">—</span>;
                          if (deep === quick) {
                            return <span className="text-[10px] font-mono text-muted-foreground font-medium">{deep}</span>;
                          }
                          return (
                            <div className="flex flex-col gap-0.5">
                              {deep && <span className="text-[10px] font-mono text-muted-foreground font-semibold" title="Deep think model">{deep}</span>}
                              {quick && quick !== deep && <span className="text-[10px] font-mono text-muted-foreground/60" title="Quick think model">{quick}</span>}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-4 py-3.5 text-xs text-muted-foreground whitespace-nowrap font-medium">
                        {item.analysis_date}{" "}
                        <span className="text-muted-foreground/60 font-normal">
                          {new Date(item.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-xs text-muted-foreground/45 font-mono max-w-[180px] truncate">
                        {item.run_id}
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {item.status === "running" && (
                            <button
                              onClick={() => cancelMutation.mutate(item.run_id)}
                              disabled={cancelMutation.isPending}
                              className="px-2.5 py-1 text-xs font-bold uppercase tracking-wider rounded-lg border border-amber-500/25 text-amber-500 bg-amber-500/5 hover:bg-amber-500/10 transition-all disabled:opacity-50 cursor-pointer"
                            >
                              {cancelMutation.isPending ? "…" : "Cancel"}
                            </button>
                          )}
                          {confirmId === item.run_id ? (
                            <div className="flex items-center gap-1.5 bg-destructive/10 border border-destructive/20 p-1 rounded-xl">
                              <button onClick={() => deleteMutation.mutate(item.run_id)} disabled={deleteMutation.isPending} className="px-2 py-1 text-[10px] font-extrabold uppercase tracking-wider rounded bg-destructive text-destructive-foreground hover:brightness-110 disabled:opacity-50 cursor-pointer transition-all">
                                {deleteMutation.isPending ? "…" : "Yes"}
                              </button>
                              <button onClick={() => setConfirmId(null)} className="px-2 py-1 text-[10px] font-extrabold uppercase tracking-wider rounded bg-muted text-foreground hover:bg-muted/80 cursor-pointer border border-border/40 transition-all">No</button>
                            </div>
                          ) : (
                            <button onClick={() => setConfirmId(item.run_id)} className="p-2 rounded-lg opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all duration-200 cursor-pointer" title="Delete">
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
          <div className="md:hidden space-y-3">
            {paged.map((item) => {
              const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
              return (
                <div key={item.run_id} className="group rounded-2xl border border-border/50 bg-card/65 backdrop-blur-sm hover:bg-card hover:border-border/70 hover:shadow-md transition-all duration-300">
                  <div className="p-4.5">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-xl bg-muted/80 flex items-center justify-center shrink-0 border border-border/40 group-hover:bg-primary/10 transition-colors">
                          <span className="font-mono font-black text-xs text-foreground/80">{item.ticker.slice(0, 4)}</span>
                        </div>
                        <Link to="/analysis/$runId" params={{ runId: item.run_id }} className="min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-bold font-mono text-sm group-hover:text-primary transition-colors">{item.ticker}</span>
                            {item.asset_type === "crypto" && (
                              <span className="text-[8px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400 font-extrabold border border-amber-500/20 leading-none">CRYPTO</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground font-semibold">
                            <span>{item.analysis_date}</span>
                            <span className="text-muted-foreground/60 font-normal">
                              {new Date(item.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                            </span>
                          </div>
                        </Link>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        {item.status === "running" && (
                          <button onClick={() => cancelMutation.mutate(item.run_id)} disabled={cancelMutation.isPending} className="px-2 py-1 text-xs font-bold uppercase tracking-wider rounded-lg border border-amber-500/25 text-amber-500 bg-amber-500/5 hover:bg-amber-500/10 transition-colors disabled:opacity-50 cursor-pointer">
                            {cancelMutation.isPending ? "…" : "Cancel"}
                          </button>
                        )}
                        {confirmId === item.run_id ? (
                          <div className="flex items-center gap-1 bg-destructive/10 border border-destructive/20 p-0.5 rounded-lg">
                            <button onClick={() => deleteMutation.mutate(item.run_id)} disabled={deleteMutation.isPending} className="px-2 py-0.5 text-[10px] font-black uppercase tracking-wider rounded bg-destructive text-destructive-foreground hover:brightness-110 disabled:opacity-50 cursor-pointer">
                              {deleteMutation.isPending ? "…" : "Yes"}
                            </button>
                            <button onClick={() => setConfirmId(null)} className="px-2 py-0.5 text-[10px] font-black uppercase tracking-wider rounded bg-muted text-foreground hover:bg-muted/80 cursor-pointer border border-border/40">No</button>
                          </div>
                        ) : (
                          <button onClick={() => setConfirmId(item.run_id)} className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors cursor-pointer" title="Delete">
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="mt-3 pt-3 border-t border-border/25 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-extrabold">Status:</span>
                        {item.status !== "completed" && item.status !== "running" && item.error ? (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger>
                                <span className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-wider cursor-help">
                                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                                  {item.status}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="max-w-sm">
                                {item.error}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wider">
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                            {item.status}
                          </span>
                        )}
                      </div>

                      {item.status === "completed" && (
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-extrabold">Signal:</span>
                          <TradeScoreDisplay card={scoreMap.get(item.run_id)} />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {/* end mobile cards */}

          {/* ── Pagination ── */}
          {filtered.length > pageSize && (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2">
              <div className="flex items-center gap-2.5 text-xs text-muted-foreground font-semibold">
                <span>
                  {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, filtered.length)} of {filtered.length}
                </span>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
                  className="px-2 py-1 rounded-lg border border-border/50 bg-card text-foreground text-xs font-bold cursor-pointer focus:outline-none [&>option]:bg-card [&>option]:text-foreground"
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
                  className="px-3.5 py-2 text-xs font-bold rounded-lg border border-border bg-card/65 hover:bg-muted hover:text-foreground active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                >
                  Prev
                </button>
                <span className="px-3 py-1.5 text-xs text-muted-foreground font-extrabold uppercase tracking-wider">
                  {safePage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage >= totalPages - 1}
                  className="px-3.5 py-2 text-xs font-bold rounded-lg border border-border bg-card/65 hover:bg-muted hover:text-foreground active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {deleteAllMutation.isPending && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="flex flex-col items-center gap-4 bg-card/90 border border-border/50 rounded-2xl p-8 shadow-2xl backdrop-blur">
            <div className="w-10 h-10 border-[3px] border-destructive border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-bold uppercase tracking-wider">Deleting all analyses…</p>
            <p className="text-xs text-muted-foreground font-medium">This may take a while for large databases.</p>
          </div>
        </div>
      )}
    </div>
  );
}
