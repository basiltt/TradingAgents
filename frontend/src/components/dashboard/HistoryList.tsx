import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS_CONFIG: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; dot: string }> = {
  running: { variant: "default", dot: "bg-primary animate-pulse" },
  completed: { variant: "secondary", dot: "bg-emerald-500" },
  failed: { variant: "destructive", dot: "bg-destructive" },
  cancelled: { variant: "outline", dot: "bg-muted-foreground" },
  pending: { variant: "outline", dot: "bg-amber-500" },
};

export function HistoryList() {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analyses"],
    queryFn: ({ signal }) => apiClient.listAnalyses(undefined, signal),
    staleTime: 30_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: string) => apiClient.deleteAnalysis(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      setConfirmId(null);
    },
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">History</h1>
          <p className="text-muted-foreground mt-1">Browse past analyses and their results.</p>
        </div>
        <Link
          to="/analysis/new"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:opacity-90 transition-opacity"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          New Analysis
        </Link>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
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
      ) : (data?.items ?? []).length === 0 ? (
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
      ) : (
        <div className="space-y-2">
          {(data?.items ?? []).map((item) => {
            const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
            return (
              <Card key={item.run_id} className="group hover:shadow-md hover:border-primary/30 transition-all duration-200">
                <CardContent className="py-3.5 px-4 flex items-center justify-between gap-4">
                  <Link
                    to="/analysis/$runId"
                    params={{ runId: item.run_id }}
                    className="flex items-center gap-4 min-w-0 flex-1 cursor-pointer"
                  >
                    <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center shrink-0 group-hover:bg-primary/10 transition-colors">
                      <span className="font-mono font-bold text-sm text-foreground">{item.ticker.slice(0, 4)}</span>
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold font-mono">{item.ticker}</span>
                        {item.asset_type === "crypto" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 font-medium">CRYPTO</span>
                        )}
                        <span className="text-xs text-muted-foreground">{item.analysis_date}</span>
                      </div>
                      <p className="text-xs text-muted-foreground truncate font-mono">
                        {item.run_id}
                      </p>
                    </div>
                  </Link>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={cfg.variant} className="gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                      {item.status}
                    </Badge>
                    {confirmId === item.run_id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => deleteMutation.mutate(item.run_id)}
                          disabled={deleteMutation.isPending}
                          className="px-2 py-1 text-xs font-medium rounded bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50"
                        >
                          {deleteMutation.isPending ? "…" : "Confirm"}
                        </button>
                        <button
                          onClick={() => setConfirmId(null)}
                          className="px-2 py-1 text-xs font-medium rounded bg-muted text-muted-foreground hover:opacity-90"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmId(item.run_id)}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                        title="Delete analysis"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
