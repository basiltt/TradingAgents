import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, RefreshCcw, Waypoints } from "lucide-react";
import { cyclesApi, type CycleResponse } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { formatDate, isActive } from "./utils";

const STATUS_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "Pending", variant: "outline" },
  placing_trades: { label: "Placing", variant: "default" },
  running: { label: "Running", variant: "default" },
  stopping: { label: "Stopping", variant: "secondary" },
  completed: { label: "Completed", variant: "secondary" },
  stopped: { label: "Stopped", variant: "outline" },
  failed: { label: "Failed", variant: "destructive" },
};

export function CycleListPage() {
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["cycles", offset, limit],
    queryFn: ({ signal }) => cyclesApi.list({ offset, limit }, signal),
    refetchInterval: (query) => {
      const hasActive = query.state.data?.items?.some((cycle) => isActive(cycle.status));
      return hasActive ? 5000 : 30000;
    },
  });

  const items: CycleResponse[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const activeCount = items.filter((cycle) => isActive(cycle.status)).length;
  const completedCount = items.filter((cycle) => cycle.status === "completed").length;
  const failedCount = items.filter((cycle) => cycle.status === "failed").length;

  if (isLoading) {
    return (
      <div className="space-y-5 pb-7">
        <Skeleton className="h-48 rounded-[calc(var(--radius)*2)]" />
        <Skeleton className="h-72 rounded-[calc(var(--radius)*1.8)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-5 pb-7">
        <PageHeader
          eyebrow="Automation cycles"
          title="Cycle orchestration dashboard"
          description="Trading cycles could not be loaded. Retry the surface without leaving the automation workspace."
          actions={
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCcw className="size-4" />
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Automation cycles"
        title="Cycle orchestration dashboard"
        description="Monitor automated trade batches, review execution states, and jump into the originating scan workflow from a responsive control surface."
        actions={
          <Link
            to="/scanner/history"
            className="touch-target inline-flex items-center justify-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-primary/25 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
          >
            <Waypoints className="size-4" />
            Start from scan history
          </Link>
        }
        stats={[
          { label: "Visible cycles", value: String(items.length), tone: "accent" },
          { label: "Active", value: String(activeCount), tone: activeCount ? "success" : "neutral" },
          { label: "Completed", value: String(completedCount), tone: "neutral" },
          { label: "Failed", value: String(failedCount), tone: failedCount ? "danger" : "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Auto-refresh for active cycles</Badge>
          <Badge variant="outline">Mobile card layout</Badge>
          <Badge variant="outline">Detail drilldown ready</Badge>
        </div>
      </PageHeader>

      {items.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-4 p-6 text-center sm:p-8">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <Waypoints className="size-5.5" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-tight">No trading cycles yet</h2>
              <p className="max-w-xl text-sm text-muted-foreground">
                Launch a new cycle from scan history to track progress, failures, and managed trade
                batches from this dashboard.
              </p>
            </div>
            <Link
              to="/scanner/history"
              className="touch-target inline-flex items-center justify-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-border/70 bg-card/75 px-3.5 py-2.5 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)]"
            >
              Open scan history
              <ArrowRight className="size-4" />
            </Link>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:hidden">
            {items.map((cycle) => {
              const config = STATUS_CONFIG[cycle.status] ?? STATUS_CONFIG.pending;
              return (
                <Link
                  key={cycle.id}
                  to="/cycles/$cycleId"
                  params={{ cycleId: String(cycle.id) }}
                  className="block"
                >
                  <Card size="sm" className="h-full">
                    <CardContent className="space-y-4 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="section-eyebrow">Cycle</p>
                          <h3 className="font-mono text-lg font-semibold tracking-tight">
                            #{cycle.id}
                          </h3>
                        </div>
                        <Badge variant={config.variant}>{config.label}</Badge>
                      </div>
                      <div className="grid gap-2 text-sm text-muted-foreground">
                        <p>
                          {cycle.trades_placed} placed
                          {cycle.trades_failed > 0 ? `, ${cycle.trades_failed} failed` : ""}
                        </p>
                        <p>{formatDate(cycle.created_at)}</p>
                        {cycle.stop_reason ? (
                          <p className="text-amber-500">Reason: {cycle.stop_reason}</p>
                        ) : null}
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>

          <Card className="hidden sm:flex">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[52rem] text-sm" aria-label="Trading cycles">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/18 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      <th className="px-5 py-4 text-left">Cycle</th>
                      <th className="px-5 py-4 text-left">Status</th>
                      <th className="px-5 py-4 text-left">Trades</th>
                      <th className="px-5 py-4 text-left">Created</th>
                      <th className="px-5 py-4 text-left">Completed</th>
                      <th className="px-5 py-4 text-right">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((cycle) => {
                      const config = STATUS_CONFIG[cycle.status] ?? STATUS_CONFIG.pending;
                      return (
                        <tr
                          key={cycle.id}
                          className="border-b border-border/35 transition-colors last:border-b-0 hover:bg-muted/18"
                        >
                          <td className="px-5 py-4">
                            <div className="space-y-1">
                              <p className="font-mono text-sm font-semibold">#{cycle.id}</p>
                              {cycle.stop_reason ? (
                                <p className="text-xs text-amber-500">{cycle.stop_reason}</p>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-5 py-4">
                            <Badge variant={config.variant}>{config.label}</Badge>
                          </td>
                          <td className="px-5 py-4">
                            <span className="font-medium text-foreground">
                              {cycle.trades_placed} placed
                            </span>
                            {cycle.trades_failed > 0 ? (
                              <span className="ml-2 text-destructive">
                                {cycle.trades_failed} failed
                              </span>
                            ) : null}
                          </td>
                          <td className="px-5 py-4 text-muted-foreground">
                            {formatDate(cycle.created_at)}
                          </td>
                          <td className="px-5 py-4 text-muted-foreground">
                            {formatDate(cycle.completed_at)}
                          </td>
                          <td className="px-5 py-4 text-right">
                            <Link to="/cycles/$cycleId" params={{ cycleId: String(cycle.id) }}>
                              <Button variant="ghost" size="sm">
                                View
                                <ArrowRight className="size-4" />
                              </Button>
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {total > limit ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {offset + 1}-{Math.min(offset + limit, total)} of {total}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  disabled={offset === 0}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setOffset(offset + limit)}
                  disabled={offset + limit >= total}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
