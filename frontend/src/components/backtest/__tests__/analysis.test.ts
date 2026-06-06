import { describe, it, expect } from "vitest";
import {
  aggregateMonthlyReturns,
  buildHistogram,
  pnlHistogram,
  tradeDurationHours,
  durationHistogram,
} from "../analysis";
import type { BacktestTrade } from "../types";

function trade(overrides: Partial<BacktestTrade> = {}): BacktestTrade {
  return {
    id: 1,
    symbol: "BTCUSDT",
    side: "buy",
    entry_price: 100,
    exit_price: 110,
    qty: 1,
    leverage: 5,
    entry_time: "2026-01-01T00:00:00Z",
    exit_time: "2026-01-01T04:00:00Z",
    pnl: 50,
    pnl_pct: 5,
    fees_paid: 1,
    close_reason: "take_profit",
    mfe_pct: 6,
    mae_pct: -1,
    signal_score: 80,
    signal_confidence: "high",
    scan_id: "scan-1",
    ...overrides,
  };
}

describe("aggregateMonthlyReturns", () => {
  it("groups by calendar month (UTC) and sums pnl", () => {
    const result = aggregateMonthlyReturns([
      trade({ exit_time: "2026-01-10T00:00:00Z", pnl: 100 }),
      trade({ exit_time: "2026-01-20T00:00:00Z", pnl: -40 }),
      trade({ exit_time: "2026-02-05T00:00:00Z", pnl: 200 }),
    ]);
    expect(result.cells).toHaveLength(2);
    expect(result.cells[0]).toMatchObject({ year: 2026, month: 1, pnl: 60, trades: 2 });
    expect(result.cells[1]).toMatchObject({ year: 2026, month: 2, pnl: 200, trades: 1 });
  });

  it("computes per-year totals and a sorted year list", () => {
    const result = aggregateMonthlyReturns([
      trade({ exit_time: "2025-12-31T00:00:00Z", pnl: 10 }),
      trade({ exit_time: "2026-01-01T00:00:00Z", pnl: 90 }),
    ]);
    expect(result.yearTotals).toEqual({ 2025: 10, 2026: 90 });
    expect(result.years).toEqual([2025, 2026]);
  });

  it("ignores trades with no exit_time", () => {
    const result = aggregateMonthlyReturns([trade({ exit_time: null, pnl: 999 })]);
    expect(result.cells).toHaveLength(0);
  });
});

describe("buildHistogram", () => {
  it("returns empty for no values", () => {
    expect(buildHistogram([])).toEqual([]);
  });
  it("buckets values into equal-width bins and counts each once", () => {
    const buckets = buildHistogram([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5);
    expect(buckets).toHaveLength(5);
    const total = buckets.reduce((s, b) => s + b.count, 0);
    expect(total).toBe(11); // every value counted exactly once
  });
  it("places the max value in the final (inclusive) bucket with exact counts", () => {
    const buckets = buildHistogram([0, 10], 2);
    expect(buckets).toHaveLength(2);
    // 0 → first bucket, 10 (the max) → final inclusive bucket. Exactly one each.
    expect(buckets[0].count).toBe(1);
    expect(buckets[1].count).toBe(1);
  });
  it("handles a single distinct value as one degenerate bucket", () => {
    const buckets = buildHistogram([5, 5, 5]);
    expect(buckets).toHaveLength(1);
    expect(buckets[0].count).toBe(3);
  });
  it("ignores non-finite values", () => {
    const buckets = buildHistogram([1, 2, Infinity, NaN, 3], 2);
    const total = buckets.reduce((s, b) => s + b.count, 0);
    expect(total).toBe(3);
  });
});

describe("pnlHistogram", () => {
  it("buckets per-trade pnl and skips null", () => {
    const buckets = pnlHistogram([
      trade({ pnl: -100 }),
      trade({ pnl: 0 }),
      trade({ pnl: 100 }),
      trade({ pnl: null }),
    ]);
    const total = buckets.reduce((s, b) => s + b.count, 0);
    expect(total).toBe(3);
  });
});

describe("tradeDurationHours", () => {
  it("computes hours between entry and exit", () => {
    expect(tradeDurationHours(trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T06:00:00Z" }))).toBe(6);
  });
  it("returns null when a timestamp is missing", () => {
    expect(tradeDurationHours(trade({ exit_time: null }))).toBeNull();
  });
  it("returns null for negative duration", () => {
    expect(tradeDurationHours(trade({ entry_time: "2026-01-02T00:00:00Z", exit_time: "2026-01-01T00:00:00Z" }))).toBeNull();
  });
});

describe("durationHistogram", () => {
  it("splits each bucket into win/loss counts", () => {
    const buckets = durationHistogram([
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T01:00:00Z", pnl: 50 }), // win, 1h
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T01:00:00Z", pnl: -50 }), // loss, 1h
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-02T00:00:00Z", pnl: 30 }), // win, 24h
    ]);
    const wins = buckets.reduce((s, b) => s + b.winCount, 0);
    const losses = buckets.reduce((s, b) => s + b.lossCount, 0);
    expect(wins).toBe(2);
    expect(losses).toBe(1);
  });
  it("returns empty when no trade has a measurable duration", () => {
    expect(durationHistogram([trade({ exit_time: null })])).toEqual([]);
  });
  it("classifies a break-even (pnl=0) trade as a winner, not a loser", () => {
    const buckets = durationHistogram([
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T01:00:00Z", pnl: 0 }),
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T02:00:00Z", pnl: -10 }),
    ]);
    const wins = buckets.reduce((s, b) => s + b.winCount, 0);
    const losses = buckets.reduce((s, b) => s + b.lossCount, 0);
    expect(wins).toBe(1); // pnl===0 counts as win (>= 0)
    expect(losses).toBe(1);
  });
  it("excludes trades with null pnl (consistent with the P&L histogram population)", () => {
    const buckets = durationHistogram([
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T01:00:00Z", pnl: null }),
      trade({ entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T02:00:00Z", pnl: 50 }),
    ]);
    const total = buckets.reduce((s, b) => s + b.winCount + b.lossCount, 0);
    expect(total).toBe(1); // null-pnl trade dropped
  });
});
