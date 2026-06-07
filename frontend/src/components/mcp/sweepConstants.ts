/** Shared optimizer constants (kept out of component files for fast-refresh). */
export const OBJECTIVE_OPTIONS = [
  "total_return",
  "sharpe",
  "sortino",
  "max_drawdown",
  "win_rate",
  "profit_factor",
  "expectancy",
  "calmar",
] as const;
