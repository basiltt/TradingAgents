import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NeuTabs } from "@/design-system/neumorphism";
import { accountsApi } from "@/api/client";
import { usePerformanceOverview } from "./hooks/usePerformance";
import { PerformanceControlBar } from "./PerformanceControlBar";
import { PerformanceHeroStrip } from "./PerformanceHeroStrip";
import { OverviewTab } from "./tabs/OverviewTab";
import { TradesTab } from "./tabs/TradesTab";
import { SignalsTab } from "./tabs/SignalsTab";
import type { PerformanceTimeframe } from "./performanceTypes";

interface Props { embedded?: boolean; accountId?: string; }

const STORAGE_KEY = "performance-filters";

function loadFilters(): { scope: string; timeframe: PerformanceTimeframe } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { scope: "all", timeframe: "ALL" };
}

export function PerformanceDashboard({ embedded = false, accountId }: Props) {
  const initial = loadFilters();
  const [scope, setScope] = useState(embedded && accountId ? accountId : initial.scope);
  const [timeframe, setTimeframe] = useState<PerformanceTimeframe>(initial.timeframe);
  const [tab, setTab] = useState("overview");
  const effectiveScope = embedded && accountId ? accountId : scope;

  const { data, isLoading, isError, refetch } = usePerformanceOverview(effectiveScope, timeframe);

  const { data: accountsRaw } = useQuery({
    queryKey: ["performance-accounts"],
    queryFn: ({ signal }) => accountsApi.list(undefined, signal),
    enabled: !embedded,
    staleTime: 60_000,
  });
  const accountOptions = (accountsRaw ?? []).map((a) => ({
    id: a.id,
    label: a.label ?? a.id,
    account_type: a.account_type as "live" | "demo",
  }));

  function update(next: { scope?: string; timeframe?: PerformanceTimeframe }) {
    const s = next.scope ?? scope;
    const t = next.timeframe ?? timeframe;
    setScope(s);
    setTimeframe(t);
    if (!embedded) localStorage.setItem(STORAGE_KEY, JSON.stringify({ scope: s, timeframe: t }));
  }

  const hasTrades = (data?.kpis.total_trades ?? 0) > 0;

  return (
    <div className="flex flex-col gap-4">
      <PerformanceControlBar
        scope={effectiveScope}
        timeframe={timeframe}
        onScopeChange={(s) => update({ scope: s })}
        onTimeframeChange={(t) => update({ timeframe: t })}
        accounts={accountOptions}
        hideScope={embedded}
      />
      {isLoading && (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-20 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />
            ))}
          </div>
          <div className="h-72 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />
        </div>
      )}
      {isError && (
        <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-6 text-center">
          <p className="text-[var(--neu-danger)]">Failed to load performance.</p>
          <button onClick={() => refetch()} className="mt-2 underline">Retry</button>
        </div>
      )}
      {data && (
        <>
          <PerformanceHeroStrip overview={data} />
          {hasTrades ? (
            <NeuTabs
              value={tab}
              onValueChange={setTab}
              variant="inset"
              items={[
                { value: "overview", label: "Overview", content: <OverviewTab overview={data} /> },
                { value: "trades", label: "Trades", content: <TradesTab scope={effectiveScope} timeframe={timeframe} /> },
                { value: "signals", label: "Signals", content: <SignalsTab scope={effectiveScope} /> },
              ]}
            />
          ) : (
            <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-10 text-center">
              <p className="text-[var(--neu-text-strong)]">No closed trades yet</p>
              <p className="mt-1 text-[var(--neu-text-soft)]">
                Run the Scanner or enable Auto-Trade to start building performance.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
