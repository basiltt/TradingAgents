import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Loader2,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CloseExecution } from "@/api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
}

export function CloseHistoryDialog({ open, onOpenChange, accountId, accountLabel }: Props) {
  const [executions, setExecutions] = useState<CloseExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const limit = 10;

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setPage(1);
      setExecutions([]);
      setTotal(0);
    }
    onOpenChange(nextOpen);
  };

  const changePage = (newPage: number) => {
    setPage(newPage);
    setLoading(true);
  };

  useEffect(() => {
    if (!open) {
      return;
    }
    const controller = new AbortController();
    accountsApi.getCloseExecutions(accountId, page, limit, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setExecutions(res.items);
          setTotal(res.total);
        }
      })
      .catch(() => { if (!controller.signal.aborted) toast.error("Failed to load history"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, accountId, page]);

  if (!open) return null;

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const successful = executions.filter((execution) => execution.failed_count === 0).length;
  const partial = executions.filter((execution) => execution.failed_count > 0 && execution.closed_count > 0).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4" role="dialog" aria-modal="true" aria-label="Close history" onClick={() => handleOpenChange(false)}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,oklch(0.64_0.12_206_/_0.18),transparent_36%),rgba(2,6,23,0.78)] backdrop-blur-md" />
      <div
        className="glass-card relative flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-[calc(var(--radius)*2)] border border-border/70 bg-card/90 shadow-[0_44px_140px_-56px_rgba(0,0,0,0.82)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--primary)_42%,white),transparent)]" />

        <div className="border-b border-border/55 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-4">
              <div className="gradient-primary flex size-14 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.35)] text-primary-foreground shadow-[var(--shadow-accent)]">
                <ShieldCheck className="size-6" />
              </div>
              <div>
                <p className="section-eyebrow">Execution audit trail</p>
                <h2 className="mt-1 text-xl font-semibold tracking-[-0.04em] text-foreground sm:text-[1.7rem]">Close history</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Review every manual and rule-driven liquidation event recorded for <span className="font-semibold text-foreground">{accountLabel}</span>.
                </p>
              </div>
            </div>
            <Button type="button" variant="ghost" size="icon-sm" onClick={() => handleOpenChange(false)} aria-label="Close history panel">
              <X className="size-4" />
            </Button>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Entries", value: String(total), tone: "accent" },
              { label: "Fully closed", value: String(successful), tone: successful ? "success" : "neutral" },
              { label: "Partial outcomes", value: String(partial), tone: partial ? "warning" : "neutral" },
            ].map((item) => (
              <div key={item.label} data-tone={item.tone} className="page-header-stat rounded-[calc(var(--radius)*1.1)] border px-4 py-3">
                <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">{item.label}</div>
                <div className="mt-2 text-lg font-semibold tracking-[-0.04em] text-foreground">{item.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          {loading ? (
            <div className="flex min-h-[18rem] items-center justify-center">
              <div className="surface-lift flex items-center gap-3 rounded-[calc(var(--radius)*1.25)] px-5 py-4 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading execution history...
              </div>
            </div>
          ) : executions.length === 0 ? (
            <div className="flex min-h-[18rem] flex-col items-center justify-center rounded-[calc(var(--radius)*1.6)] border border-dashed border-border/60 bg-background/35 px-6 text-center">
              <div className="surface-lift flex size-16 items-center justify-center rounded-[calc(var(--radius)*1.4)] border border-border/60">
                <Sparkles className="size-6 text-primary" />
              </div>
              <h3 className="mt-5 text-lg font-semibold tracking-tight text-foreground">No close events captured yet</h3>
              <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                Executions appear here after positions are flattened manually or through conditional close rules.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {executions.map((exec) => <ExecutionRow key={exec.id} execution={exec} />)}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3 border-t border-border/55 px-5 py-4 sm:px-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            {total > limit ? (
              <div className="flex items-center gap-2">
                <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => changePage(page - 1)}>
                  <ChevronLeft className="size-4" />
                  Previous
                </Button>
                <Button type="button" variant="outline" size="sm" disabled={page >= totalPages} onClick={() => changePage(page + 1)}>
                  Next
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            ) : null}
            <Button type="button" variant="ghost" onClick={() => handleOpenChange(false)}>
              Done
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ExecutionRow({ execution }: { execution: CloseExecution }) {
  const allSuccess = execution.failed_count === 0;
  const allFailed = execution.closed_count === 0;
  const date = new Date(execution.executed_at);

  const statusMeta = allSuccess
    ? {
        icon: CheckCircle2,
        tone: "text-success",
        chip: "border-success/20 bg-success/12 text-success",
        label: "Successful close",
      }
    : allFailed
      ? {
          icon: XCircle,
          tone: "text-destructive",
          chip: "border-destructive/20 bg-destructive/10 text-destructive",
          label: "Failed close",
        }
      : {
          icon: Clock3,
          tone: "text-warning",
          chip: "border-warning/20 bg-warning/12 text-warning",
          label: "Partial outcome",
        };

  const Icon = statusMeta.icon;

  return (
    <article className="glass-card rounded-[calc(var(--radius)*1.35)] border p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <div className="surface-lift flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.05)] border border-border/60">
              <Icon className={cn("size-5", statusMeta.tone)} />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold tracking-[-0.03em] text-foreground">{statusMeta.label}</h3>
                <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", statusMeta.chip)}>
                  {execution.closed_count}/{execution.total_positions} closed
                </span>
                <span
                  className={cn(
                    "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
                    execution.trigger_source === "rule"
                      ? "border-primary/20 bg-primary/12 text-primary"
                      : "border-border/60 bg-background/60 text-muted-foreground",
                  )}
                >
                  {execution.trigger_source === "rule" ? "Rule trigger" : "Manual trigger"}
                </span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {date.toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Closed", value: String(execution.closed_count), tone: "success" },
              { label: "Failed", value: String(execution.failed_count), tone: execution.failed_count ? "danger" : "neutral" },
              { label: "Requested", value: String(execution.total_positions), tone: "accent" },
            ].map((item) => (
              <div key={item.label} data-tone={item.tone} className="page-header-stat rounded-[calc(var(--radius)*1.05)] border px-3.5 py-3">
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{item.label}</div>
                <div className="mt-2 text-base font-semibold tracking-[-0.03em] text-foreground">{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {execution.results.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {execution.results.slice(0, 12).map((result, index) => (
            <span
              key={`${result.symbol}-${index}`}
              className={cn(
                "inline-flex items-center rounded-full border px-3 py-1.5 text-[11px] font-semibold tracking-[0.14em] uppercase",
                result.status === "closed"
                  ? "border-success/20 bg-success/12 text-success"
                  : "border-destructive/20 bg-destructive/10 text-destructive",
              )}
              title={result.error || undefined}
            >
              {result.symbol}
            </span>
          ))}
          {execution.results.length > 12 ? (
            <span className="inline-flex items-center rounded-full border border-border/60 bg-background/55 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              +{execution.results.length - 12} more
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
