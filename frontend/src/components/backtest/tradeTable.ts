/**
 * Pure, framework-free helpers for the trade list table: sorting, filtering,
 * and CSV export. Extracted so the data logic is unit-testable without rendering.
 */
import type { BacktestTrade } from "./types";

export type TradeSortKey =
  | "entry_time"
  | "exit_time"
  | "symbol"
  | "side"
  | "pnl"
  | "pnl_pct"
  | "close_reason";

export type SortDirection = "asc" | "desc";

export interface TradeFilters {
  side?: "all" | "long" | "short";
  closeReason?: string | "all";
  outcome?: "all" | "win" | "loss";
  search?: string;
}

/** Map a raw side string to a normalized long/short bucket. */
export function normalizeSide(side: string | null | undefined): "long" | "short" | "other" {
  if (!side) return "other";
  const s = side.toLowerCase();
  if (s === "buy" || s === "long") return "long";
  if (s === "sell" || s === "short") return "short";
  return "other";
}

/** Apply filters to a trade list (does not mutate input). */
export function filterTrades(trades: BacktestTrade[], filters: TradeFilters): BacktestTrade[] {
  const search = filters.search?.trim().toLowerCase();
  return trades.filter((t) => {
    if (filters.side && filters.side !== "all") {
      if (normalizeSide(t.side) !== filters.side) return false;
    }
    if (filters.closeReason && filters.closeReason !== "all") {
      if ((t.close_reason ?? "") !== filters.closeReason) return false;
    }
    if (filters.outcome && filters.outcome !== "all") {
      const pnl = t.pnl ?? 0;
      if (filters.outcome === "win" && pnl <= 0) return false;
      if (filters.outcome === "loss" && pnl >= 0) return false;
    }
    if (search) {
      if (!t.symbol.toLowerCase().includes(search)) return false;
    }
    return true;
  });
}

function compareValues(a: unknown, b: unknown): number {
  // Nulls sort last regardless of direction-applied sign.
  const aNull = a == null;
  const bNull = b == null;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

/** Sort a trade list by key + direction (does not mutate input). */
export function sortTrades(
  trades: BacktestTrade[],
  key: TradeSortKey,
  direction: SortDirection,
): BacktestTrade[] {
  const sorted = [...trades].sort((a, b) => {
    const cmp = compareValues(a[key], b[key]);
    // Keep nulls last: compareValues already returns ±1 for null operands;
    // only flip the sign for non-null comparisons.
    if (a[key] == null || b[key] == null) return cmp;
    return direction === "asc" ? cmp : -cmp;
  });
  return sorted;
}

/** Compute the running cumulative PnL for an (already ordered) trade list. */
export function withCumulativePnl(
  trades: BacktestTrade[],
): Array<BacktestTrade & { cumulative_pnl: number }> {
  let running = 0;
  return trades.map((t) => {
    running += t.pnl ?? 0;
    return { ...t, cumulative_pnl: running };
  });
}

/** Slice a list into a page (1-based page index). */
export function paginate<T>(items: T[], page: number, pageSize: number): T[] {
  const start = (page - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

const CSV_COLUMNS: Array<{ key: keyof BacktestTrade; label: string }> = [
  { key: "symbol", label: "Symbol" },
  { key: "side", label: "Side" },
  { key: "entry_time", label: "Entry Time" },
  { key: "exit_time", label: "Exit Time" },
  { key: "entry_price", label: "Entry Price" },
  { key: "exit_price", label: "Exit Price" },
  { key: "qty", label: "Qty" },
  { key: "leverage", label: "Leverage" },
  { key: "pnl", label: "PnL" },
  { key: "pnl_pct", label: "PnL %" },
  { key: "fees_paid", label: "Fees" },
  { key: "close_reason", label: "Close Reason" },
  { key: "mfe_pct", label: "MFE %" },
  { key: "mae_pct", label: "MAE %" },
  { key: "signal_score", label: "Signal Score" },
  { key: "signal_confidence", label: "Signal Confidence" },
  { key: "strategy_kind", label: "Strategy" },
];

/** Escape a single CSV cell per RFC 4180 (quote if it contains ,"\n) AND
 * neutralize spreadsheet formula injection: a string cell starting with
 * = + - @ (or tab/CR) is prefixed with a single quote so Excel/Sheets/LibreOffice
 * treat it as text rather than executing it. Numeric cells are left intact so
 * legitimate negative numbers (e.g. -123.45) are not mangled. */
export function csvCell(value: unknown): string {
  if (value == null) return "";
  let str = String(value);
  if (typeof value !== "number" && /^[=+\-@\t\r]/.test(str)) {
    str = `'${str}`;
  }
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/** Build a CSV string from trades (header + one row per trade). */
export function tradesToCsv(trades: BacktestTrade[]): string {
  const header = CSV_COLUMNS.map((c) => csvCell(c.label)).join(",");
  const rows = trades.map((t) =>
    CSV_COLUMNS.map((c) => csvCell(t[c.key])).join(","),
  );
  return [header, ...rows].join("\r\n");
}
