import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeftRight,
  Radar,
  Server,
  Wallet,
} from "lucide-react";
import { accountsApi, apiClient, tradesApi } from "@/api/client";
import { NeuMarketStrip } from "@/design-system/neumorphism";

function formatCurrencyCompact(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    notation: Math.abs(value) >= 100000 ? "compact" : "standard",
    maximumFractionDigits: Math.abs(value) >= 100000 ? 1 : 2,
  }).format(value);
}

function formatPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(1)}%`;
}

export function AppMarketBar() {
  const [compact, setCompact] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(max-width: 767px)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setCompact(media.matches);
    update();

    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const healthQuery = useQuery({
    queryKey: ["shell", "health"],
    queryFn: ({ signal }) => apiClient.getHealth(signal),
    staleTime: 12_000,
    refetchInterval: 15_000,
    retry: 1,
  });

  const portfolioQuery = useQuery({
    queryKey: ["shell", "portfolio-summary"],
    queryFn: ({ signal }) => accountsApi.getPortfolioSummary(signal),
    staleTime: 15_000,
    refetchInterval: 20_000,
    retry: 1,
  });

  const analysesQuery = useQuery({
    queryKey: ["shell", "analyses"],
    queryFn: ({ signal }) => apiClient.listAnalyses({ limit: 100 }, signal),
    staleTime: 12_000,
    refetchInterval: 20_000,
    retry: 1,
  });

  const scansQuery = useQuery({
    queryKey: ["shell", "scans"],
    queryFn: ({ signal }) => apiClient.listScans(signal),
    staleTime: 12_000,
    refetchInterval: 20_000,
    retry: 1,
  });

  const tradesQuery = useQuery({
    queryKey: ["shell", "trade-stats"],
    queryFn: ({ signal }) => tradesApi.getStats(undefined, signal),
    staleTime: 15_000,
    refetchInterval: 20_000,
    retry: 1,
  });

  const analysisMetrics = useMemo(() => {
    const items = analysesQuery.data?.items ?? [];
    return {
      running: items.filter((item) => item.status === "running").length,
      completed: items.filter((item) => item.status === "completed").length,
    };
  }, [analysesQuery.data?.items]);

  const scanMetrics = useMemo(() => {
    const scans = scansQuery.data?.scans ?? [];
    const running = scans.filter((scan) => scan.status === "running");
    return {
      running: running.length,
      signals: running.reduce((sum, scan) => sum + (scan.results?.length ?? 0), 0),
    };
  }, [scansQuery.data?.scans]);

  const items = useMemo(() => {
    const portfolioEquity = portfolioQuery.data?.total_equity
      ? Number(portfolioQuery.data.total_equity)
      : null;
    const activeAccounts = portfolioQuery.data?.active_accounts ?? 0;
    const totalAccounts = portfolioQuery.data?.total_accounts ?? 0;
    const runtimeHealthy = healthQuery.data?.status === "ok";

    return [
      {
        id: "runtime",
        icon: <Server className="size-4.5" />,
        label: "Runtime",
        value: healthQuery.isError ? "Offline" : runtimeHealthy ? "Stable" : "Degraded",
        detail: healthQuery.isError
          ? "API health check unavailable"
          : `Database ${healthQuery.data?.db ?? "unknown"} • live control plane`,
        tone: healthQuery.isError ? "danger" : runtimeHealthy ? "success" : "warning",
      },
      {
        id: "portfolio-equity",
        icon: <Wallet className="size-4.5" />,
        label: "Portfolio equity",
        value: formatCurrencyCompact(portfolioEquity),
        detail: `${activeAccounts}/${totalAccounts} accounts active`,
        tone: portfolioEquity != null && portfolioEquity > 0 ? "success" : "neutral",
      },
      {
        id: "research-queue",
        icon: <Activity className="size-4.5" />,
        label: "Research queue",
        value: String(analysisMetrics.running),
        detail: `${analysisMetrics.completed} completed analyses`,
        tone: analysisMetrics.running > 0 ? "accent" : "neutral",
      },
      {
        id: "scanner-pulse",
        icon: <Radar className="size-4.5" />,
        label: "Scanner pulse",
        value: String(scanMetrics.running),
        detail: scanMetrics.running > 0 ? `${scanMetrics.signals} live result rows` : "No active market sweeps",
        tone: scanMetrics.running > 0 ? "accent" : "neutral",
      },
      {
        id: "trade-desk",
        icon: <ArrowLeftRight className="size-4.5" />,
        label: "Trade desk",
        value: String(tradesQuery.data?.open_count ?? 0),
        detail: `Win rate ${formatPercent(tradesQuery.data?.win_rate)}`,
        tone: tradesQuery.isError ? "warning" : (tradesQuery.data?.total_pnl ?? 0) >= 0 ? "success" : "danger",
      },
    ] as const;
  }, [
    analysisMetrics.completed,
    analysisMetrics.running,
    healthQuery.data?.db,
    healthQuery.data?.status,
    healthQuery.isError,
    portfolioQuery.data?.active_accounts,
    portfolioQuery.data?.total_accounts,
    portfolioQuery.data?.total_equity,
    scanMetrics.running,
    scanMetrics.signals,
    tradesQuery.data?.open_count,
    tradesQuery.data?.total_pnl,
    tradesQuery.data?.win_rate,
    tradesQuery.isError,
  ]);

  return <NeuMarketStrip items={items.map((item) => ({ ...item }))} compact={compact} />;
}
