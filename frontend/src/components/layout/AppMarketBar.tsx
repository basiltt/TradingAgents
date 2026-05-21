import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeftRight,
  Radar,
  Server,
  Wallet,
} from "lucide-react";
import { accountsApi, apiClient, tradesApi } from "@/api/client";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { cn } from "@/lib/utils";

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

type MarketBarTone = "neutral" | "positive" | "warning" | "danger" | "accent";

function MarketBarItem({
  icon: Icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  icon: typeof Server;
  label: string;
  value: string;
  detail: string;
  tone?: MarketBarTone;
}) {
  return (
    <div
      data-tone={tone}
      className="ticker-item min-w-[10.25rem] flex-1"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            {label}
          </p>
          <p className="mt-1.5 text-base font-semibold tracking-tight text-foreground sm:text-[1.05rem]">
            <AnimatedNumber value={value} />
          </p>
        </div>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1)] border border-white/8 bg-white/4 text-primary shadow-[var(--shadow-soft)]">
          <Icon className="size-4" />
        </span>
      </div>
      <p className="mt-2.5 flex items-center gap-1.5 text-[0.78rem] text-muted-foreground">
        <span
          className={cn(
            "inline-flex size-2 rounded-full",
            tone === "positive" && "bg-emerald-400 shadow-[0_0_16px_rgba(52,211,153,0.55)]",
            tone === "warning" && "bg-amber-400 shadow-[0_0_16px_rgba(251,191,36,0.55)]",
            tone === "danger" && "bg-red-400 shadow-[0_0_16px_rgba(248,113,113,0.55)]",
            tone === "accent" && "bg-primary shadow-[0_0_18px_color-mix(in_oklch,var(--primary)_65%,transparent)]",
            tone === "neutral" && "bg-muted-foreground/70",
          )}
        />
        <span className="truncate">{detail}</span>
      </p>
    </div>
  );
}

export function AppMarketBar() {
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

  const portfolioEquity = portfolioQuery.data?.total_equity
    ? Number(portfolioQuery.data.total_equity)
    : null;
  const activeAccounts = portfolioQuery.data?.active_accounts ?? 0;
  const totalAccounts = portfolioQuery.data?.total_accounts ?? 0;

  const runtimeHealthy = healthQuery.data?.status === "ok";
  const runtimeTone: MarketBarTone = healthQuery.isError
    ? "danger"
    : runtimeHealthy
      ? "positive"
      : "warning";

  return (
    <div className="ticker-strip custom-scrollbar">
      <MarketBarItem
        icon={Server}
        label="Runtime"
        value={
          healthQuery.isError
            ? "Offline"
            : runtimeHealthy
              ? "Stable"
              : "Degraded"
        }
        detail={
          healthQuery.isError
            ? "API health check unavailable"
            : `Database ${healthQuery.data?.db ?? "unknown"} • live control plane`
        }
        tone={runtimeTone}
      />
      <MarketBarItem
        icon={Wallet}
        label="Portfolio Equity"
        value={formatCurrencyCompact(portfolioEquity)}
        detail={`${activeAccounts}/${totalAccounts} accounts active`}
        tone={portfolioEquity != null && portfolioEquity > 0 ? "positive" : "neutral"}
      />
      <MarketBarItem
        icon={Activity}
        label="Research Queue"
        value={String(analysisMetrics.running)}
        detail={`${analysisMetrics.completed} completed analyses`}
        tone={analysisMetrics.running > 0 ? "accent" : "neutral"}
      />
      <MarketBarItem
        icon={Radar}
        label="Scanner Pulse"
        value={String(scanMetrics.running)}
        detail={
          scanMetrics.running > 0
            ? `${scanMetrics.signals} live result rows`
            : "No active market sweeps"
        }
        tone={scanMetrics.running > 0 ? "accent" : "neutral"}
      />
      <MarketBarItem
        icon={ArrowLeftRight}
        label="Trade Desk"
        value={String(tradesQuery.data?.open_count ?? 0)}
        detail={`Win rate ${formatPercent(tradesQuery.data?.win_rate)}`}
        tone={
          tradesQuery.isError
            ? "warning"
            : (tradesQuery.data?.total_pnl ?? 0) >= 0
              ? "positive"
              : "danger"
        }
      />
    </div>
  );
}
