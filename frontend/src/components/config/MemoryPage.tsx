import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Database, RefreshCw, TriangleAlert } from "lucide-react";
import { apiClient } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function MemoryPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["memory", page],
    queryFn: ({ signal }) => apiClient.getMemory({ page, limit: PAGE_SIZE }, signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        eyebrow="Agent Memory"
        title="Historical decisions, confidence records, and long-term reasoning context."
        description="Use the redesigned memory log to review what the agents decided, how confident they were, and whether each record resolved cleanly."
        stats={[
          { label: "Loaded page", value: String(page), tone: "accent" },
          { label: "Records", value: String(data?.total ?? 0), tone: "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Paginated browsing</Badge>
          <Badge variant="outline">Readable decision cards</Badge>
          <Badge variant="outline">Mobile-first spacing</Badge>
        </div>
      </PageHeader>

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index} className="min-h-28 animate-pulse" />
          ))}
        </div>
      ) : isError || !data ? (
        <Card className="border-destructive/20 bg-destructive/6">
          <CardContent className="flex flex-col gap-4 p-6 sm:flex-row sm:items-center">
            <div className="flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.4)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <TriangleAlert className="size-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-destructive">
                Memory service unavailable
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The backend did not return the memory log. Verify the API runtime and reload
                the page.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : data.items.length === 0 ? (
        <Card>
          <CardContent className="grid gap-5 p-8 md:grid-cols-[auto_minmax(0,1fr)] md:items-center">
            <div className="gradient-primary flex size-14 items-center justify-center rounded-[calc(var(--radius)*1.6)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <Database className="size-6" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">No records yet</p>
              <h2 className="text-2xl font-semibold tracking-tight">The memory log is still empty.</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Run one or more analyses to generate long-term entries for decisions,
                reasoning summaries, and confidence outcomes.
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
                  <CardHeader className="gap-4">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="flex min-w-0 items-start gap-4">
                        <div className="flex size-12 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.4)] bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
                          <BrainCircuit className="size-5" />
                        </div>
                        <div className="min-w-0 space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <CardTitle className="font-mono text-xl tracking-[0.04em]">
                              {entry.ticker}
                            </CardTitle>
                            <Badge variant="outline">{entry.date}</Badge>
                            <span
                              className={cn(
                                "inline-flex min-h-6 items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
                                decisionTone,
                              )}
                            >
                              {entry.decision}
                            </span>
                          </div>
                          {entry.reasoning ? (
                            <CardDescription className="max-w-3xl text-sm leading-6">
                              {entry.reasoning}
                            </CardDescription>
                          ) : (
                            <CardDescription>No reasoning snapshot was stored for this entry.</CardDescription>
                          )}
                        </div>
                      </div>

                      <div className="grid min-w-[12rem] gap-2 sm:grid-cols-2 lg:grid-cols-1">
                        <StatPill label="Confidence" value={entry.confidence} />
                        <StatPill label="Status" value={entry.status} />
                      </div>
                    </div>
                  </CardHeader>
                </Card>
              );
            })}
          </div>

          {data.total > PAGE_SIZE && (
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
                    type="button"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => value - 1)}
                    className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/75 px-4 py-3 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)] disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={page * PAGE_SIZE >= data.total}
                    onClick={() => setPage((value) => value + 1)}
                    className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-primary/20 bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)] disabled:opacity-40"
                  >
                    <RefreshCw className="mr-2 size-4" />
                    Next page
                  </button>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-muted/20 px-4 py-3 shadow-[var(--shadow-soft)]">
      <p className="section-eyebrow">{label}</p>
      <p className="mt-2 text-sm font-semibold tracking-tight text-foreground">{value}</p>
    </div>
  );
}
