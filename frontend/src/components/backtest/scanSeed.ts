/**
 * Build a backtest seed config from scanner data, for the "Backtest These
 * Settings" entry points. Pure + framework-free so the mapping is testable.
 *
 * The seed is a Partial<BacktestCreateRequest> that pre-fills the new-backtest
 * form; the user still reviews/adjusts capital, TP/SL, leverage, etc.
 */
import type { BacktestCreateRequest } from "./types";

/** A completed scan's relevant fields (subset of the ScanStatus API shape). */
export interface ScanSeedInput {
  scan_id: string;
  started_at?: string | null;
  completed_at?: string | null;
}

/**
 * Seed from a single completed scan: a date-range window bracketing the scan's
 * run time. We widen to a sensible default window (the scan day → now) so the
 * backtest has data to simulate over, since one scan is a point-in-time signal.
 */
export function scanToBacktestSeed(scan: ScanSeedInput): Partial<BacktestCreateRequest> {
  const seed: Partial<BacktestCreateRequest> = {
    scan_source: { mode: "date_range" },
  };
  // Anchor the window start at the scan's start (fallback completed_at), if valid.
  const anchor = scan.started_at ?? scan.completed_at ?? null;
  if (anchor) {
    const start = new Date(anchor);
    if (!Number.isNaN(start.getTime())) {
      seed.date_range_start = start.toISOString();
      // End: 30 days after the scan, but never in the future would require "now";
      // leave end unset so the form fills its default (now) — simpler + always valid.
    }
  }
  return seed;
}

/** Seed from a scheduled scan: replays all of that schedule's historical scans. */
export function scheduleToBacktestSeed(scheduleId: string): Partial<BacktestCreateRequest> {
  return {
    scan_source: { mode: "schedule", schedule_id: scheduleId },
  };
}

/** Serialize a seed for the `?seed=` search param consumed by /backtest/new. */
export function encodeSeedParam(seed: Partial<BacktestCreateRequest>): string {
  return JSON.stringify(seed);
}
