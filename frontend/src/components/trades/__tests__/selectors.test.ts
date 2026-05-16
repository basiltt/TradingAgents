import { describe, it, expect } from "vitest";
import { selectActiveTradeAggregates, selectActiveTradesList } from "../selectors";

function makeState(trades: Record<string, any>) {
  return {
    trades: { activeTrades: trades, lastUpdated: null },
  } as any;
}

describe("selectActiveTradesList", () => {
  it("returns array of trade values", () => {
    const state = makeState({ a: { id: "a" }, b: { id: "b" } });
    expect(selectActiveTradesList(state)).toHaveLength(2);
  });

  it("returns empty array for no trades", () => {
    expect(selectActiveTradesList(makeState({}))).toEqual([]);
  });
});

describe("selectActiveTradeAggregates", () => {
  it("returns zeros for empty trades", () => {
    const result = selectActiveTradeAggregates(makeState({}));
    expect(result).toEqual({
      tradeCount: 0,
      totalRealizedPnl: 0,
      totalUnrealizedPnl: 0,
      totalPnl: 0,
    });
  });

  it("sums realized and unrealized PnL", () => {
    const state = makeState({
      a: { realized_pnl: 100, unrealized_pnl: 50 },
      b: { realized_pnl: -30, unrealized_pnl: 20 },
    });
    const result = selectActiveTradeAggregates(state);
    expect(result.tradeCount).toBe(2);
    expect(result.totalRealizedPnl).toBe(70);
    expect(result.totalUnrealizedPnl).toBe(70);
    expect(result.totalPnl).toBe(140);
  });

  it("skips null PnL fields", () => {
    const state = makeState({
      a: { realized_pnl: null, unrealized_pnl: 50 },
      b: { realized_pnl: 100, unrealized_pnl: null },
    });
    const result = selectActiveTradeAggregates(state);
    expect(result.totalRealizedPnl).toBe(100);
    expect(result.totalUnrealizedPnl).toBe(50);
  });
});
