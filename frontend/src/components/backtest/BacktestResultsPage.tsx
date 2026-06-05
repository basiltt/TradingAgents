import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { backtestApi } from "@/api/client";
import { useBacktestPolling } from "@/hooks/useBacktestPolling";
import { isTerminalStatus } from "./types";
import { BacktestStatusBadge } from "./BacktestStatusBadge";
import { MetricsGrid } from "./MetricsGrid";
import { EquityCurveChart } from "./EquityCurveChart";
import { TradeListTable } from "./TradeListTable";
import { BacktestAnalysisTab } from "./BacktestAnalysisTab";
import { addToBasket, isInBasket, MAX_BASKET, getBasket } from "./comparisonBasket";
import { formatUsd, formatPct, formatRatio } from "./format";

export interface BacktestResultsPageProps {
  runId: string;
  onBack?: () => void;
  /** Re-run this config (Retry on failed / Re-run on cancelled). Receives the run's config. */
  onRetry?: (config: Record<string, unknown>) => void;
  /** Navigate to the comparison view (after adding to the basket). */
  onCompare?: (runIds: string[]) => void;
}

/** Sticky strip of the 4 headline metrics shown above the tabs. */
function HeroMetrics({
  netProfit,
  netProfitPct,
  winRate,
  profitFactor,
  maxDdPct,
}: {
  netProfit: number;
  netProfitPct: number | null;
  winRate: number | null;
  profitFactor: number | null;
  maxDdPct: number;
}) {
  const cls = netProfit >= 0 ? "text-emerald-500" : "text-rose-500";
  const tiles = [
    { label: "Net Profit", value: formatUsd(netProfit, { sign: true }), sub: formatPct(netProfitPct, { sign: true }), color: cls },
    { label: "Win Rate", value: formatPct(winRate) },
    { label: "Profit Factor", value: formatRatio(profitFactor, { infinite: true }) },
    { label: "Max Drawdown", value: formatPct(maxDdPct), color: "text-rose-500" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="hero-metrics">
      {tiles.map((t) => (
        <div key={t.label} className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] px-4 py-3">
          <p className="text-[0.68rem] font-semibold uppercase tracking-wide text-[var(--neu-text-muted)]">{t.label}</p>
          <p className={`mt-1 text-lg font-bold tabular-nums ${t.color ?? "text-[var(--neu-text-strong)]"}`}>{t.value}</p>
          {t.sub ? <p className="text-[0.7rem] text-[var(--neu-text-muted)]">{t.sub}</p> : null}
        </div>
      ))}
    </div>
  );
}

/** Trades fetched into the table at once. The backend reports `total`, so we can
 * warn the user when a run exceeds this and the table is showing a subset. */
const TRADES_PAGE_LIMIT = 1000;

function RunningState({ progress }: { progress: number }) {
  const pct = Math.min(100, Math.max(0, progress));
  return (
    <div className="flex flex-col items-center gap-4 py-16" data-testid="backtest-running">
      <div
        className="h-2 w-64 overflow-hidden rounded-full bg-[var(--neu-surface-inset)]"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Backtest progress"
      >
        <div
          className="h-full rounded-full bg-[var(--neu-accent)] transition-all duration-500"
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
      <p className="text-sm text-[var(--neu-text-muted)]">
        Running backtest… {Math.round(pct)}%
      </p>
    </div>
  );
}

