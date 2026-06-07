/**
 * MCPSweepBrowser — lists persisted optimizer sweeps and lets the operator open
 * a sweep's results, re-ranked server-side by an alternate objective (FR-040).
 * The agent launches sweeps over the wire; this is the human's window into them.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FlaskConical, Loader2 } from "lucide-react";

import { mcpApi } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { OBJECTIVE_OPTIONS } from "./sweepConstants";
import type { MCPSweepJob } from "./types";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  running: "default",
  completed: "secondary",
  cancelled: "outline",
  failed: "destructive",
  interrupted: "outline",
  queued: "outline",
};

export function MCPSweepBrowser() {
  const sweepsQ = useQuery({
    queryKey: ["mcp", "sweeps"],
    queryFn: ({ signal }) => mcpApi.listSweeps(50, signal),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const sweeps = sweepsQ.data?.items ?? [];

  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] bg-[var(--neu-accent)]/12 text-[var(--neu-accent)]">
          <FlaskConical className="size-5" />
        </div>
        <div>
          <h3 className="text-base font-bold tracking-tight text-[var(--neu-text-strong)]">Optimizer sweeps</h3>
          <p className="text-xs text-[var(--neu-text-muted)]">Async parameter sweeps the agent ran. Open one to inspect + re-rank its results.</p>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {sweepsQ.isLoading ? (
          <div className="flex justify-center py-8 text-[var(--neu-text-muted)]"><Loader2 className="size-5 animate-spin" /></div>
        ) : sweeps.length === 0 ? (
          <p className="rounded-[var(--neu-radius-md)] border border-dashed border-[var(--neu-stroke-soft)] py-8 text-center text-xs text-[var(--neu-text-muted)]">
            No sweeps yet. When the agent runs an optimization, it appears here.
          </p>
        ) : (
          sweeps.map((s) => <SweepRow key={s.id} sweep={s} />)
        )}
      </div>
    </div>
  );
}

function SweepRow({ sweep }: { sweep: MCPSweepJob }) {
  const [open, setOpen] = useState(false);
  const [objective, setObjective] = useState<string>(sweep.objective_metric);

  const resultsQ = useQuery({
    queryKey: ["mcp", "sweep-results", sweep.id, objective],
    queryFn: ({ signal }) => mcpApi.getSweepResults(sweep.id, objective, signal),
    enabled: open,
    staleTime: 10_000,
  });
  const rows = resultsQ.data?.items ?? [];
  const pct = sweep.total_combos ? Math.round((sweep.completed_combos / sweep.total_combos) * 100) : 0;

  return (
    <div className="overflow-hidden rounded-[var(--neu-radius-md)] border border-[var(--neu-stroke-soft)]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 bg-[var(--neu-surface-flat)] px-3.5 py-2.5 text-left transition-colors hover:bg-[var(--neu-surface-inset)] neu-focus-ring"
      >
        <div className="flex items-center gap-2.5">
          <ChevronDown className={cn("size-4 text-[var(--neu-text-muted)] transition-transform", !open && "-rotate-90")} />
          <code className="font-mono text-xs font-semibold text-[var(--neu-text-strong)]">{sweep.id.slice(0, 8)}…</code>
          <Badge variant={STATUS_VARIANT[sweep.status] ?? "secondary"} className="h-5 px-1.5 text-[10px] uppercase">
            {sweep.status}
          </Badge>
        </div>
        <span className="text-[11px] text-[var(--neu-text-muted)]">
          {sweep.completed_combos}/{sweep.total_combos} ({pct}%) · {sweep.objective_metric}
        </span>
      </button>

      {open ? (
        <div className="bg-[var(--neu-surface-raised)] px-3.5 py-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Re-rank by</span>
            <select
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              className="rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-inset)] px-2 py-1 text-xs text-[var(--neu-text-strong)] neu-focus-ring"
            >
              {OBJECTIVE_OPTIONS.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
          {resultsQ.isLoading ? (
            <div className="flex justify-center py-4 text-[var(--neu-text-muted)]"><Loader2 className="size-4 animate-spin" /></div>
          ) : rows.length === 0 ? (
            <p className="py-2 text-[11px] text-[var(--neu-text-muted)]">No results yet.</p>
          ) : (
            <div className="space-y-1">
              {rows.slice(0, 10).map((r, i) => (
                <div key={r.config_hash} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="font-mono text-[var(--neu-text-muted)]">#{i + 1}</span>
                  <code className="flex-1 truncate font-mono text-[var(--neu-text-strong)]">
                    {JSON.stringify(r.config)}
                  </code>
                  <span className="font-semibold text-[var(--neu-accent)]">
                    {objective}: {fmtMetric(r.metrics, objective)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function fmtMetric(metrics: Record<string, unknown>, objective: string): string {
  // mirror the backend alias resolution for the headline display
  const aliases: Record<string, string[]> = {
    total_return: ["total_return", "net_profit_pct", "cagr"],
    max_drawdown: ["max_drawdown", "max_dd_pct"],
  };
  for (const k of aliases[objective] ?? [objective]) {
    const v = metrics[k];
    if (typeof v === "number") return v.toFixed(2);
  }
  return "—";
}
