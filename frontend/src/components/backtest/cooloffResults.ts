/**
 * @module cooloffResults
 *
 * Pure transforms for the backtest results cool-off telemetry. Kept separate from
 * BacktestResultsPage (the component) so the defensive parsing is unit-testable in
 * isolation and the component file exports only a component (React Fast Refresh).
 *
 * The backtest engine writes cool-off telemetry into `results.summary` (the
 * persisted filter_stats) ONLY when at least one cool-off tier was enabled for the
 * run — a backtest with cool-off OFF omits these keys entirely, so the UI renders
 * exactly as it did before the feature existed.
 */
import type { CooloffBand } from "./equityCurveData";
import type { CooloffReason } from "../scanner/cooloffTiers";

/** Human labels for the four cool-off tiers (the `reason` enum the engine emits).
 * Unknown reasons fall back to a de-underscored form so nothing is silently dropped. */
export const COOLOFF_REASON_LABELS: Record<CooloffReason, string> = {
  success: "Success",
  failure: "Failure",
  double_success: "Double success",
  double_failure: "Double failure",
};

export function cooloffReasonLabel(reason: string): string {
  return (COOLOFF_REASON_LABELS as Record<string, string>)[reason] ?? reason.replace(/_/g, " ");
}

/** Normalized cool-off telemetry pulled out of `results.summary`. */
export interface CooloffTelemetry {
  /** Total signals the cool-off gate skipped across the run. */
  signalsSkipped: number;
  /** Skipped-signal counts keyed by arming reason, descending by count. */
  byReason: Array<{ reason: string; count: number }>;
  /** Pause windows for the equity-curve shading. */
  bands: CooloffBand[];
  /** True when the cool-off keys exist in the summary (a tier was enabled for the run). */
  present: boolean;
  /** True when there is something worth showing (a skip, a band, or a reason count).
   * A tier enabled but never triggered yields present=true / hasContent=false, so the
   * summary strip stays hidden rather than rendering an empty "0 signals skipped" row. */
  hasContent: boolean;
}

/** Pull cool-off telemetry out of the loosely-typed `results.summary` blob. Every
 * field is validated defensively: a missing/garbled summary yields a present=false
 * record so the UI renders exactly as it did before the feature existed. */
export function extractCooloff(summary: Record<string, unknown> | undefined): CooloffTelemetry {
  const empty: CooloffTelemetry = {
    signalsSkipped: 0,
    byReason: [],
    bands: [],
    present: false,
    hasContent: false,
  };
  if (!summary || typeof summary !== "object") return empty;

  const hasSkip = "cooloff_signals_skipped" in summary;
  const hasBands = "cooloff_bands" in summary;
  if (!hasSkip && !hasBands) return empty;

  const rawSkipped = summary["cooloff_signals_skipped"];
  const signalsSkipped =
    typeof rawSkipped === "number" && Number.isFinite(rawSkipped) && rawSkipped > 0
      ? Math.trunc(rawSkipped)
      : 0;

  const rawByReason = summary["cooloff_skipped_by_reason"];
  const byReason: Array<{ reason: string; count: number }> = [];
  if (rawByReason && typeof rawByReason === "object" && !Array.isArray(rawByReason)) {
    for (const [reason, value] of Object.entries(rawByReason as Record<string, unknown>)) {
      if (typeof value === "number" && Number.isFinite(value) && value > 0) {
        byReason.push({ reason, count: Math.trunc(value) });
      }
    }
    byReason.sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
  }

  const rawBands = summary["cooloff_bands"];
  const bands: CooloffBand[] = [];
  if (Array.isArray(rawBands)) {
    for (const b of rawBands) {
      if (
        b &&
        typeof b === "object" &&
        typeof (b as CooloffBand).start === "string" &&
        typeof (b as CooloffBand).end === "string"
      ) {
        const rec = b as Record<string, unknown>;
        bands.push({
          start: rec.start as string,
          end: rec.end as string,
          reason: typeof rec.reason === "string" ? rec.reason : "unknown",
        });
      }
    }
  }

  return {
    signalsSkipped,
    byReason,
    bands,
    present: hasSkip || hasBands,
    hasContent: signalsSkipped > 0 || bands.length > 0 || byReason.length > 0,
  };
}