export function BacktestResultsPage({ runId, onBack, onRetry, onCompare }: BacktestResultsPageProps) {
  const { data: run, isLoading, error } = useBacktestPolling(runId);

  const terminal = run ? isTerminalStatus(run.status) : false;
  const completed = run?.status === "completed";
  const [activeTab, setActiveTab] = React.useState("overview");

  // Trades are fetched lazily — once the run is completed AND the user opens a
  // tab that needs them (Trades or Analysis). Avoids parsing up to 1000 rows for
  // tabs that may never open.
  const needsTrades = activeTab === "trades" || activeTab === "analysis";
  const tradesQuery = useQuery({
    queryKey: ["backtest", runId, "trades"],
    queryFn: ({ signal }) =>
      backtestApi.getTrades(runId, { page: 1, limit: TRADES_PAGE_LIMIT }, signal),
    enabled: completed && needsTrades,
  });

  const [cancelling, setCancelling] = React.useState(false);
  const handleCancel = React.useCallback(async () => {
    if (cancelling) return;
    // Lightweight guard against accidental termination of a long-running sim.
    if (typeof window !== "undefined" && !window.confirm("Cancel this backtest?")) {
      return;
    }
    setCancelling(true);
    try {
      await backtestApi.cancel(runId);
    } catch {
      // polling will surface the resulting state
    } finally {
      setCancelling(false);
    }
  }, [runId, cancelling]);

  // Toast once when a run we're ACTIVELY WATCHING transitions to terminal. We
  // must not toast on mount of an already-finished run (deep link / refresh), so
  // we only fire when the previous observed status was pending/running.
  // IMPORTANT: this effect must stay declared BEFORE the [status] effect so the
  // per-run reset runs first within a commit where both runId and status change.
  const prevStatusRef = React.useRef<string | undefined>(undefined);
  const notifiedRef = React.useRef(false);
  const status = run?.status;
  React.useEffect(() => {
    // Switching runs: re-arm notification and seed prevStatus with the new run's
    // current status (seed, not clear) so a same-status cross-navigation still
    // detects the later active→terminal transition.
    notifiedRef.current = false;
    prevStatusRef.current = status;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
  React.useEffect(() => {
    const prev = prevStatusRef.current;
    if (status && status !== prev) {
      const wasActive = prev === "pending" || prev === "running";
      if (wasActive && !notifiedRef.current) {
        if (status === "completed") {
          notifiedRef.current = true;
          toast.success("Backtest completed");
        } else if (status === "failed") {
          notifiedRef.current = true;
          toast.error("Backtest failed");
        }
      }
      prevStatusRef.current = status;
    }
  }, [status]);

  const [inBasket, setInBasket] = React.useState(false);
  React.useEffect(() => {
    setInBasket(isInBasket(runId));
  }, [runId]);

  const handleAddToComparison = () => {
    const next = addToBasket(runId);
    setInBasket(next.includes(runId));
    if (next.includes(runId)) {
      toast.success(`Added to comparison (${next.length}/${MAX_BASKET})`);
    } else {
      toast.error(`Comparison is full (max ${MAX_BASKET})`);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-4" data-testid="backtest-loading">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-[var(--neu-danger)]">
          {error instanceof Error ? error.message : "Backtest not found."}
        </p>
        {onBack ? (
          <Button variant="outline" onClick={onBack}>
            Back to list
          </Button>
        ) : null}
      </div>
    );
  }

  const metrics = run.results?.metrics;
  const equityCurve = run.results?.equity_curve ?? [];

  return (
    <div className="flex flex-col gap-5" data-testid="backtest-results-page">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        {onBack ? (
          <Button variant="ghost" size="sm" onClick={onBack}>
            ← Back
          </Button>
        ) : null}
        <h1 className="text-xl font-bold tracking-tight text-[var(--neu-text-strong)]">
          Backtest Results
        </h1>
        <span aria-live="polite">
          <BacktestStatusBadge status={run.status} />
        </span>
        <span className="text-[0.78rem] text-[var(--neu-text-muted)]">{run.id}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {completed ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleAddToComparison}
              disabled={inBasket}
            >
              {inBasket ? "In comparison ✓" : "Add to comparison"}
            </Button>
          ) : null}
          {completed && onCompare ? (
            <Button variant="ghost" size="sm" onClick={() => onCompare(getBasket())} disabled={getBasket().length < 2}>
              Compare ({getBasket().length})
            </Button>
          ) : null}
          {!terminal ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
            >
              {cancelling ? "Cancelling…" : "Cancel"}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Sticky hero metrics for a completed run */}
      {completed && metrics ? (
        <HeroMetrics
          netProfit={metrics.net_profit}
          netProfitPct={metrics.net_profit_pct}
          winRate={metrics.win_rate}
          profitFactor={metrics.profit_factor}
          maxDdPct={metrics.max_dd_pct}
        />
      ) : null}

      {/* Body by status */}
      {run.status === "pending" || run.status === "running" ? (
        <RunningState progress={run.progress_pct} />
      ) : null}

      {run.status === "failed" ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-danger)]/40 p-6">
          <p className="text-sm font-semibold text-[var(--neu-danger)]">Backtest failed</p>
          <p className="mt-1 text-sm text-[var(--neu-text-muted)]">
            {run.error_message ?? "Unknown error."}
          </p>
          {onRetry ? (
            <Button variant="outline" size="sm" className="mt-4" onClick={() => onRetry(run.config)}>
              Retry with same settings
            </Button>
          ) : null}
        </div>
      ) : null}

      {run.status === "cancelled" ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-6">
          <p className="text-sm text-[var(--neu-text-muted)]">This backtest was cancelled.</p>
          {onRetry ? (
            <Button variant="outline" size="sm" className="mt-4" onClick={() => onRetry(run.config)}>
              Re-run with same settings
            </Button>
          ) : null}
        </div>
      ) : null}

      {completed && metrics ? (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="equity">Equity & Drawdown</TabsTrigger>
            <TabsTrigger value="trades">Trades</TabsTrigger>
            <TabsTrigger value="analysis">Analysis</TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <MetricsGrid metrics={metrics} />
          </TabsContent>

          <TabsContent value="equity">
            <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4">
              <EquityCurveChart
                equityCurve={equityCurve}
                buyHoldFinalValue={metrics.buy_hold_final_value}
              />
            </div>
          </TabsContent>

          <TabsContent value="trades">
            {tradesQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : tradesQuery.data ? (
              <div className="flex flex-col gap-2">
                {tradesQuery.data.total > tradesQuery.data.trades.length ? (
                  <p className="text-[0.78rem] text-[var(--neu-text-muted)]">
                    Showing first {tradesQuery.data.trades.length.toLocaleString()} of{" "}
                    {tradesQuery.data.total.toLocaleString()} trades.
                  </p>
                ) : null}
                <TradeListTable trades={tradesQuery.data.trades} totalCount={tradesQuery.data.total} />
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-[var(--neu-text-muted)]">
                No trades to display.
              </p>
            )}
          </TabsContent>

          <TabsContent value="analysis">
            {tradesQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <BacktestAnalysisTab trades={tradesQuery.data?.trades ?? []} />
            )}
          </TabsContent>
        </Tabs>
      ) : null}

      {/* Defensive: a completed run with no results payload (backend contract
          violation) would otherwise render a blank body. */}
      {completed && !metrics ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-6">
          <p className="text-sm text-[var(--neu-text-muted)]">
            This backtest completed but no results are available.
          </p>
        </div>
      ) : null}
    </div>
  );
}
