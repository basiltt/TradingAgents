/**
 * Display formatters for backtest metrics. Kept pure + framework-free so they
 * can be unit-tested and reused across the metrics grid, charts, and trade table.
 *
 * Every formatter handles null/undefined (→ "N/A" or "—") because the metrics
 * payload deliberately uses null for undefined values (e.g. profit_factor with
 * no losses, sharpe with <2 data points).
 */

export const NA = "N/A";
export const DASH = "—";

/** Shared table-header cell classes (kept here so the ~dozen header cells across
 * the metrics/list/compare/trade tables stay visually consistent). */
export const TH_CLASS =
  "text-[0.72rem] font-semibold uppercase tracking-wide text-[var(--neu-text-muted)]";
export const TH_CLASS_RIGHT = `${TH_CLASS} text-right`;

/** Format a USD amount: $1,234.56, with sign for non-zero. */
export function formatUsd(value: number | null | undefined, opts?: { sign?: boolean }): string {
  if (value == null || !Number.isFinite(value)) return NA;
  const sign = opts?.sign && value > 0 ? "+" : "";
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? "-" : sign}$${formatted}`;
}

/** Format a percentage: 12.34%, with optional sign. */
export function formatPct(
  value: number | null | undefined,
  opts?: { sign?: boolean; digits?: number },
): string {
  if (value == null || !Number.isFinite(value)) return NA;
  const digits = opts?.digits ?? 2;
  const sign = opts?.sign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

/** Format a ratio (sharpe, profit factor, calmar): 2.34, or ∞ for null-with-no-losses. */
export function formatRatio(
  value: number | null | undefined,
  opts?: { infinite?: boolean; digits?: number },
): string {
  if (value == null || !Number.isFinite(value)) {
    return opts?.infinite ? "∞" : NA;
  }
  return value.toFixed(opts?.digits ?? 2);
}

/** Format a duration in hours: 1.5h, 26h, or "2d 4h" for long spans. */
export function formatHours(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return NA;
  if (value < 24) return `${value.toFixed(1)}h`;
  // Round to whole hours first so the day/hour split can't produce "1d 24h".
  const totalHours = Math.round(value);
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
}

/** Compact local-agnostic date-time label: "YYYY-MM-DD HH:mm" or em dash. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return iso.replace("T", " ").slice(0, 16);
}

/** Plain integer with thousands separators. */
export function formatInt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return NA;
  return Math.round(value).toLocaleString("en-US");
}

/** Friendly labels for engine close-reason codes (raw code shown for any unknown
 * code so nothing is silently hidden). Keeps the trade list + filter readable. */
const CLOSE_REASON_LABELS: Record<string, string> = {
  tp: "Take Profit",
  sl: "Stop Loss",
  liquidation: "Liquidation",
  max_duration: "Max Duration",
  mr_time_stop: "MR Time Stop",
  trailing_profit: "Trailing Profit",
  breakeven: "Closed at Breakeven",
  equity_drop: "Equity Drop",
  equity_rise: "Equity Rise",
  backtest_end: "Backtest End",
};

export function formatCloseReason(code: string | null | undefined): string {
  if (!code) return DASH;
  return CLOSE_REASON_LABELS[code] ?? code.replace(/_/g, " ");
}

/** Sign of a value for color coding: "pos" | "neg" | "zero". */
export function signOf(value: number | null | undefined): "pos" | "neg" | "zero" {
  if (value == null || !Number.isFinite(value) || value === 0) return "zero";
  return value > 0 ? "pos" : "neg";
}

/** Tailwind text-color class for a P&L-style value. */
export function pnlColorClass(value: number | null | undefined): string {
  const s = signOf(value);
  if (s === "pos") return "text-emerald-500";
  if (s === "neg") return "text-rose-500";
  return "text-muted-foreground";
}

/** Explicit P&L color classes, for cases where the value's sign is fixed by
 * meaning (drawdown/commission/gross-loss are always costs; gross-profit is
 * always a gain) so we colorize without inspecting the runtime sign. */
export const PNL_NEGATIVE_CLASS = "text-rose-500";
export const PNL_POSITIVE_CLASS = "text-emerald-500";
