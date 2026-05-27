/**
 * @module MemoryPage
 *
 * Paginated viewer for the AI agent's long-term memory log.
 * Each memory entry captures the agent's ticker, decision (buy/sell/hold),
 * reasoning summary, confidence score, and outcome status for a given date.
 *
 * Data is fetched from the backend via {@link apiClient.getMemory} with
 * server-side pagination at {@link PAGE_SIZE} records per page.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Database, RefreshCw, TriangleAlert } from "lucide-react";
import { apiClient } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

/**
 * Page component that browses the AI agent's persisted memory entries.
 *
 * Renders a paginated list of memory records. Each card shows:
 * - Ticker symbol and analysis date.
 * - Decision badge color-coded by direction (buy = green, sell = red, hold = amber).
 * - Reasoning summary from the agent's context window at decision time.
 * - Confidence score and current outcome status via {@link StatPill}.
 *
 * Empty and error states are handled with appropriate feedback cards.
 * Pagination controls appear only when `total > PAGE_SIZE`.
 *
 * @returns The agent memory page JSX element.
 *
 * @example
 * // Rendered by the router at the /memory route
 * <MemoryPage />
 */
export function MemoryPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["memory", page],
    queryFn: ({ signal }) => apiClient.getMemory({ page, limit: PAGE_SIZE }, signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Memory"
        title="Agent Memory"
        description=""
        stats={[
          { label: "Loaded page", value: String(page), tone: "accent" },
          { label: "Records", value: String(data?.total ?? 0), tone: "neutral" },
        ]}
      >
      </PageHeader>

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index} className="min-h-32 animate-pulse" />
          ))}
        </div>
      ) : isError || !data ? (
        <Card className="border-destructive/20 bg-destructive/6">
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <TriangleAlert className="size-4.5" />
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight text-destructive">Memory service unavailable</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The backend did not return the memory log. Verify the API runtime and reload the page.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : data.items.length === 0 ? (
        <Card>
          <CardContent className="grid gap-4 p-6 md:grid-cols-[auto_minmax(0,1fr)] md:items-center">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <Database className="size-5.5" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">No records yet</p>
              <h2 className="text-xl font-semibold tracking-tight">The memory log is still empty.</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Run one or more analyses to generate long-term entries for decisions, reasoning summaries, and confidence outcomes.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4">
            {data.items.map((entry, index) => {
              const decision = entry.decision.toLowerCase();
              const decisionTone =
                decision === "buy" || decision === "long"
                  ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-500"
                  : decision === "sell" || decision === "short"
                    ? "border-destructive/20 bg-destructive/10 text-destructive"
                    : "border-warning/20 bg-warning/12 text-warning";

              return (
                <Card key={`${entry.ticker}-${entry.date}-${index}`}>
                  <CardContent className="p-5">
                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(15rem,0.7fr)] xl:items-start">
                      <div className="flex min-w-0 items-start gap-4">
                        <div className="gradient-primary flex size-11 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.3)] text-primary-foreground shadow-[var(--shadow-accent)]">
                          <BrainCircuit className="size-4.5" />
                        </div>
                        <div className="min-w-0 space-y-3">
                          <div className="flex flex-wrap items-center gap-2.5">
                            <CardTitle className="font-mono text-xl tracking-[0.08em]">{entry.ticker}</CardTitle>
                            <Badge variant="outline">{entry.date}</Badge>
                            <span
                              className={cn(
                                "inline-flex min-h-7 items-center rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
                                decisionTone,
                              )}
                            >
                              {entry.decision}
                            </span>
                          </div>
                          <div className="rounded-[calc(var(--radius)*1.2)] border border-border/55 bg-card/52 p-4 shadow-[var(--shadow-soft)]">
                            <p className="section-eyebrow">Reasoning summary</p>
                            {entry.reasoning ? (
                              <CardDescription className="mt-3 max-w-4xl text-sm leading-7 text-foreground/82">
                                {entry.reasoning}
                              </CardDescription>
                            ) : (
                              <CardDescription className="mt-3">No reasoning snapshot was stored for this entry.</CardDescription>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                        <StatPill label="Confidence" value={entry.confidence} />
                        <StatPill label="Status" value={entry.status} />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {data.total > PAGE_SIZE ? (
            <Card>
              <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="section-eyebrow">Pagination</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Showing page {data.page} of {Math.ceil(data.total / PAGE_SIZE)} from {data.total} stored records.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    id="memory-previous-page"
                    type="button"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => value - 1)}
                    className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/75 px-4 py-3 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)] hover:border-primary/18 disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    id="memory-next-page"
                    type="button"
                    disabled={page * PAGE_SIZE >= data.total}
                    onClick={() => setPage((value) => value + 1)}
                    className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-primary/20 bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)] hover:brightness-110 disabled:opacity-40"
                  >
                    <RefreshCw className="mr-2 size-4" />
                    Next page
                  </button>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}

/**
 * Small labeled metric pill used inside each memory entry card.
 *
 * @param props.label - Metric name displayed as an eyebrow label.
 * @param props.value - Metric value rendered in bold below the label.
 * @returns A styled pill card JSX element.
 */
function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/58 px-4 py-3 shadow-[var(--shadow-soft)]">
      <p className="section-eyebrow">{label}</p>
      <p className="mt-2 text-sm font-semibold tracking-tight text-foreground">{value}</p>
    </div>
  );
}
