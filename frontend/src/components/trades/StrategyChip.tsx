import { memo } from "react";

export type StrategyKind = "trend" | "mean_reversion";

interface StrategyChipProps {
  kind: StrategyKind;
  /** Optional fade/trade direction shown after the strategy label. */
  direction?: "long" | "short";
  className?: string;
}

const STYLES: Record<StrategyKind, { label: string; cls: string }> = {
  trend: {
    label: "Trend",
    cls: "bg-sky-500/[0.08] text-sky-400 border-sky-500/20",
  },
  mean_reversion: {
    label: "Mean-Rev",
    cls: "bg-violet-500/[0.08] text-violet-400 border-violet-500/20",
  },
};

/**
 * Small pill identifying which strategy produced a trade/position (FR-052/AC-016).
 * Rendered on trade rows and position cards so trend vs mean-reversion entries are
 * visually distinguishable at a glance. Default-off feature data: existing rows are
 * all "trend" (migration-44 backfill), so this reads as a no-op chip until F2 runs.
 */
export const StrategyChip = memo(function StrategyChip({ kind, direction, className }: StrategyChipProps) {
  const s = STYLES[kind] ?? STYLES.trend;
  return (
    <span
      data-testid="strategy-chip"
      data-kind={kind}
      title={kind === "mean_reversion" ? "Mean-reversion entry (fades range extremes)" : "Trend entry"}
      className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wider border ${s.cls} ${className ?? ""}`}
    >
      {s.label}
      {direction ? (
        <span data-testid="strategy-chip-direction" className="opacity-70 normal-case tracking-normal">
          {direction === "long" ? "▲ long" : "▼ short"}
        </span>
      ) : null}
    </span>
  );
});
