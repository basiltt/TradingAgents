import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const DECISION_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  buy: "default",
  sell: "destructive",
  hold: "secondary",
};

export function MemoryPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["memory", page],
    queryFn: ({ signal }) => apiClient.getMemory({ page, limit: 25 }, signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Memory</h1>
        <p className="text-muted-foreground mt-1">
          Browse past trading decisions and agent reasoning.
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-20 w-full rounded-xl" />
          ))}
        </div>
      ) : isError || !data ? (
        <Card className="border-destructive/50">
          <CardContent className="flex items-center gap-3 py-6">
            <div className="w-10 h-10 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="font-medium text-destructive">Error loading memory</p>
              <p className="text-sm text-muted-foreground">Could not connect to the API. Is the backend running?</p>
            </div>
          </CardContent>
        </Card>
      ) : data.items.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold mb-1">No memories yet</h3>
            <p className="text-sm text-muted-foreground max-w-sm">
              Run an analysis to populate the agent memory log.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="space-y-2">
            {data.items.map((entry, i) => (
              <Card key={`${entry.ticker}-${entry.date}-${i}`} className="hover:shadow-md transition-shadow">
                <CardContent className="py-3.5 px-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center shrink-0">
                        <span className="font-mono font-bold text-sm">{entry.ticker.slice(0, 4)}</span>
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold font-mono">{entry.ticker}</span>
                          <span className="text-xs text-muted-foreground">{entry.date}</span>
                          <Badge variant={DECISION_COLORS[entry.decision.toLowerCase()] ?? "outline"} className="capitalize">
                            {entry.decision}
                          </Badge>
                          <Badge variant="outline" className="text-xs">{entry.confidence}</Badge>
                        </div>
                        {entry.reasoning && (
                          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{entry.reasoning}</p>
                        )}
                      </div>
                    </div>
                    <Badge variant={entry.status === "resolved" ? "secondary" : "outline"} className="shrink-0 text-xs capitalize">
                      {entry.status}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {data.total > 25 && (
            <div className="flex items-center justify-between pt-2">
              <p className="text-sm text-muted-foreground">
                Page {data.page} of {Math.ceil(data.total / 25)} ({data.total} entries)
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" disabled={page * 25 >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
