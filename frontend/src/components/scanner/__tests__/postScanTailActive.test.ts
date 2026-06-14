import { describe, it, expect } from "vitest";

import { postScanTailActive } from "../ScannerPage";
import type { ScanStatus } from "@/api/client";

function scan(p: Partial<ScanStatus>): ScanStatus {
  return {
    scan_id: "s",
    status: "completed",
    total: 1,
    completed: 1,
    failed: 0,
    current_batch: 0,
    total_batches: 1,
    current_tickers: [],
    results: [],
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    auto_trade_config_count: 1,
    ...p,
  } as ScanStatus;
}

describe("postScanTailActive", () => {
  it("false for undefined", () => {
    expect(postScanTailActive(undefined)).toBe(false);
  });

  it("false without auto-trade configs", () => {
    expect(postScanTailActive(scan({ auto_trade_config_count: 0 }))).toBe(false);
  });

  it("false once summaries have landed", () => {
    expect(
      postScanTailActive(scan({ auto_trade_summaries: [{ account_id: "a", trades_executed: 1, trades_failed: 0, trades_skipped: 0 }] })),
    ).toBe(false);
  });

  it("false while still running (not yet terminal)", () => {
    expect(postScanTailActive(scan({ status: "running" }))).toBe(false);
  });

  it("true: terminal + configured + no summaries + recent", () => {
    expect(postScanTailActive(scan({ status: "completed" }))).toBe(true);
  });

  it("false past the elapsed cap", () => {
    const old = new Date(Date.now() - 20 * 60 * 1000).toISOString();
    expect(postScanTailActive(scan({ completed_at: old, started_at: old }))).toBe(false);
  });

  it("false when completed_at and started_at are both unusable", () => {
    expect(postScanTailActive(scan({ completed_at: null, started_at: "" }))).toBe(false);
  });

  it("falls back to started_at when completed_at is null", () => {
    expect(postScanTailActive(scan({ completed_at: null, started_at: new Date().toISOString() }))).toBe(true);
  });
});
