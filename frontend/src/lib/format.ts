/**
 * @module format
 *
 * Display-formatting helpers for durations and date-times.
 *
 * Architectural role: pure presentation utilities shared across the app for turning
 * numbers/timestamps into human-readable strings. All functions are defensive
 * against non-finite numbers and unparseable dates (returning a fallback rather than
 * "NaNs" / "Invalid Date"), so a single bad value never corrupts the UI.
 *
 * Boundary: pure functions — no DOM, no I/O, no state.
 */

/**
 * Convert milliseconds to a human-readable duration string (e.g. "1h 23m 45s").
 *
 * @param ms - Duration in milliseconds. Non-finite (NaN/Infinity) or negative
 *   inputs are treated as zero ("0s") rather than producing "NaNm" / "-1s" garbage.
 * @returns The formatted duration, or "0s" for invalid/negative input.
 */
export function formatDuration(ms: number): string {
  // AI-CONTEXT: Guard non-finite/negative up front. formatDuration is exported and
  // some callers (formatDurationBetween) pass computed deltas that can be NaN
  // (unparseable timestamps) or negative (clock skew); without this guard the
  // modulo math yields "Infinityh NaNm NaNs" or "-1s".
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/**
 * Compute duration between two ISO timestamps and format as a readable string.
 * If completedAt is null, uses Date.now() as the end time.
 */
export function formatDurationBetween(
  startedAt: string,
  completedAt: string | null,
  fallback = "—",
): string {
  if (!startedAt) return fallback;
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  // AI-CONTEXT: A malformed (non-empty but unparseable) timestamp yields NaN from
  // getTime(); Math.max(0, NaN) is NaN, which would render "NaNs". Return the
  // fallback instead so a bad timestamp degrades gracefully.
  if (!Number.isFinite(start) || !Number.isFinite(end)) return fallback;
  return formatDuration(Math.max(0, end - start));
}

/**
 * Format an ISO timestamp as a localized date-time string.
 *
 * Centralizes the `new Date(iso).toLocaleString(...)` pattern (with null/empty
 * guard and parse-failure fallback) that scanner pages hand-rolled. Defaults to a
 * "MMM D, YYYY, HH:MM" style; pass `opts` to override (e.g. drop the year).
 *
 * @param iso - The ISO-8601 timestamp, or null/undefined.
 * @param opts - Optional `Intl.DateTimeFormat` options to override the default
 *   `{ month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }`.
 * @param fallback - String returned when `iso` is null/empty. Defaults to `"—"`.
 * @returns The formatted local date-time, the `fallback` for empty input, or the
 *   raw `iso` when it cannot be parsed/formatted.
 *
 * @example
 * formatDateTimeLabel("2026-01-05T14:30:00Z");
 * // "Jan 5, 2026, 02:30 PM" (locale-dependent)
 * formatDateTimeLabel(null);            // "—"
 * formatDateTimeLabel("", undefined, "never"); // "never"
 */
export function formatDateTimeLabel(
  iso: string | null | undefined,
  opts?: Intl.DateTimeFormatOptions,
  fallback = "—",
): string {
  if (!iso) return fallback;
  // AI-CONTEXT: new Date("garbage").toLocaleString() does NOT throw — it returns the
  // literal "Invalid Date". Check the parsed time explicitly so an unparseable input
  // returns the raw iso (the documented graceful fallback) instead of "Invalid Date".
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  try {
    return parsed.toLocaleString(undefined, opts ?? {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ── Metric/display formatters (merged from components/backtest/format.ts) ─────
// Pure + framework-free so they can be unit-tested and reused across the metrics
// grid, charts, trade tables, and the Performance dashboard. Every formatter
// handles null/undefined (→ "N/A" or "—") because metric payloads deliberately
// use null for undefined values (e.g. profit_factor with no losses, sharpe with
// <10 trading days).

export const NA = "N/A";
export const DASH = "—";

/** Shared table-header cell classes (kept here so header cells across the
 * metrics/list/compare/trade tables stay visually consistent). */
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

/** Compact locale-agnostic date-time label: "YYYY-MM-DD HH:mm" or em dash.
 * (Distinct from formatDateTimeLabel above, which is locale-aware.) */
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
 * code so nothing is silently hidden). */
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
