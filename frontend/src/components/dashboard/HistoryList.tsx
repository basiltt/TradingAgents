import { useState, useMemo } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

export function HistoryList() {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortOption>("newest");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(25);

  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analyses"],
    queryFn: ({ signal }) => apiClient.listAnalyses({ limit: 10000 }, signal),
    staleTime: 30_000,
    refetchInterval: 30_000, // poll every 30s so deletes/changes on other devices sync
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

  const scoreQueries = useQueries({
    queries: completedRunIds.map((runId) => ({
      queryKey: ["trade-score", runId],
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const snap = await apiClient.getSnapshot(runId, signal);
        return parseTradeCard(snap.reports);
      },
      staleTime: Infinity,
      gcTime: 30 * 60 * 1000,
    })),
  });

  const scoreMap = useMemo(() => {
    const map = new Map<string, TradeCardData | null>();
    completedRunIds.forEach((id, i) => {
      map.set(id, scoreQueries[i]?.data ?? null);
    });
    return map;
  }, [completedRunIds, scoreQueries]);

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
  }, [allItems, search, statusFilter, sort, scoreMap]);

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

  return (
    <div className="space-y-5">
      {/* ── Header ── */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">History</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Browse past analyses and their results.
            {allItems.length > 0 && (
              <span className="ml-1.5 text-foreground font-medium">
                {filtered.length !== allItems.length
                  ? `${filtered.length} of ${allItems.length}`
                  : `${allItems.length} total`}
              </span>
            )}
          </p>
        </div>

        {/* Header action buttons — stack on mobile, row on sm+ */}
        <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap sm:shrink-0">
          {allItems.length > 0 && (
            confirmDeleteAll ? (
              <div className="flex items-center gap-1.5 w-full sm:w-auto">
                <button
                  onClick={() => deleteAllMutation.mutate()}
                  disabled={deleteAllMutation.isPending}
                  className="flex-1 sm:flex-none px-3 py-2 text-xs font-medium rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {deleteAllMutation.isPending ? "Deleting…" : "Confirm Delete All"}
                </button>
                <button
                  onClick={() => setConfirmDeleteAll(false)}
                  className="flex-1 sm:flex-none px-3 py-2 text-xs font-medium rounded-lg bg-muted text-muted-foreground hover:opacity-90 transition-opacity"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDeleteAll(true)}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-destructive/30 text-destructive font-medium text-sm hover:bg-destructive/10 transition-colors"
              >
                <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                <span className="hidden xs:inline">Delete All</span>
              </button>
            )
          )}
          <Link
            to="/analysis/new"
            className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:opacity-90 transition-opacity"
          >
            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Analysis
          </Link>
        </div>
      </div>

      {/* ── Search + Filters + Sort ── */}
      {allItems.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {/* Row 1: Search + Sort */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(0); }}
                placeholder="Search ticker or run ID…"
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortOption)}
              className="shrink-0 px-2.5 py-2 text-xs rounded-lg border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          {/* Row 2: Status filter pills — scroll horizontally on very small screens */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
            {STATUS_FILTERS.map((s) => {
              const active = statusFilter.has(s);
              const cfg = STATUS_CONFIG[s];
              return (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors whitespace-nowrap ${
                    active
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40"
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
          </div>
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
        <Card className="border-destructive/50">
          <CardContent className="flex items-center gap-3 py-6">
            <div className="w-10 h-10 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="font-medium text-destructive">Error loading history</p>
              <p className="text-sm text-muted-foreground">Could not connect to the API. Is the backend running?</p>
            </div>
          </CardContent>
        </Card>
      ) : allItems.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <div className="w-14 h-14 rounded-2xl bg-muted flex items-center justify-center mb-4">
              <svg className="w-7 h-7 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="font-semibold mb-1">No analyses yet</h3>
            <p className="text-sm text-muted-foreground max-w-sm">
              Start your first analysis to see results here.
            </p>
          </CardContent>
        </Card>
      ) : filtered.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-8 text-center">
            <p className="text-sm text-muted-foreground">No results match your filters.</p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ── Desktop: table layout ── */}
          <div className="hidden md:block rounded-xl border border-border overflow-hidden">
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
                        <Badge variant={cfg.variant} className="gap-1 text-[10px] py-0.5 h-auto leading-none">
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                          {item.status}
                        </Badge>
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
                <Card key={item.run_id} className="group hover:shadow-md hover:border-primary/30 transition-all duration-200">
                  <CardContent className="py-3 px-3">
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
                          <Badge variant={cfg.variant} className="gap-1 text-[10px] py-0.5 h-auto leading-none">
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                            {item.status}
                          </Badge>
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
                  </CardContent>
                </Card>
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
                  className="px-2 py-1 rounded border border-border bg-background text-foreground text-xs focus:outline-none"
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
    </div>
  );
}
