import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { backtestApi } from "@/api/client";
import type { BacktestRun } from "./types";
import { formatUsd, formatPct, formatRatio, formatInt, pnlColorClass, TH_CLASS, TH_CLASS_RIGHT } from "./format";
import { EquityOverlayChart, OVERLAY_COLORS, type EquityDataset } from "./EquityOverlayChart";
import { MAX_COMPARE_RUNS } from "./comparisonBasket";
import { cn } from "@/lib/utils";

export interface BacktestComparePageProps {
  runIds: string[];
  onBack?: () => void;
}

interface CompareRow {
  label: string;
  /** Single source of truth for the metric value (drives text, color, and best-run). */
  value: (r: BacktestRun) => number | null;
  format: (v: number | null) => string;
  colorize?: boolean;
  /** "high" = larger is better, "low" = smaller is better; omit for non-ranked rows. */
  better?: "high" | "low";
}

const metricsOf = (r: BacktestRun) => r.results?.metrics;

const ROWS: CompareRow[] = [
  {
    label: "Net Profit",
    value: (r) => metricsOf(r)?.net_profit ?? null,
    format: (v) => formatUsd(v, { sign: true }),
    colorize: true,
    better: "high",
  },
  {
    label: "Return %",
    value: (r) => metricsOf(r)?.net_profit_pct ?? null,
    format: (v) => formatPct(v, { sign: true }),
    colorize: true,
    better: "high",
  },
  {
    label: "Win Rate",
    value: (r) => metricsOf(r)?.win_rate ?? null,
    format: (v) => formatPct(v),
    better: "high",
  },
  {
    label: "Profit Factor",
    value: (r) => metricsOf(r)?.profit_factor ?? null,
    format: (v) => formatRatio(v, { infinite: true }),
    better: "high",
  },
  {
    label: "Sharpe",
    value: (r) => metricsOf(r)?.sharpe ?? null,
    format: (v) => formatRatio(v),
    better: "high",
  },
  {
    label: "Max Drawdown",
    value: (r) => metricsOf(r)?.max_dd_pct ?? null,
    format: (v) => formatPct(v),
    better: "low",
  },
  {
    label: "Total Trades",
    value: (r) => metricsOf(r)?.total_trades ?? null,
    format: (v) => formatInt(v),
  },
  {
    label: "CAGR",
    value: (r) => metricsOf(r)?.cagr ?? null,
    format: (v) => formatPct(v, { sign: true }),
    colorize: true,
    better: "high",
  },
];

/** Index of the best run for a row, or -1 if not comparable. */
export function bestRunIndex(
  runs: BacktestRun[],
  rawValue: ((r: BacktestRun) => number | null) | undefined,
  better: "high" | "low" | undefined,
): number {
  if (!rawValue || !better) return -1;
  let bestIdx = -1;
  let bestVal: number | null = null;
  runs.forEach((r, i) => {
    const v = rawValue(r);
    if (v == null || !Number.isFinite(v)) return;
    if (bestVal == null || (better === "high" ? v > bestVal : v < bestVal)) {
      bestVal = v;
      bestIdx = i;
    }
  });
  return bestIdx;
}

export function BacktestComparePage({ runIds, onBack }: BacktestComparePageProps) {
  // A hand-edited URL could carry more than the supported number of runs; clamp
  // before hitting the API (which would 422) so the UI stays well-defined.
  const cappedIds = runIds.slice(0, MAX_COMPARE_RUNS);
  const { data, isLoading, error } = useQuery({
    queryKey: ["backtest", "compare", ...cappedIds],
    queryFn: ({ signal }) => backtestApi.compare(cappedIds, signal),
    enabled: cappedIds.length >= 2,
  });

  if (cappedIds.length < 2) {
    return <p className="py-10 text-center text-sm text-[var(--neu-text-muted)]">Select at least two runs to compare.</p>;
  }

  if (isLoading) {
    return <Skeleton className="h-64 w-full" data-testid="compare-loading" />;
  }

  if (error || !data) {
    return (
      <p className="py-10 text-center text-sm text-[var(--neu-danger)]">
        {error instanceof Error ? error.message : "Failed to load comparison."}
      </p>
    );
  }

  const runs = data.runs;

  const overlayDatasets: EquityDataset[] = runs.map((r, i) => ({
    label: `Run ${i + 1} (${r.id.slice(0, 8)})`,
    color: OVERLAY_COLORS[i % OVERLAY_COLORS.length],
    data: r.results?.equity_curve ?? [],
  }));
  const hasEquity = overlayDatasets.some((d) => d.data.length > 0);

  return (
    <div className="flex flex-col gap-4" data-testid="backtest-compare-page">
      <div className="flex items-center gap-3">
        {onBack ? (
          <Button variant="ghost" size="sm" onClick={onBack}>
            ← Back
          </Button>
        ) : null}
        <h1 className="text-xl font-bold tracking-tight text-[var(--neu-text-strong)]">
          Compare Backtests
        </h1>
      </div>

      {hasEquity ? (
        <Card>
          <CardHeader>
            <CardTitle>Equity Curves</CardTitle>
          </CardHeader>
          <CardContent>
            <EquityOverlayChart datasets={overlayDatasets} />
          </CardContent>
        </Card>
      ) : null}

      <div className="overflow-x-auto rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/60">
        <table className="w-full border-collapse text-sm" data-testid="compare-table">
          <caption className="sr-only">Backtest comparison</caption>
          <thead>
            <tr className="bg-[color:var(--neu-surface-inset)]/40 text-left">
              <th scope="col" className={cn("px-3 py-2", TH_CLASS)}>Metric</th>
              {runs.map((r, i) => (
                <th key={r.id} scope="col" className={cn("px-3 py-2", TH_CLASS_RIGHT)}>
                  Run {i + 1}
                  <span className="block font-normal normal-case text-[0.66rem] text-[var(--neu-text-soft)]">
                    {r.id.slice(0, 8)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const best = bestRunIndex(runs, row.value, row.better);
              return (
                <tr key={row.label} className="border-t border-[color:var(--neu-stroke-soft)]/40">
                  <th scope="row" className="px-3 py-2 text-left text-[0.8rem] font-medium text-[var(--neu-text-muted)]">
                    {row.label}
                  </th>
                  {runs.map((r, i) => {
                    const raw = row.value(r);
                    return (
                      <td
                        key={r.id}
                        className={cn(
                          "px-3 py-2 text-right tabular-nums",
                          row.colorize ? pnlColorClass(raw) : "text-[var(--neu-text-strong)]",
                          i === best ? "font-bold" : "",
                        )}
                        data-best={i === best ? "true" : undefined}
                      >
                        {row.format(raw)}
                        {i === best ? (
                          <>
                            <span aria-hidden className="ml-1 text-[var(--neu-accent)]">★</span>
                            <span className="sr-only"> (best)</span>
                          </>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
