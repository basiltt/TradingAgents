/**
 * Format an ISO timestamp as a short localized date-time (e.g. `Jun 9, 2026, 02:30 PM`).
 * @param iso - ISO date string, or `null`/`undefined`.
 * @returns The formatted string; an em dash (`"—"`) when input is empty, or the raw input if it can't be parsed.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

/** Whether a cycle status represents in-flight work (pending/placing_trades/running/stopping) vs. a terminal state. */
export function isActive(status: string): boolean {
  return ["pending", "placing_trades", "running", "stopping"].includes(status);
}
