import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function ConfigPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-bold">Configuration</h2>
        <p className="text-sm text-muted-foreground">Loading…</p>
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-bold">Configuration</h2>
        <p className="text-sm text-destructive">Error loading configuration.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Configuration</h2>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Resolved Config</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
            {Object.entries(data.resolved).map(([key, value]) => (
              <div key={key}>
                <dt className="font-medium text-muted-foreground">{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {Object.keys(data.overrides).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Overrides</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
              {Object.entries(data.overrides).map(([key, value]) => (
                <div key={key}>
                  <dt className="font-medium text-muted-foreground">{key}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
