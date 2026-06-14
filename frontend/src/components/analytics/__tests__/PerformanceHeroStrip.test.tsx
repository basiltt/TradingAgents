import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PerformanceHeroStrip } from "../PerformanceHeroStrip";
import type { PerformanceOverview, PerformanceKpis } from "../performanceTypes";

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

const base: PerformanceOverview = {
  kpis: KPIS,
  kpis_prev: { total_equity: 188.1, net_pnl: 7.1, win_rate: 58, sharpe_ratio: 1.4, max_drawdown_pct: -5, total_trades: 6 },
  equity_curve: [{ t: "2026-05-01T00:00:00Z", cum_pnl: 5, peak: 5 }],
  equity_now: { t: "2026-06-14T12:00:00Z", equity: 199.02 },
  drawdown_series: [], daily_pnl: [{ date: "2026-05-01", pnl: 2.3 }], monthly_pnl: [],
  meta: { currency: "USDT", grouping_tz: "UTC", trading_days: 14, starting_equity: 174,
          return_basis: "recorded_history", live_equity_available: true,
          live_sourced: [], degraded: false },
};

describe("PerformanceHeroStrip", () => {
  it("renders the 5 hero metric labels", () => {
    render(<PerformanceHeroStrip overview={base} />);
    expect(screen.getByText(/Total Equity/i)).toBeInTheDocument();
    expect(screen.getByText(/Net P&L/i)).toBeInTheDocument();
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument();
    expect(screen.getByText(/Sharpe/i)).toBeInTheDocument();
    expect(screen.getByText(/Max DD/i)).toBeInTheDocument();
  });

  it("shows delta chips when prior window has >=3 trades", () => {
    const { queryAllByTestId } = render(<PerformanceHeroStrip overview={base} />);
    expect(queryAllByTestId("delta-chip").length).toBeGreaterThan(0);
  });

  it("hides delta chips when kpis_prev is null", () => {
    const { queryAllByTestId } = render(<PerformanceHeroStrip overview={{ ...base, kpis_prev: null }} />);
    expect(queryAllByTestId("delta-chip")).toHaveLength(0);
  });

  it("hides delta chips when the prior window is too thin (<3 trades)", () => {
    const thin = { ...base, kpis_prev: { ...base.kpis_prev!, total_trades: 2 } };
    const { queryAllByTestId } = render(<PerformanceHeroStrip overview={thin} />);
    expect(queryAllByTestId("delta-chip")).toHaveLength(0);
  });
});
