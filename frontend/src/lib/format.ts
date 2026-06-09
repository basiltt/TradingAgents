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
