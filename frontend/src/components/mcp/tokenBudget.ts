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

/**
 * Classifies a selected token count against a budget into a traffic-light tone.
 * @param selected - Tokens currently selected.
 * @param budget - Budget ceiling; treated as 0 ratio when not positive.
 * @returns "over" above the budget, "caution" above 75%, otherwise "safe".
 */
export function tokenTone(selected: number, budget: number): BudgetTone {
  const ratio = budget > 0 ? selected / budget : 0;
  if (ratio > 1) return "over";
  if (ratio > 0.75) return "caution";
  return "safe";
}

/**
 * Compactly formats a token count, using a "k" suffix at/above 1000.
 * @param n - Token count to format.
 * @returns Raw number under 1000; otherwise "Nk" (no decimal at/above 10k, one decimal below).
 */
export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}
