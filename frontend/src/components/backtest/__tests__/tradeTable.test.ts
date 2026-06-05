import { describe, it, expect } from "vitest";
import {
  normalizeSide,
  filterTrades,
  sortTrades,
  withCumulativePnl,
  paginate,
  pageCount,
  csvCell,
  tradesToCsv,
} from "../tradeTable";
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

describe("normalizeSide", () => {
  it("maps buy/long → long, sell/short → short", () => {
    expect(normalizeSide("buy")).toBe("long");
    expect(normalizeSide("LONG")).toBe("long");
    expect(normalizeSide("sell")).toBe("short");
    expect(normalizeSide("Short")).toBe("short");
    expect(normalizeSide(null)).toBe("other");
  });
});

describe("filterTrades", () => {
  const trades = [
    trade({ id: 1, side: "buy", pnl: 50, symbol: "BTCUSDT", close_reason: "take_profit" }),
    trade({ id: 2, side: "sell", pnl: -30, symbol: "ETHUSDT", close_reason: "stop_loss" }),
    trade({ id: 3, side: "buy", pnl: -10, symbol: "SOLUSDT", close_reason: "max_duration" }),
  ];

  it("filters by side", () => {
    expect(filterTrades(trades, { side: "long" }).map((t) => t.id)).toEqual([1, 3]);
    expect(filterTrades(trades, { side: "short" }).map((t) => t.id)).toEqual([2]);
  });
  it("filters by outcome", () => {
    expect(filterTrades(trades, { outcome: "win" }).map((t) => t.id)).toEqual([1]);
    expect(filterTrades(trades, { outcome: "loss" }).map((t) => t.id)).toEqual([2, 3]);
  });
  it("filters by close reason", () => {
    expect(filterTrades(trades, { closeReason: "stop_loss" }).map((t) => t.id)).toEqual([2]);
  });
  it("filters by symbol search (case-insensitive substring)", () => {
    expect(filterTrades(trades, { search: "eth" }).map((t) => t.id)).toEqual([2]);
  });
  it("returns all with empty filters", () => {
    expect(filterTrades(trades, {}).length).toBe(3);
  });
  it("does not mutate input", () => {
    const copy = [...trades];
    filterTrades(trades, { side: "long" });
    expect(trades).toEqual(copy);
  });
});

describe("sortTrades", () => {
  const trades = [
    trade({ id: 1, pnl: 50, symbol: "BTCUSDT" }),
    trade({ id: 2, pnl: -30, symbol: "ETHUSDT" }),
    trade({ id: 3, pnl: 100, symbol: "AAVEUSDT" }),
  ];

  it("sorts numerically asc/desc", () => {
    expect(sortTrades(trades, "pnl", "asc").map((t) => t.pnl)).toEqual([-30, 50, 100]);
    expect(sortTrades(trades, "pnl", "desc").map((t) => t.pnl)).toEqual([100, 50, -30]);
  });
  it("sorts strings alphabetically", () => {
    expect(sortTrades(trades, "symbol", "asc").map((t) => t.symbol)).toEqual([
      "AAVEUSDT",
      "BTCUSDT",
      "ETHUSDT",
    ]);
  });
  it("keeps nulls last regardless of direction", () => {
    const withNull = [
      trade({ id: 1, pnl: 50 }),
      trade({ id: 2, pnl: null }),
      trade({ id: 3, pnl: 10 }),
    ];
    expect(sortTrades(withNull, "pnl", "asc").map((t) => t.id)).toEqual([3, 1, 2]);
    expect(sortTrades(withNull, "pnl", "desc").map((t) => t.id)).toEqual([1, 3, 2]);
  });
  it("does not mutate input", () => {
    const copy = [...trades];
    sortTrades(trades, "pnl", "asc");
    expect(trades).toEqual(copy);
  });
});

describe("withCumulativePnl", () => {
  it("accumulates pnl in order", () => {
    const result = withCumulativePnl([
      trade({ pnl: 50 }),
      trade({ pnl: -20 }),
      trade({ pnl: 100 }),
    ]);
    expect(result.map((t) => t.cumulative_pnl)).toEqual([50, 30, 130]);
  });
  it("treats null pnl as 0", () => {
    const result = withCumulativePnl([trade({ pnl: null }), trade({ pnl: 10 })]);
    expect(result.map((t) => t.cumulative_pnl)).toEqual([0, 10]);
  });
});

describe("paginate / pageCount", () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1);
  it("slices the correct page", () => {
    expect(paginate(items, 1, 10)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(paginate(items, 3, 10)).toEqual([21, 22, 23, 24, 25]);
  });
  it("computes page count with ceil, min 1", () => {
    expect(pageCount(25, 10)).toBe(3);
    expect(pageCount(0, 10)).toBe(1);
  });
});

describe("csvCell / tradesToCsv", () => {
  it("escapes cells containing comma/quote/newline", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('he said "hi"')).toBe('"he said ""hi"""');
    expect(csvCell(null)).toBe("");
  });
  it("quotes cells containing newlines or carriage returns (RFC 4180)", () => {
    expect(csvCell("a\nb")).toBe('"a\nb"');
    expect(csvCell("a\rb")).toBe('"a\rb"');
  });
  it("neutralizes spreadsheet formula injection on string cells", () => {
    // Leading =,+,-,@ would execute in Excel/Sheets — prefix with a quote.
    expect(csvCell("@SUM(A1)")).toBe("'@SUM(A1)");
    expect(csvCell("+1+1")).toBe("'+1+1");
    expect(csvCell("-cmd")).toBe("'-cmd");
    // A formula that also contains quotes is both prefixed AND RFC-4180 quoted.
    expect(csvCell('=HYPERLINK("x")')).toBe('"\'=HYPERLINK(""x"")"');
  });
  it("does NOT prefix legitimate negative numbers (numeric cells)", () => {
    // typeof number guard keeps real values intact.
    expect(csvCell(-123.45)).toBe("-123.45");
    expect(csvCell(-1)).toBe("-1");
  });
  it("builds header + rows", () => {
    const csv = tradesToCsv([trade({ symbol: "BTCUSDT", pnl: 50 })]);
    const lines = csv.split("\r\n");
    expect(lines[0]).toContain("Symbol");
    expect(lines[0]).toContain("PnL");
    expect(lines[1]).toContain("BTCUSDT");
    expect(lines[1]).toContain("50");
  });
});
