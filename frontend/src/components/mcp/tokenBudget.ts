/**
 * Pure helpers for the context-token budget meter. Kept separate from the
 * TokenMeter component so the component file only exports a component (Vite
 * fast-refresh requirement / react-refresh lint rule).
 */

/** Reference context budgets (tokens) the operator can compare against. */
export const CONTEXT_BUDGETS: Record<string, number> = {
  "Tight (8k tool budget)": 8_000,
  "Comfortable (16k)": 16_000,
  "Generous (32k)": 32_000,
};

export type BudgetTone = "safe" | "caution" | "over";

export function tokenTone(selected: number, budget: number): BudgetTone {
  const ratio = budget > 0 ? selected / budget : 0;
  if (ratio > 1) return "over";
  if (ratio > 0.75) return "caution";
  return "safe";
}

export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}
