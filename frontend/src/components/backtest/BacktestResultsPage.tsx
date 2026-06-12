import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Check, X } from "lucide-react";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { backtestApi } from "@/api/client";
import { useBacktestPolling } from "@/hooks/useBacktestPolling";
import { useBacktestProgressWS } from "@/hooks/useBacktestProgressWS";
import { isTerminalStatus } from "./types";
import { BacktestStatusBadge } from "./BacktestStatusBadge";
import { MetricsGrid } from "./MetricsGrid";
import { EquityCurveChart } from "./EquityCurveChart";
import { computeCooloffMembership } from "./equityCurveData";
import { extractCooloff, cooloffReasonLabel } from "./cooloffResults";
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

/** Friendly copy for engine/service warning codes. Unknown codes fall back to
 * the raw code so nothing is silently dropped. */
const WARNING_LABELS: Record<string, string> = {
  no_signals_found: "No scan signals matched this date range and filters.",
  max_same_sector_not_enforced:
    "The “Max Same Sector” limit is not simulated — results may differ from live trading, which enforces it.",
  f2_long_ack_bypassed_in_backtest:
    "F2 long-side acknowledgement is bypassed in the backtest (there is no live account) — the long side is honored via mr_long_enabled so its expectancy is measurable here.",
  mr_entry_uses_next_bar_open:
    "Mean-reversion side/geometry use the next-bar-open fill price (no look-ahead), which can differ slightly from live trading’s scan-time mark.",
  btc_vol_uses_historical_klines_at_scan_time:
    "The BTC volatility filter is evaluated from historical klines as of each scan time.",
};

function warningLabel(code: string): string {
  if (WARNING_LABELS[code]) return WARNING_LABELS[code];
  // "signals_dropped_no_kline_data_<N>" — some signals had no cached candles, so the
  // backtest couldn't simulate them and under-traded vs live trading.
  const noKline = code.match(/^signals_dropped_no_kline_data_(\d+)$/);
  if (noKline) {
    return `${Number(noKline[1]).toLocaleString()} signal(s) were skipped because the symbol had no cached candles — live trading would have taken these, so results under-count trades. Warm the cache for full coverage.`;
  }
  // Any other code (metrics diagnostics like "metrics_dropped_2_malformed_trades",
  // or a future engine code like "funding_rate_estimated") → de-underscored so it
  // reads as words rather than raw snake_case, and nothing is silently dropped.
  return code.replace(/_/g, " ");
}

/** Error + retry affordance for the lazy trades fetch. Shared by the Trades and
 * Analysis tabs (both depend on the same query) so a failed fetch never silently
 * degrades to an empty table / empty charts on either tab. */
function TradesFetchError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <p className="text-sm text-[var(--neu-danger)]">Failed to load trades.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

/** Null/NaN-safe fixed-decimal formatter — "—" when a value isn't finite, so a
 *  missing/NaN metric never crashes the whole results page via `.toFixed()`. */
