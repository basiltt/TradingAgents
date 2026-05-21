import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { cn } from "@/lib/utils";

export function MemoryPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["memory", page],
    queryFn: ({ signal }) => apiClient.getMemory({ page, limit: 25 }, signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-10">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">Cognitive Memory Log</h1>
        <p className="text-xs text-muted-foreground mt-1.5 font-medium uppercase tracking-wider">
          Explore historical trading decisions, confidence metrics, and LLM agent reasoning outputs
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3.5">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 w-full rounded-2xl bg-muted/20 animate-pulse border border-border/30" />
          ))}
        </div>
      ) : isError || !data ? (
        <div className="glass-card border border-destructive/20 bg-destructive/5 rounded-2xl p-6 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0 border border-destructive/15">
            <svg className="w-5 h-5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-destructive">Failed to fetch cognitive memory log</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">Could not establish connection. Check backend services.</p>
          </div>
        </div>
      ) : data.items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/40 p-16 text-center bg-muted/5">
          <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-5 border border-border/30">
            <svg className="w-8 h-8 text-muted-foreground/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
            </svg>
          </div>
          <h3 className="text-sm font-bold uppercase tracking-wider mb-1.5">No memories yet</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto leading-relaxed">
            Run standard ticker analysis configurations to generate execution history logs.
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {data.items.map((entry, i) => {
              const dec = entry.decision.toLowerCase();
              const decStyle =
                dec === "buy" || dec === "long" ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" :
                dec === "sell" || dec === "short" ? "bg-red-500/10 text-red-500 border-red-500/20" :
                "bg-amber-500/10 text-amber-500 border-amber-500/20";

              return (
                <div key={`${entry.ticker}-${entry.date}-${i}`} className="glass-card border border-border/40 bg-card/65 rounded-2xl shadow-sm transition-all duration-300 hover:border-border/60 hover:bg-card/85 p-5">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                    <div className="flex items-start gap-4 min-w-0">
                      <div className="w-10 h-10 rounded-xl bg-muted/80 flex items-center justify-center shrink-0 border border-border/10">
                        <span className="font-mono font-black text-xs text-foreground">{entry.ticker.slice(0, 4)}</span>
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-black font-mono text-sm tracking-tight">{entry.ticker}</span>
                          <span className="text-[10px] text-muted-foreground/70 font-semibold uppercase tracking-wider">{entry.date}</span>
                          <span className={cn("text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full border shadow-sm", decStyle)}>
                            {entry.decision}
                          </span>
                          <span className="text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded bg-muted text-muted-foreground border border-border/30">
                            Conf: {entry.confidence}
                          </span>
                        </div>
                        {entry.reasoning && (
                          <p className="text-xs text-foreground/80 font-medium leading-relaxed mt-2 select-text">{entry.reasoning}</p>
                        )}
                      </div>
                    </div>
                    <span className={cn(
                      "text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded-md border shrink-0 sm:ml-auto self-start",
                      entry.status === "resolved" ? "bg-primary/10 text-primary border-primary/20" : "bg-muted/30 text-muted-foreground border-border/20"
                    )}>
                      {entry.status}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {data.total > 25 && (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-4 border-t border-border/20">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                Showing page {data.page} of {Math.ceil(data.total / 25)} ({data.total} cognitive records)
              </p>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="px-4 py-2 text-xs font-black uppercase tracking-wider rounded-xl border border-border/40 hover:bg-muted disabled:opacity-40 transition-all cursor-pointer"
                >
                  Prev
                </button>
                <button
                  disabled={page * 25 >= data.total}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-4 py-2 text-xs font-black uppercase tracking-wider rounded-xl border border-border/40 hover:bg-muted disabled:opacity-40 transition-all cursor-pointer"
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
