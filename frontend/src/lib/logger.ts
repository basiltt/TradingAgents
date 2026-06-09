/**
 * @module logger
 *
 * Centralized client-side logger and error-reporting seam.
 *
 * Architectural role: the single place the frontend emits diagnostics. Replaces
 * scattered `console.*` calls so that (a) log scope/format is consistent, (b)
 * `debug`/`info` are silenced in production builds to avoid console noise and
 * accidental data exposure, and (c) there is ONE hook point to wire a real
 * error-reporting backend (Sentry, Datadog RUM, etc.) later without touching every
 * call site — see {@link setErrorReporter}.
 *
 * Boundary: writes to `console` and, when configured, forwards errors/warnings to a
 * reporter. Holds module-level reporter state but no other application state.
 *
 * SECURITY: never pass secrets, tokens, API keys, or full request bodies to the
 * logger. Log identifiers and messages, not credentials.
 */

/** Severity levels, ordered least → most severe. */
export type LogLevel = "debug" | "info" | "warn" | "error";

/**
 * A pluggable sink for warnings and errors (e.g. Sentry). Receives the level, a
 * scoped message, and any structured context the caller passed.
 */
export type ErrorReporter = (
  level: "warn" | "error",
  message: string,
  context?: Record<string, unknown>,
) => void;

// AI-CONTEXT: import.meta.env.DEV is statically replaced by Vite at build time, so
// the dev-only branches below are tree-shaken out of production bundles entirely.
const IS_DEV = import.meta.env.DEV;

let errorReporter: ErrorReporter | null = null;

/**
 * Register a reporter to receive all `warn`/`error` logs (typically once at app
 * startup). Passing `null` detaches the current reporter.
 *
 * @param reporter - The sink to forward warnings/errors to, or null to detach.
 *
 * @example
 * setErrorReporter((level, msg, ctx) => Sentry.captureMessage(msg, { level, extra: ctx }));
 */
export function setErrorReporter(reporter: ErrorReporter | null): void {
  errorReporter = reporter;
}

/** Build the `[scope] message` prefix used by every level. */
function format(scope: string, message: string): string {
  return `[${scope}] ${message}`;
}

/**
 * Scoped logger.
 *
 * `debug` and `info` are no-ops in production (dev-only diagnostics). `warn` and
 * `error` always reach the console AND the registered {@link ErrorReporter}, so
 * production failures are observable even though the console is quiet by default.
 *
 * @example
 * logger.warn("useAccountPolling", "poll failed", { message: err.message });
 * logger.error("TradeActions", "close failed", { tradeId, status });
 */
export const logger = {
  /**
   * Dev-only verbose diagnostic. Stripped from production builds.
   * @param scope - Short module/feature tag, e.g. "useAccountWebSocket".
   * @param message - Human-readable message (no secrets).
   * @param context - Optional structured context.
   */
  debug(scope: string, message: string, context?: Record<string, unknown>): void {
    if (IS_DEV) console.debug(format(scope, message), context ?? "");
  },

  /**
   * Dev-only informational message (state transitions, lifecycle). Stripped from prod.
   * @param scope - Short module/feature tag.
   * @param message - Human-readable message (no secrets).
   * @param context - Optional structured context.
   */
  info(scope: string, message: string, context?: Record<string, unknown>): void {
    if (IS_DEV) console.info(format(scope, message), context ?? "");
  },

  /**
   * Degraded-but-recoverable condition (retry, fallback, swallowed-but-notable
   * error). Always logged; forwarded to the error reporter if one is registered.
   * @param scope - Short module/feature tag.
   * @param message - Human-readable message (no secrets).
   * @param context - Optional structured context (ids, status codes — never tokens).
   */
  warn(scope: string, message: string, context?: Record<string, unknown>): void {
    console.warn(format(scope, message), context ?? "");
    errorReporter?.("warn", format(scope, message), context);
  },

  /**
   * A real failure. Always logged; forwarded to the error reporter if registered.
   * @param scope - Short module/feature tag.
   * @param message - Human-readable message (no secrets).
   * @param context - Optional structured context (ids, status codes — never tokens).
   */
  error(scope: string, message: string, context?: Record<string, unknown>): void {
    console.error(format(scope, message), context ?? "");
    errorReporter?.("error", format(scope, message), context);
  },
} as const;