function fmtNum(v: number | null | undefined, digits: number, sign = false): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${sign && v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

/** Sticky strip of the 4 headline metrics shown above the tabs. */
function HeroMetrics({
  netProfit,
  netProfitPct,
  winRate,
  profitFactor,
  maxDdPct,
  finalEquity,
}: {
  netProfit: number;
  netProfitPct: number | null;
  winRate: number | null;
  profitFactor: number | null;
  maxDdPct: number;
  finalEquity: number;
}) {
  const cls = netProfit >= 0 ? "text-emerald-500" : "text-rose-500";
  // Starting balance is the compounding anchor: final equity minus all net PnL.
  // Derived from metrics (not run.config) so it is always internally consistent
  // with the Net Profit shown alongside it.
  const startingBalance = finalEquity - netProfit;
  const tiles = [
    { label: "Net Profit", value: formatUsd(netProfit, { sign: true }), sub: formatPct(netProfitPct, { sign: true }), color: cls },
    { label: "Win Rate", value: formatPct(winRate) },
    { label: "Profit Factor", value: formatRatio(profitFactor, { infinite: true }) },
    { label: "Max Drawdown", value: formatPct(maxDdPct), color: "text-rose-500" },
  ];
  return (
    <div className="flex flex-col gap-3" data-testid="hero-metrics">
      {/* Equity progression — makes the compounded start→end growth obvious at a
          glance (the dashboard otherwise only shows the % delta). */}
      <div
        data-testid="equity-progression"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-inset px-4 py-3"
      >
        <span className="text-[0.68rem] font-semibold uppercase tracking-wide text-[var(--neu-text-muted)]">
          Equity
        </span>
        <span className="text-lg font-bold tabular-nums text-[var(--neu-text-muted)]">
          {formatUsd(startingBalance)}
        </span>
        <span className="text-[var(--neu-text-muted)]" aria-hidden="true">→</span>
        <span className={`text-lg font-bold tabular-nums ${cls}`}>
          {formatUsd(finalEquity)}
        </span>
        <span className={`text-[0.78rem] font-semibold tabular-nums ${cls}`}>
          ({formatUsd(netProfit, { sign: true })} · {formatPct(netProfitPct, { sign: true })})
        </span>
        <span className="text-[0.68rem] text-[var(--neu-text-muted)]">
          start → final
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] px-4 py-3">
            <p className="text-[0.68rem] font-semibold uppercase tracking-wide text-[var(--neu-text-muted)]">{t.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${t.color ?? "text-[var(--neu-text-strong)]"}`}>{t.value}</p>
            {t.sub ? <p className="text-[0.7rem] text-[var(--neu-text-muted)]">{t.sub}</p> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Trades fetched into the table at once. MUST stay within the backend's cap —
 * the router rejects limit > 500 (Query le=500) and the service clamps to 500, so
 * requesting more would 422 the whole Trades/Analysis fetch. The backend reports
 * `total`, so when a run exceeds this we warn the user the table shows a subset. */
const TRADES_PAGE_LIMIT = 500;

function StepRow({
  label,
  detail,
  status,
}: {
  label: string;
  detail: string;
  status: "active" | "done" | "failed";
}) {
  return (
    <li className="flex items-start gap-3 py-1.5">
      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center">
        {status === "done" ? (
          <Check className="size-4 text-[var(--neu-success)]" aria-hidden="true" />
        ) : status === "failed" ? (
          <X className="size-4 text-[var(--neu-danger)]" aria-hidden="true" />
        ) : (
          <Loader2 className="size-4 animate-spin text-[var(--neu-accent)]" aria-hidden="true" />
        )}
      </span>
      <span className="flex flex-col">
        <span
          className={
            status === "active"
              ? "text-sm font-medium text-[var(--neu-text)]"
              : "text-sm text-[var(--neu-text-muted)]"
          }
        >
          {label}
        </span>
        {detail ? (
          <span className="text-xs tabular-nums text-[var(--neu-text-muted)]">{detail}</span>
        ) : null}
      </span>
    </li>
  );
}

function RunningState({
  runId,
  progress,
  active,
}: {
  runId: string | undefined;
  progress: number;
  active: boolean;
}) {
  const { steps, pct: wsPct } = useBacktestProgressWS(runId, active);
  // Prefer the WS pct when present (finer-grained), else the polled progress_pct.
  const pct = Math.min(100, Math.max(0, wsPct ?? progress));
  // Phase label is a fallback shown only until the first WS step arrives, so the
  // view is never blank during the WS handshake.
  const phase =
    pct < 10
      ? "Warming up price-data cache…"
      : pct < 100
        ? "Simulating trades…"
        : "Finalizing results…";

  return (
    <div
      className="mx-auto flex w-full max-w-md flex-col gap-5 py-12"
      data-testid="backtest-running"
      aria-live="polite"
    >
      {/* Progress bar — determinate fill + indeterminate sweep so it always moves. */}
      <div
        className="relative h-2 w-full overflow-hidden rounded-full bg-[var(--neu-surface-inset)]"
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
        <div className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-progress-sweep rounded-full bg-gradient-to-r from-transparent via-[var(--neu-accent)]/60 to-transparent" />
      </div>

      {steps.length > 0 ? (
        // Live step-by-step list streamed over the WebSocket.
        <ul className="flex flex-col rounded-[var(--neu-radius-lg)] bg-[var(--neu-surface-inset)]/40 px-4 py-3">
          {steps.map((s) => (
            <StepRow key={s.stage} label={s.label} detail={s.detail} status={s.status} />
          ))}
        </ul>
      ) : (
        // Fallback until the first WS event arrives (or if WS is unavailable).
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="size-6 animate-spin text-[var(--neu-accent)]" aria-hidden="true" />
          <p className="text-sm font-medium text-[var(--neu-text)]">
            {phase}
            <span className="ml-0.5 inline-flex">
              <span className="animate-bounce [animation-delay:-0.3s]">.</span>
              <span className="animate-bounce [animation-delay:-0.15s]">.</span>
              <span className="animate-bounce">.</span>
            </span>
          </p>
        </div>
      )}

      <p className="text-center text-xs tabular-nums text-[var(--neu-text-muted)]">
        {Math.round(pct)}% complete
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
  // tab that needs them (Trades or Analysis). Avoids parsing up to TRADES_PAGE_LIMIT
  // rows for tabs that may never open.
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

  // AI-CONTEXT: `inBasket` is derived from runId (via isInBasket, a localStorage
  // read) but must also update when the user clicks Add/Remove. We use React's
  // documented "adjust state while rendering when a prop changes" pattern instead
  // of a setState-in-effect (react-hooks/set-state-in-effect): compare the live
  // runId against the previous one during render and reseed synchronously. This
  // avoids the extra commit+flash an effect would cause on run switches.
  const [inBasket, setInBasket] = React.useState(() => isInBasket(runId));
  const [seenRunId, setSeenRunId] = React.useState(runId);
  if (runId !== seenRunId) {
    setSeenRunId(runId);
    setInBasket(isInBasket(runId));
  }

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

  // Treat metrics as present only when they carry real content. A run with no
  // matching signals yields metrics={} which the service then augments with a
  // few buy&hold keys — making it truthy but field-less. Gating on a required
  // metric field (total_trades) routes that case to the "no results" fallback
  // instead of rendering a wall of N/A tiles.
  const rawMetrics = run.results?.metrics;
  const metrics =
    rawMetrics && rawMetrics.total_trades != null ? rawMetrics : undefined;
  const equityCurve = run.results?.equity_curve ?? [];
  const resultWarnings = run.results?.warnings ?? [];
  const replay = run.results?.replay_comparison ?? null;

  // Cool-off telemetry rides in results.summary (the persisted filter_stats). These
  // keys are present ONLY when at least one cool-off tier was enabled for the run;
  // a backtest with cool-off OFF omits them entirely, so the stat + bands simply do
  // not render (the pre-feature view). See backtest_engine._cooloff_finalize_bands.
  const cooloff = extractCooloff(run.results?.summary);
  // The chart only shades bands that actually contain an equity sample (categorical
  // x-axis membership). Gate the "Shaded = cool-off pause" legend on the SAME check
  // so the legend never claims shading the chart didn't draw (e.g. a sub-sample band).
  // Cheap single pass; not memoised because this code runs after the component's
  // early returns (a hook here would violate rules-of-hooks) and the cost is trivial.
  const cooloffBandsVisible =
    cooloff.bands.length > 0 && computeCooloffMembership(equityCurve, cooloff.bands).some(Boolean);

  // Retry/Re-run must reproduce the ORIGINAL run faithfully. The backend stores
  // scan_source in a separate column from config, so run.config alone omits it —
  // merging it back in keeps a schedule/explicit-sourced run from resetting to the
  // date_range default on retry.
  const retryConfig: Record<string, unknown> = {
    ...run.config,
    scan_source: run.scan_source,
  };

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
          finalEquity={metrics.final_equity}
        />
      ) : null}

      {/* Replay vs Live — only for replay-mode runs. The headline run metrics use the
          live ledger; this section is the pure candle-engine diagnostic comparison. */}
      {completed && replay && replay.n_cycles > 0 ? (
        <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4">
          <div className="mb-3 flex flex-wrap items-baseline gap-2">
            <h2 className="text-base font-semibold text-[var(--neu-text-strong)]">Engine Diagnostic vs Live</h2>
            <span className="text-[0.72rem] text-[var(--neu-text-muted)]">
              {replay.pinned_trades} pinned trades · {replay.n_cycles} cycles
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] px-4 py-3">
              <div className="text-[0.72rem] text-[var(--neu-text-muted)]">Final equity delta</div>
              <div className="text-lg font-semibold tabular-nums text-[var(--neu-text-strong)]">
                {fmtNum(replay.final_equity_delta_pct, 1, true)}%
              </div>
            </div>
            <div className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] px-4 py-3">
              <div className="text-[0.72rem] text-[var(--neu-text-muted)]">Per-cycle PnL correlation</div>
              <div className="text-lg font-semibold tabular-nums text-[var(--neu-text-strong)]">
                {fmtNum(replay.pnl_correlation, 2)}
              </div>
            </div>
            <div className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] px-4 py-3">
              <div className="text-[0.72rem] text-[var(--neu-text-muted)]">Directional agreement</div>
              <div className="text-lg font-semibold tabular-nums text-[var(--neu-text-strong)]">
                {replay.directional_agreement}/{replay.n_cycles}
              </div>
            </div>
          </div>
          <p className="mt-2 text-[0.72rem] text-[var(--neu-text-muted)]">
            Headline metrics use the live account ledger; this table shows the pure candle-engine replay gap.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-[0.78rem] tabular-nums">
              <thead>
                <tr className="text-left text-[var(--neu-text-muted)]">
                  <th className="px-2 py-1 font-medium">Cycle</th>
                  <th className="px-2 py-1 text-right font-medium">Live PnL</th>
                  <th className="px-2 py-1 text-right font-medium">Backtest PnL</th>
                  <th className="px-2 py-1 text-right font-medium">Live equity</th>
                  <th className="px-2 py-1 text-right font-medium">BT equity</th>
                  <th className="px-2 py-1 text-right font-medium">Δ%</th>
                </tr>
              </thead>
              <tbody>
                {replay.cycles.map((c) => (
                  <tr key={c.scan_id} className="border-t border-[var(--neu-surface-inset)]">
                    <td className="px-2 py-1 font-mono">{c.scan_id.slice(0, 8)}</td>
                    <td className="px-2 py-1 text-right">{fmtNum(c.live_net_pnl, 2)}</td>
                    <td className="px-2 py-1 text-right">{fmtNum(c.backtest_net_pnl, 2)}</td>
                    <td className="px-2 py-1 text-right">{fmtNum(c.live_equity_after, 2)}</td>
                    <td className="px-2 py-1 text-right">{fmtNum(c.backtest_equity_after, 2)}</td>
                    <td className="px-2 py-1 text-right">
                      {fmtNum(c.delta_pct, 1, true)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* Result warnings banner — surfaced for ANY completed run with metrics so
          approximations (e.g. max_same_sector not simulated) and metrics
          diagnostics aren't silently hidden behind a clean dashboard. The
          no-results empty state handles the no_signals_found case separately. */}
      {completed && metrics && resultWarnings.length > 0 ? (
        <div
          role="status"
          data-testid="result-warnings"
          className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-warning)]/40 bg-[color:var(--neu-warning)]/5 px-4 py-3"
        >
          <p className="text-[0.8rem] font-semibold text-[var(--neu-warning)]">Notes about these results</p>
          <ul className="mt-1 list-inside list-disc text-[0.78rem] text-[var(--neu-text-muted)]">
            {resultWarnings.map((w) => (
              <li key={w}>{warningLabel(w)}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Body by status */}
      {run.status === "pending" || run.status === "running" ? (
        <RunningState
          runId={runId}
          progress={run.progress_pct}
          active={run.status === "pending" || run.status === "running"}
        />
      ) : null}

      {run.status === "failed" ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-danger)]/40 p-6">
          <p className="text-sm font-semibold text-[var(--neu-danger)]">Backtest failed</p>
          <p className="mt-1 text-sm text-[var(--neu-text-muted)]">
            {run.error_message ?? "Unknown error."}
          </p>
          {onRetry ? (
            <Button variant="outline" size="sm" className="mt-4" onClick={() => onRetry(retryConfig)}>
              Retry with same settings
            </Button>
          ) : null}
        </div>
      ) : null}

      {run.status === "cancelled" ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-6">
          <p className="text-sm text-[var(--neu-text-muted)]">This backtest was cancelled.</p>
          {onRetry ? (
            <Button variant="outline" size="sm" className="mt-4" onClick={() => onRetry(retryConfig)}>
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
                cooloffBands={cooloff.bands}
              />
              {cooloff.hasContent ? (
                <div
                  className="mt-3 flex flex-col gap-2 border-t border-[var(--neu-stroke-soft)] pt-3"
                  data-testid="cooloff-summary"
                >
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    {cooloffBandsVisible ? (
                      <span className="flex items-center gap-1.5 text-[var(--neu-text-muted)]">
                        <span
                          className="inline-block h-3 w-3 rounded-sm border border-[var(--neu-warning)]"
                          style={{ backgroundColor: "var(--neu-warning)", opacity: 0.14 }}
                          aria-hidden="true"
                        />
                        Shaded = cool-off pause
                      </span>
                    ) : null}
                    <span className="text-[var(--neu-text-strong)]">
                      <strong>{cooloff.signalsSkipped.toLocaleString()}</strong> signal
                      {cooloff.signalsSkipped === 1 ? "" : "s"} skipped during cool-off
                    </span>
                  </div>
                  {cooloff.byReason.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {cooloff.byReason.map((r) => (
                        <span
                          key={r.reason}
                          className="rounded-full bg-[var(--neu-surface-sunken)] px-2 py-0.5 text-xs text-[var(--neu-text-muted)]"
                        >
                          {cooloffReasonLabel(r.reason)}: {r.count.toLocaleString()}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </TabsContent>

          <TabsContent value="trades">
            {tradesQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : tradesQuery.isError ? (
              <TradesFetchError onRetry={() => tradesQuery.refetch()} />
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
            ) : tradesQuery.isError ? (
              <TradesFetchError onRetry={() => tradesQuery.refetch()} />
            ) : (
              <div className="flex flex-col gap-2">
                {tradesQuery.data && tradesQuery.data.total > tradesQuery.data.trades.length ? (
                  <p className="text-[0.78rem] text-[var(--neu-warning)]" role="status">
                    Analysis covers the first {tradesQuery.data.trades.length.toLocaleString()} of{" "}
                    {tradesQuery.data.total.toLocaleString()} trades — the charts below
                    reflect only this subset, so they may not match the Overview totals.
                  </p>
                ) : null}
                <BacktestAnalysisTab trades={tradesQuery.data?.trades ?? []} />
              </div>
            )}
          </TabsContent>
        </Tabs>
      ) : null}

      {/* Completed but no usable metrics — most commonly a run whose date
          range / filters matched no scan signals. Explain it (and surface any
          engine warnings) rather than showing a wall of N/A tiles. */}
      {completed && !metrics ? (
        <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-6" data-testid="no-results">
          <p className="text-sm font-medium text-[var(--neu-text-strong)]">
            No trades were simulated
          </p>
          <p className="mt-1 text-sm text-[var(--neu-text-muted)]">
            {resultWarnings.includes("no_signals_found")
              ? "No scan signals matched this date range and filters. Widen the range, relax the filters, or pick a different signal source."
              : "This backtest completed but produced no usable results."}
          </p>
          {resultWarnings.filter((w) => w !== "no_signals_found").length > 0 ? (
            <ul className="mt-3 list-inside list-disc text-[0.78rem] text-[var(--neu-text-soft)]">
              {resultWarnings
                .filter((w) => w !== "no_signals_found")
                .map((w) => (
                  <li key={w}>{warningLabel(w)}</li>
                ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
