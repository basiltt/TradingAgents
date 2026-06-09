/**
 * Convert milliseconds to a human-readable duration string (e.g. "1h 23m 45s").
 */
export function formatDuration(ms: number): string {
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
  const diff = Math.max(
    0,
    (completedAt ? new Date(completedAt).getTime() : Date.now()) -
      new Date(startedAt).getTime(),
  );
  return formatDuration(diff);
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
  try {
    return new Date(iso).toLocaleString(undefined, opts ?? {
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
