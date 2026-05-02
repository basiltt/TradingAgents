import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export function HistoryList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analyses"],
    queryFn: ({ signal }) => apiClient.listAnalyses(undefined, signal),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-bold">History</h2>
        <p className="text-sm text-muted-foreground">Loading…</p>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-bold">History</h2>
        <p className="text-sm text-destructive">Error loading analysis history.</p>
      </div>
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">History</h2>
      {items.length === 0 ? (
        <p className="text-muted-foreground">No analyses found.</p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Link
              key={item.run_id}
              to="/analysis/$runId"
              params={{ runId: item.run_id }}
            >
              <Card className="hover:border-primary transition-colors cursor-pointer">
                <CardContent className="py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-medium">{item.ticker}</span>
                    <span className="text-sm text-muted-foreground">
                      {item.analysis_date}
                    </span>
                  </div>
                  <Badge
                    variant={
                      item.status === "completed"
                        ? "secondary"
                        : item.status === "failed"
                          ? "destructive"
                          : "default"
                    }
                  >
                    {item.status}
                  </Badge>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
