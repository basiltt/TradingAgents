import type { PerformanceTimeframe } from "./performanceTypes";

const TIMEFRAMES: PerformanceTimeframe[] = ["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"];

interface Props {
  scope: string;
  timeframe: PerformanceTimeframe;
  onScopeChange: (s: string) => void;
  onTimeframeChange: (t: PerformanceTimeframe) => void;
  accounts: Array<{ id: string; label: string; account_type: "live" | "demo" }>;
  hideScope?: boolean; // embedded mode
}

export function PerformanceControlBar({
  scope, timeframe, onScopeChange, onTimeframeChange, accounts, hideScope,
}: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {!hideScope && (
        <select
          value={scope}
          onChange={(e) => onScopeChange(e.target.value)}
          className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] px-3 py-2 text-[var(--neu-text-strong)]"
          aria-label="Performance scope"
        >
          <option value="all">All Accounts</option>
          <option value="live">Live</option>
          <option value="demo">Demo</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.label}</option>
          ))}
        </select>
      )}
      <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Timeframe">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => onTimeframeChange(tf)}
            aria-pressed={tf === timeframe}
            className={`rounded-[var(--neu-radius-md)] px-2.5 py-1 text-sm ${
              tf === timeframe
                ? "neu-surface-inset text-[var(--neu-accent)]"
                : "text-[var(--neu-text-soft)]"
            }`}
          >
            {tf}
          </button>
        ))}
      </div>
    </div>
  );
}
