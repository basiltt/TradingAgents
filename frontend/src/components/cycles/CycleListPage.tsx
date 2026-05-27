/**
 * @module CycleListPage
 *
 * Paginated list view for all trading cycles managed by the execution engine.
 * Cycles are fetched from `GET /cycles` via {@link cyclesApi.list} and displayed
 * in a responsive layout: a full table on desktop and individual cards on mobile.
 *
 * The query refresh interval adapts to activity: 5 s when any cycle is active,
 * 30 s during idle periods to reduce unnecessary network traffic.
 */
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
  {
    label: string;
    variant: "default" | "secondary" | "destructive" | "outline";
    tone: "accent" | "success" | "warning" | "danger" | "neutral";
  }
> = {
  pending: { label: "Pending", variant: "outline", tone: "neutral" },
  placing_trades: { label: "Placing", variant: "default", tone: "accent" },
  running: { label: "Running", variant: "default", tone: "success" },
  stopping: { label: "Stopping", variant: "secondary", tone: "warning" },
  completed: { label: "Completed", variant: "secondary", tone: "neutral" },
  stopped: { label: "Stopped", variant: "outline", tone: "warning" },
  failed: { label: "Failed", variant: "destructive", tone: "danger" },
};

function cycleStatusTone(status: string) {
  return STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
}

function cycleStatusCopy(cycle: CycleResponse) {
  if (cycle.stop_reason) return cycle.stop_reason;
  if (cycle.status === "running") return "Execution is actively managing this cycle.";
  if (cycle.status === "placing_trades") return "Orders are being routed across approved setups.";
  if (cycle.status === "failed") return "Review the cycle detail for failed trade context.";
  if (cycle.completed_at) return `Completed ${formatDate(cycle.completed_at)}`;
  return `Opened ${formatDate(cycle.created_at)}`;
}

/**
 * Small toned metric pill used in cycle row and sidebar summary cells.
 *
 * @param props.label - Metric name shown as an uppercase eyebrow label.
 * @param props.value - Metric value rendered below the label.
 * @param props.tone - Color scheme variant controlling border/background. Defaults to `"neutral"`.
 * @returns A compact bordered pill JSX element.
 */
