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
