import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCards } from "../KpiCards";
import type { PerformanceAnalytics } from "@/api/client";

const mockAnalytics: PerformanceAnalytics = {
  total_return_pct: 12.5,
  total_pnl: "1250.00",
  max_drawdown_pct: 3.2,
  sharpe_ratio: 1.8,
  sortino_ratio: 2.1,
  calmar_ratio: 3.9,
  win_rate: 65,
  profit_factor: 2.1,
  expectancy: 15.5,
  avg_daily_return_pct: 0.42,
  best_day_pct: 4.2,
  best_day_date: "2025-01-15",
  worst_day_pct: -2.1,
  worst_day_date: "2025-01-10",
  max_consecutive_wins: 7,
  max_consecutive_losses: 3,
  total_trades: 120,
  win_count: 78,
  loss_count: 42,
  avg_win: "32.10",
  avg_loss: "-18.50",
  drawdown_duration_days: 5,
  recovery_time_days: 3,
  snapshot_count: 30,
};

describe("KpiCards", () => {
  it("renders primary KPIs", () => {
    render(<KpiCards analytics={mockAnalytics} />);
    expect(screen.getByText("Total Return")).toBeInTheDocument();
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    expect(screen.getByText("Sharpe Ratio")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("Profit Factor")).toBeInTheDocument();
  });

  it("renders trade stats KPIs", () => {
    render(<KpiCards analytics={mockAnalytics} />);
    expect(screen.getByText("Total Trades")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("formats currency values correctly", () => {
    render(<KpiCards analytics={mockAnalytics} />);
    expect(screen.getByText("$1250.00")).toBeInTheDocument();
  });

  it("applies positive color for positive return", () => {
    render(<KpiCards analytics={mockAnalytics} />);
    const returnVal = screen.getByText("+12.5%");
    expect(returnVal.className).toContain("emerald");
  });

  it("applies negative color for negative return", () => {
    const negAnalytics = { ...mockAnalytics, total_return_pct: -5.2 };
    render(<KpiCards analytics={negAnalytics} />);
    const returnVal = screen.getByText("-5.2%");
    expect(returnVal.className).toContain("red");
  });
});
