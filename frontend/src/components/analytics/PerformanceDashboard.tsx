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
import { LiveTab } from "./tabs/LiveTab";
import type { PerformanceTimeframe } from "./performanceTypes";

interface Props { embedded?: boolean; accountId?: string; }

const STORAGE_KEY = "performance-filters";
const VALID_TIMEFRAMES: ReadonlySet<string> = new Set([
  "1D", "1W", "1M", "3M", "YTD", "1Y", "ALL",
]);
const DEFAULT_FILTERS: { scope: string; timeframe: PerformanceTimeframe } = {
  scope: "all", timeframe: "ALL",
};

function loadFilters(): { scope: string; timeframe: PerformanceTimeframe } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FILTERS;
    const parsed = JSON.parse(raw);
    // Validate shape AND timeframe membership: a corrupt object, a non-object, or a stale
    // timeframe token (e.g. one removed in a later release) must fall back to defaults --
    // otherwise it flows to the API, 422s, and the Retry button re-sends the same bad value.
    if (
      parsed && typeof parsed === "object" &&
      typeof parsed.scope === "string" &&
      typeof parsed.timeframe === "string" &&
      VALID_TIMEFRAMES.has(parsed.timeframe)
    ) {
      return { scope: parsed.scope, timeframe: parsed.timeframe as PerformanceTimeframe };
    }
  } catch { /* ignore */ }
  return DEFAULT_FILTERS;
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
  // Overview shows the trade-derived dashboard, or an honest empty card when the selected
  // window has no closed trades. Live & Signals are timeframe-independent (open positions /
  // signal coverage), so they must stay reachable even when hasTrades is false -- gating the
  // whole tab strip on window-scoped trade count would hide live positions for a fresh or
  // recently-quiet account.
  const overviewContent = data && (hasTrades ? (
    <OverviewTab overview={data} />
  ) : (
    <div className="neu-surface-base rounded-[var(--neu-radius-md)] p-10 text-center">
      <p className="text-[var(--neu-text-strong)]">No closed trades in this range</p>
      <p className="mt-1 text-[var(--neu-text-soft)]">
        Adjust the timeframe, or check the Live tab for open positions.
      </p>
    </div>
  ));

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
          <NeuTabs
            value={tab}
            onValueChange={setTab}
            variant="inset"
            items={[
              { value: "overview", label: "Overview", content: overviewContent },
              { value: "trades", label: "Trades", content: <TradesTab scope={effectiveScope} timeframe={timeframe} /> },
              { value: "signals", label: "Signals", content: <SignalsTab scope={effectiveScope} /> },
              { value: "live", label: "Live", content: <LiveTab scope={effectiveScope} /> },
            ]}
          />
        </>
      )}
    </div>
  );
}