function MetricPill({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "accent" | "success" | "warning" | "danger" | "neutral" }) {
  const toneClass = {
    accent: "border-primary/20 bg-primary/10 text-primary",
    success: "border-[color:color-mix(in_oklch,var(--success)_44%,transparent)] bg-[color:color-mix(in_oklch,var(--success)_12%,transparent)] text-[var(--success)]",
    warning: "border-[color:color-mix(in_oklch,var(--warning)_44%,transparent)] bg-[color:color-mix(in_oklch,var(--warning)_12%,transparent)] text-[color:color-mix(in_oklch,var(--warning)_76%,var(--foreground))]",
    danger: "border-[color:color-mix(in_oklch,var(--destructive)_44%,transparent)] bg-[color:color-mix(in_oklch,var(--destructive)_12%,transparent)] text-destructive",
    neutral: "border-border/55 bg-card/55 text-foreground",
  }[tone];

  return (
    <div className={`rounded-[calc(var(--radius)*1.05)] border px-3 py-2 shadow-[var(--shadow-soft)] ${toneClass}`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-semibold tracking-[-0.03em]">{value}</p>
    </div>
  );
}

/**
 * Page component that lists all trading cycles with summary metrics.
 *
 * Responsibilities:
 * - Loads cycles from `GET /cycles` with offset-based pagination (20 per page).
 * - Auto-refreshes at 5 s when active cycles exist, 30 s otherwise.
 * - Displays a PageHeader with counts for active, completed, and failed cycles.
 * - Renders a desktop table (`hidden sm:flex`) and mobile card grid side by side.
 * - Shows an empty state CTA linking to scan history when no cycles exist.
 * - Provides offset pagination controls when `total > limit`.
 *
 * @returns The cycles list page JSX element, or loading/error states.
 *
 * @example
 * // Rendered by the router at the /cycles route
 * <CycleListPage />
 */
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
          eyebrow="Cycles"
          title="Cycles"
          description=""
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
        eyebrow="Cycles"
        title="Cycles"
        description=""
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCcw className="size-4" />
              Refresh
            </Button>
            <Link
              to="/scanner/history"
              className="touch-target inline-flex items-center justify-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-primary/25 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
            >
              <Waypoints className="size-4" />
              Start from scan history
            </Link>
          </div>
        }
        stats={[
          { label: "Visible cycles", value: String(items.length), tone: "accent" },
          { label: "Active", value: String(activeCount), tone: activeCount ? "success" : "neutral" },
          { label: "Completed", value: String(completedCount), tone: "neutral" },
          { label: "Failed", value: String(failedCount), tone: failedCount ? "danger" : "neutral" },
        ]}
      >
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
          <section className="grid gap-3 lg:grid-cols-3">
            <div className="surface-lift rounded-[calc(var(--radius)*1.45)] p-4 lg:col-span-2">
              <p className="section-eyebrow">Live routing overview</p>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.05em] text-foreground">Execution lanes stay readable at every breakpoint</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                The cycle monitor prioritizes failure context, routing status, and trade counts while preserving a compact desktop table and richer mobile cards.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              <MetricPill label="Refresh mode" value={activeCount ? "5s live" : "30s idle"} tone={activeCount ? "success" : "neutral"} />
              <MetricPill label="Throughput" value={`${items.reduce((sum, cycle) => sum + cycle.trades_placed, 0)} trades`} tone="accent" />
              <MetricPill label="Exceptions" value={String(items.reduce((sum, cycle) => sum + cycle.trades_failed, 0))} tone={failedCount ? "danger" : "neutral"} />
            </div>
          </section>

          <div className="grid gap-3 sm:hidden">
            {items.map((cycle) => {
              const config = cycleStatusTone(cycle.status);
              return (
                <Link
                  key={cycle.id}
                  to="/cycles/$cycleId"
                  params={{ cycleId: String(cycle.id) }}
                  className="block"
                >
                  <article className="glass-card rounded-[calc(var(--radius)*1.45)] border border-border/60 bg-card/72 p-4 shadow-[var(--shadow-card)]">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="section-eyebrow">Cycle</p>
                        <h3 className="mt-1 font-mono text-lg font-semibold tracking-tight text-foreground">
                          #{cycle.id}
                        </h3>
                      </div>
                      <Badge variant={config.variant}>{config.label}</Badge>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">{cycleStatusCopy(cycle)}</p>
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <MetricPill label="Placed" value={String(cycle.trades_placed)} tone="success" />
                      <MetricPill label="Failed" value={String(cycle.trades_failed)} tone={cycle.trades_failed > 0 ? "danger" : "neutral"} />
                    </div>
                    <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-3 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                      <span>{formatDate(cycle.created_at)}</span>
                      <span className="inline-flex items-center gap-1 text-primary">
                        View detail
                        <ArrowRight className="size-3.5" />
                      </span>
                    </div>
                  </article>
                </Link>
              );
            })}
          </div>

          <Card className="hidden sm:flex overflow-hidden">
            <CardContent className="w-full p-0">
              <div className="overflow-x-auto custom-scrollbar">
                <table className="w-full min-w-[62rem] text-sm" aria-label="Trading cycles">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/18 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      <th className="px-5 py-4 text-left">Cycle</th>
                      <th className="px-5 py-4 text-left">Status</th>
                      <th className="px-5 py-4 text-left">Execution notes</th>
                      <th className="px-5 py-4 text-left">Trades</th>
                      <th className="px-5 py-4 text-left">Created</th>
                      <th className="px-5 py-4 text-left">Completed</th>
                      <th className="px-5 py-4 text-right">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((cycle) => {
                      const config = cycleStatusTone(cycle.status);
                      return (
                        <tr
                          key={cycle.id}
                          className="border-b border-border/35 align-top transition-colors last:border-b-0 hover:bg-muted/18"
                        >
                          <td className="px-5 py-4">
                            <div className="space-y-2">
                              <p className="font-mono text-sm font-semibold text-foreground">#{cycle.id}</p>
                              <p className="text-xs text-muted-foreground">Auto-routed cycle execution bundle</p>
                            </div>
                          </td>
                          <td className="px-5 py-4">
                            <Badge variant={config.variant}>{config.label}</Badge>
                          </td>
                          <td className="px-5 py-4">
                            <p className="max-w-xs text-sm leading-6 text-muted-foreground">{cycleStatusCopy(cycle)}</p>
                          </td>
                          <td className="px-5 py-4">
                            <div className="flex flex-wrap gap-2">
                              <MetricPill label="Placed" value={String(cycle.trades_placed)} tone="success" />
                              <MetricPill label="Failed" value={String(cycle.trades_failed)} tone={cycle.trades_failed > 0 ? "danger" : "neutral"} />
                            </div>
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
            <div className="surface-lift flex flex-col gap-3 rounded-[calc(var(--radius)*1.35)] p-4 sm:flex-row sm:items-center sm:justify-between">
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
