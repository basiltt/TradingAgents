import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { KpiCards } from "../KpiCards";
import type { PerformanceKpis } from "../performanceTypes";

const KPIS: PerformanceKpis = {
  total_equity: 199.02, unrealized_pnl: -1.6, open_count: 1,
  net_pnl: 12.5, realized_pnl_gross: 14.1, total_return_pct: 7.2,
  win_rate: 62.5, win_count: 10, loss_count: 6, profit_factor: 1.9,
  expectancy: 0.78, avg_win: 2.64, avg_loss: -2.31, avg_win_loss_ratio: 1.14,
  best_trade: 5.1, worst_trade: -3.3, max_consecutive_wins: 4, max_consecutive_losses: 2,
  avg_hold_time_hours: 8.4, total_trades: 16,
  max_drawdown_pct: -4.2, max_drawdown_abs: null, drawdown_duration_days: 3,
  drawdown_recovered: true, sharpe_ratio: 1.8, sortino_ratio: 2.4, calmar_ratio: 1.1,
};

describe("accessibility", () => {
  it("P&L values expose a sign + aria-label, not color-only", () => {
    const { container } = render(<KpiCards kpis={KPIS} />);
    // Net P&L tile carries an aria-label conveying value + direction (not just color).
    const labelled = container.querySelector('[aria-label*="Net P&L"]');
    expect(labelled).toBeTruthy();
    expect(labelled?.getAttribute("aria-label")).toMatch(/positive|negative|neutral/);
  });
});
