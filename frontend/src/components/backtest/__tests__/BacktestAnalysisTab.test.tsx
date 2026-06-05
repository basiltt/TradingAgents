import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BacktestAnalysisTab } from "../BacktestAnalysisTab";
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

const sample = [
  trade({ id: 1, exit_time: "2026-01-10T04:00:00Z", pnl: 100 }),
  trade({ id: 2, exit_time: "2026-01-20T04:00:00Z", pnl: -40 }),
  trade({ id: 3, exit_time: "2026-02-05T04:00:00Z", pnl: 200 }),
];

describe("BacktestAnalysisTab", () => {
  it("renders the three analysis sections", () => {
    render(<BacktestAnalysisTab trades={sample} />);
    expect(screen.getByText("Monthly Returns")).toBeInTheDocument();
    expect(screen.getByText("P&L Distribution")).toBeInTheDocument();
    expect(screen.getByText("Trade Duration")).toBeInTheDocument();
  });

  it("renders the monthly heatmap with a row per year", () => {
    render(<BacktestAnalysisTab trades={sample} />);
    const heatmap = screen.getByTestId("monthly-heatmap");
    expect(heatmap).toBeInTheDocument();
    // 2026 row header present
    expect(screen.getByRole("rowheader", { name: "2026" })).toBeInTheDocument();
    // Year total = 100 - 40 + 200 = 260
    expect(screen.getByText("+$260.00")).toBeInTheDocument();
  });

  it("renders the histograms when trades have data", () => {
    render(<BacktestAnalysisTab trades={sample} />);
    expect(screen.getByTestId("pnl-histogram")).toBeInTheDocument();
    expect(screen.getByTestId("duration-distribution")).toBeInTheDocument();
  });

  it("shows empty states when there are no trades", () => {
    render(<BacktestAnalysisTab trades={[]} />);
    expect(screen.getByTestId("heatmap-empty")).toBeInTheDocument();
    expect(screen.getByTestId("pnl-hist-empty")).toBeInTheDocument();
    expect(screen.getByTestId("duration-hist-empty")).toBeInTheDocument();
  });
});
