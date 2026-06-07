/**
 * TokenMeter — a horizontal bar visualizing how much of the model's context
 * window the currently-selected tools consume. This is the visual anchor of the
 * whole console: the user's stated concern is that enabling every tool fills the
 * model's context, so the meter turns "selected token estimate vs a reference
 * budget" into an at-a-glance safe / caution / over-budget signal.
 *
 * Pure helpers (CONTEXT_BUDGETS, tokenTone, formatTokens) live in ./tokenBudget
 * so this file exports only a component (fast-refresh requirement).
 */
import { cn } from "@/lib/utils";
import { type BudgetTone, formatTokens, tokenTone } from "./tokenBudget";

const TONE_CLASS: Record<BudgetTone, string> = {
  safe: "bg-[var(--neu-accent)]",
  caution: "bg-warning",
  over: "bg-destructive",
};

export function TokenMeter({
  selected,
  total,
  budget,
  className,
}: {
  selected: number;
  total: number;
  budget: number;
  className?: string;
}) {
  const tone = tokenTone(selected, budget);
  const pct = budget > 0 ? Math.min(100, (selected / budget) * 100) : 0;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold text-[var(--neu-text-strong)]">
          {formatTokens(selected)} tokens selected
        </span>
        <span className="text-[var(--neu-text-muted)]">
          of {formatTokens(budget)} budget · {formatTokens(total)} if all enabled
        </span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-[var(--neu-surface-inset)]">
        <div
          className={cn("absolute inset-y-0 left-0 rounded-full transition-all duration-300", TONE_CLASS[tone])}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={selected}
          aria-valuemin={0}
          aria-valuemax={budget}
        />
      </div>
      {tone === "over" ? (
        <p className="text-[11px] font-medium text-destructive">
          Over budget — this many tools may overflow the model's context. Disable some groups.
        </p>
      ) : tone === "caution" ? (
        <p className="text-[11px] font-medium text-warning">
          Approaching the budget. Consider trimming rarely-used tools.
        </p>
      ) : null}
    </div>
  );
}
