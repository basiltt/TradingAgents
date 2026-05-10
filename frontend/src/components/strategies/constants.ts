import type { StrategyCategory, StrategyStatus } from "@/api/client";

export const CATEGORIES: StrategyCategory[] = [
  "scalping", "intraday", "swing", "positional", "grid", "dca", "hedging", "arbitrage",
];

export const STATUSES: StrategyStatus[] = ["active", "paused", "archived", "draft"];

export const STATUS_COLORS: Record<StrategyStatus, string> = {
  active: "bg-green-500/20 text-green-400",
  paused: "bg-yellow-500/20 text-yellow-400",
  archived: "bg-zinc-500/20 text-zinc-400",
  draft: "bg-blue-500/20 text-blue-400",
};

export const CATEGORY_COLORS: Record<StrategyCategory, string> = {
  scalping: "bg-red-500/20 text-red-400",
  intraday: "bg-orange-500/20 text-orange-400",
  swing: "bg-emerald-500/20 text-emerald-400",
  positional: "bg-cyan-500/20 text-cyan-400",
  grid: "bg-purple-500/20 text-purple-400",
  dca: "bg-pink-500/20 text-pink-400",
  hedging: "bg-amber-500/20 text-amber-400",
  arbitrage: "bg-indigo-500/20 text-indigo-400",
};
