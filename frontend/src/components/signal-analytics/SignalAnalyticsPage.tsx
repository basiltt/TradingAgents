import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { KpiCards } from "./KpiCards";
import { CalibrationChart, type CalibrationRow } from "./CalibrationChart";
import { RollingWinRateChart, type WinRateRow } from "./RollingWinRateChart";
import { BenchmarkChart, type BenchmarkRow } from "./BenchmarkChart";
import { RegimeBreakdownChart, type RegimeRow } from "./RegimeBreakdownChart";
import { DecayAlertBanner } from "./DecayAlertBanner";
import { type DecayAlert, acknowledgeAlert } from "./decayAlerts";
import { TradeTable, type TradeRow } from "./TradeTable";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

interface Summary {
  total_trades: number;
  win_rate: number;
  avg_pnl_pct: number;
  total_pnl: number;
  avg_hold_minutes: number;
  current_streak: number;
  active_alerts: number;
}

interface PageData {
  summary: Summary;
  winRate: WinRateRow[];
  calibration: CalibrationRow[];
  benchmarks: BenchmarkRow[];
  regime: RegimeRow[];
  alerts: DecayAlert[];
  trades: TradeRow[];
}

async function fetchAll(signal: AbortSignal): Promise<PageData> {
  const headers = { "X-Requested-With": "XMLHttpRequest" };
  const get = (path: string) =>
    fetch(`${BASE_URL}${path}`, { signal, headers }).then((r) => r.json());

  const [summary, winRate, calibration, benchmarks, regime, alerts, tradesResp] =
    await Promise.all([
      get("/api/v1/signal-analytics/summary"),
      get("/api/v1/signal-analytics/win-rate"),
      get("/api/v1/signal-analytics/calibration"),
      get("/api/v1/signal-analytics/benchmarks"),
      get("/api/v1/signal-analytics/regime"),
      get("/api/v1/signal-analytics/decay-alerts"),
      get("/api/v1/signal-analytics/trades?limit=50"),
    ]);

  return {
    summary,
    winRate,
    calibration,
    benchmarks,
    regime,
    alerts,
    trades: tradesResp.trades ?? [],
  };
}

/**
 * Signal Analytics dashboard page.
 *
 * Fetches the full analytics bundle (summary, win-rate, calibration, benchmarks,
 * regime breakdown, decay alerts, recent trades) via a single React Query so the
 * request is abortable, retried, and cached like every other page. Decay-alert
 * acknowledgements optimistically prune the cached `alerts` array.
 *
 * @returns The analytics page (skeletons while loading, error card on failure).
 */
export function SignalAnalyticsPage() {
  const queryClient = useQueryClient();

  // AI-CONTEXT: Single useQuery replaces the previous fetch-in-useEffect. This
  // removes the synchronous setState-in-effect (react-hooks/set-state-in-effect),
  // and delegates loading/error/retry/abort to React Query — matching the rest of
  // the app. The query key is the stable cache identity; `refetch()` powers Retry.
  const SIGNAL_ANALYTICS_KEY = ["signal-analytics", "dashboard"] as const;
  const {
    data,
    isLoading: loading,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: SIGNAL_ANALYTICS_KEY,
    queryFn: ({ signal }) => fetchAll(signal),
  });
  const error = queryError
    ? (queryError instanceof Error ? queryError.message : "Failed to load signal analytics")
    : null;

  const handleAcknowledge = async (id: number) => {
    try {
      await acknowledgeAlert(id);
      // Optimistically drop the acknowledged alert from the cached page data so the
      // banner updates without a full refetch.
      queryClient.setQueryData<PageData>(SIGNAL_ANALYTICS_KEY, (prev) =>
        prev
          ? { ...prev, alerts: prev.alerts.filter((a) => a.id !== id) }
          : prev,
      );
    } catch {
      // AI-CONTEXT: Acknowledge is best-effort. On failure the alert simply
      // remains visible (the cache is unchanged), so the user can retry — no need
      // to surface an error toast for a non-destructive dismiss.
    }
  };

  const body = () => {
    if (loading) {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-[calc(var(--radius)*1.35)]" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-[calc(var(--radius)*1.55)]" />
          <Skeleton className="h-60 rounded-[calc(var(--radius)*1.55)]" />
          <Skeleton className="h-60 rounded-[calc(var(--radius)*1.55)]" />
        </div>
      );
    }

    if (error) {
      return (
        <Card className="border-destructive/25 bg-destructive/6">
          <CardContent className="p-6 text-center">
            <p className="text-destructive font-semibold">{error}</p>
            <button
              onClick={() => refetch()}
              className="mt-3 px-4 py-1.5 rounded bg-destructive text-destructive-foreground text-sm"
            >
              Retry
            </button>
          </CardContent>
        </Card>
      );
    }

    if (!data) return null;

    return (
      <div className="space-y-4">
        {data.alerts.length > 0 && (
          <DecayAlertBanner alerts={data.alerts} onAcknowledge={handleAcknowledge} />
        )}

        <KpiCards summary={data.summary} />

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold">Calibration by Confidence Tier</CardTitle>
            </CardHeader>
            <CardContent className="p-4 pt-0">
              <CalibrationChart data={data.calibration} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold">Rolling Win Rate</CardTitle>
            </CardHeader>
            <CardContent className="p-4 pt-0">
              <RollingWinRateChart data={data.winRate} />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Benchmark Comparison</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <BenchmarkChart data={data.benchmarks} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Performance by Market Regime</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <RegimeBreakdownChart data={data.regime} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Recent Trades</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <TradeTable trades={data.trades} />
          </CardContent>
        </Card>
      </div>
    );
  };

  return (
    <div className="space-y-4 pb-8">
      <PageHeader
        eyebrow="Analytics"
        title="Signal Analytics"
        description=""
        stats={[
          {
            label: "State",
            value: loading ? "Loading" : error ? "Error" : "Live",
            tone: loading ? "warning" : error ? "danger" : "success",
          },
        ]}
      />
      {body()}
    </div>
  );
}
