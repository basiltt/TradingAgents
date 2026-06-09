/**
 * @module decayAlerts
 *
 * Data types and side-effect helper for signal-decay alerts.
 *
 * Architectural role: the alert shape, the acknowledge API call, and severity
 * styling extracted from {@link ../DecayAlertBanner} so the component file exports
 * only a component (React Fast Refresh / `react-refresh/only-export-components`).
 *
 * Boundary: `acknowledgeAlert` performs a network POST; `severityClass` is pure.
 * The component imports both from here.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * A signal-decay alert raised by the backend monitoring.
 *
 * @property id - Stable alert id (used to acknowledge/dismiss).
 * @property alert_type - Machine slug (e.g. `"win_rate_drop"`); underscores are
 *   humanized for display.
 * @property severity - One of `"critical" | "warning" | …`; drives styling.
 * @property message - Human-readable description of the decay condition.
 * @property created_at - ISO-8601 timestamp the alert was raised.
 */
export interface DecayAlert {
  id: number;
  alert_type: string;
  severity: string;
  message: string;
  created_at: string;
}

/**
 * Map an alert severity to its Tailwind class string.
 *
 * @param severity - The alert severity (case-insensitive).
 * @returns Border/background/text classes for the banner; a neutral default for
 *   unrecognized severities.
 */
export function severityClass(severity: string): string {
  switch (severity.toLowerCase()) {
    case "critical":
      return "border-destructive/40 bg-destructive/8 text-destructive";
    case "warning":
      return "border-amber-500/40 bg-amber-500/8 text-amber-700 dark:text-amber-400";
    default:
      return "border-border/60 bg-card/70 text-foreground";
  }
}

/**
 * Acknowledge (dismiss) a decay alert on the server.
 *
 * @param id - The alert id to acknowledge.
 * @returns A promise that resolves when the POST completes.
 *
 * @remarks Side effect: issues `POST /api/v1/signal-analytics/decay-alerts/:id/acknowledge`.
 *   Does not throw on non-2xx (fire-and-forget from the banner); callers that need
 *   failure handling should inspect the response themselves.
 */
export async function acknowledgeAlert(id: number): Promise<void> {
  await fetch(`${BASE_URL}/api/v1/signal-analytics/decay-alerts/${id}/acknowledge`, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
}
