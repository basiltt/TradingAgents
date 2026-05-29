import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { KpiCards } from "./KpiCards";
import { CalibrationChart, type CalibrationRow } from "./CalibrationChart";
import { RollingWinRateChart, type WinRateRow } from "./RollingWinRateChart";
import { BenchmarkChart, type BenchmarkRow } from "./BenchmarkChart";
import { RegimeBreakdownChart, type RegimeRow } from "./RegimeBreakdownChart";
import { DecayAlertBanner, type DecayAlert, acknowledgeAlert } from "./DecayAlertBanner";
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

export function SignalAnalyticsPage() {
  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchAll(controller.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setError(e?.message ?? "Failed to load signal analytics");
        setLoading(false);
      });
    return () => controller.abort();
  }, [retryCount]);

  const handleAcknowledge = async (id: number) => {
    try {
      await acknowledgeAlert(id);
      setData((prev) =>
        prev
          ? { ...prev, alerts: prev.alerts.filter((a) => a.id !== id) }
          : prev,
      );
    } catch {
      // silently ignore
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
              onClick={() => setRetryCount((c) => c + 1)}
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
