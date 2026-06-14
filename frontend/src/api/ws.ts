/**
 * Shared WebSocket helpers (TASK-1.5 / R176 / NFR-012).
 *
 * The `wss?://host` base resolver was copy-pasted across several hooks; this is
 * the single source new code consumes. (Legacy hooks may be migrated later — see
 * the plan's follow-up note.)
 */

/** Resolve the WS origin: an explicit override, else same-origin (wss when https). */
export function wsBaseUrl(): string {
  return (
    import.meta.env.VITE_WS_BASE_URL ||
    `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
  );
}

export const RECONNECT_BASE_MS = 1500;
export const RECONNECT_MAX_MS = 8000;

/** WS close codes the client must treat as PERMANENT (no reconnect). */
const PERMANENT_CLOSE_CODES = new Set<number>([
  1000, // normal close (e.g. server's clean close for an unknown/terminal scan)
  4403, // origin rejected
  4404, // invalid id / not found
  1011, // server has no manager (won't recover by reconnecting)
]);

/** True when a close code is transient and a reconnect should be attempted. */
export function shouldReconnect(code: number | undefined): boolean {
  if (code === undefined) return true; // unknown -> be optimistic (likely 1006)
  return !PERMANENT_CLOSE_CODES.has(code);
}
