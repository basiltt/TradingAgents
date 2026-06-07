import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MetricsGrid } from "../MetricsGrid";
import type { BacktestMetrics, DirectionMetrics } from "../types";

function dir(overrides: Partial<DirectionMetrics> = {}): DirectionMetrics {
  return {
    total_trades: 10,
    winners: 6,
    losers: 4,
    net_profit: 1234.5,
    win_rate: 60,
    avg_trade: 123.45,
    avg_win: 300,
    avg_loss: -150,
    ...overrides,
  };
}

function makeMetrics(overrides: Partial<BacktestMetrics> = {}): BacktestMetrics {
  return {
    total_trades: 10,
    winners: 6,
    losers: 4,
    net_profit: 1234.5,
    net_profit_pct: 12.345,
    gross_profit: 2000,
    gross_loss: -765.5,
    win_rate: 60,
    profit_factor: 2.61,
    sharpe: 1.85,
    sortino: 2.4,
    max_dd_pct: 8.5,
    max_dd_usd: 850,
    max_dd_duration_hours: 26,
    avg_dd_pct: 3.2,
    max_run_up_pct: 15,
    max_run_up_usd: 1500,
    avg_trade: 123.45,
    avg_win: 333.33,
    avg_loss: -191.37,
    avg_win_loss_ratio: 1.74,
    largest_win: 600,
    largest_loss: -300,
    total_commission: 45.6,
    recovery_factor: 1.45,
    cagr: 145.2,
    calmar: 17.08,
    expectancy: 123.45,
    max_consecutive_wins: 4,
    max_consecutive_losses: 2,
    max_consecutive_wins_usd: 900,
    max_consecutive_losses_usd: -300,
    avg_trade_duration_hours: 12.5,
    avg_winner_duration_hours: 10,
    avg_loser_duration_hours: 16,
    max_trade_duration_hours: 48,
    final_equity: 11234.5,
    by_direction: {
      all: dir(),
      long: dir({ total_trades: 7, winners: 5, losers: 2, net_profit: 1500 }),
      short: dir({ total_trades: 3, winners: 1, losers: 2, net_profit: -265.5 }),
    },
    ...overrides,
  };
}

describe("MetricsGrid", () => {
  it("renders headline KPI tiles with formatted values", () => {
    render(<MetricsGrid metrics={makeMetrics()} />);
    // "Net Profit" appears exactly twice: a headline tile + a breakdown row label.
    expect(screen.getAllByText("Net Profit")).toHaveLength(2);
    // Net-profit dollar value appears in the headline tile and the "All" breakdown cell.
    expect(screen.getAllByText("+$1,234.50").length).toBeGreaterThanOrEqual(1);
    // Profit factor is unique.
    expect(screen.getByText("2.61")).toBeInTheDocument();
  });

  it("renders the per-direction breakdown with distinct Long/Short cell values", () => {
    render(<MetricsGrid metrics={makeMetrics()} />);
    const table = screen.getByTestId("direction-breakdown");
    // Long net profit 1500, short -265.50 — exact values prove column wiring.
    expect(within(table).getByText("+$1,500.00")).toBeInTheDocument();
    expect(within(table).getByText("-$265.50")).toBeInTheDocument();
    // Long has 7 total trades, short 3 — find those in their rows.
    const totalRow = within(table).getByText("Total Trades").closest("tr") as HTMLElement;
    const cells = totalRow.querySelectorAll("td");
    expect(cells[0].textContent).toBe("10"); // all
    expect(cells[1].textContent).toBe("7"); // long
    expect(cells[2].textContent).toBe("3"); // short
  });

  it("renders the per-direction breakdown table with All/Long/Short columns", () => {
    render(<MetricsGrid metrics={makeMetrics()} />);
    const table = screen.getByTestId("direction-breakdown");
    expect(within(table).getByText("All")).toBeInTheDocument();
    expect(within(table).getByText("Long")).toBeInTheDocument();
    expect(within(table).getByText("Short")).toBeInTheDocument();
    // Long net profit
    expect(within(table).getByText("+$1,500.00")).toBeInTheDocument();
    // Short net profit (negative)
    expect(within(table).getByText("-$265.50")).toBeInTheDocument();
  });

  it("shows N/A for null metrics (e.g. sharpe undefined)", () => {
    render(<MetricsGrid metrics={makeMetrics({ sharpe: null, sortino: null })} />);
    // Both Sharpe and Sortino tiles show N/A
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(2);
  });

  it("shows ∞ for profit factor when null (no losses)", () => {
    render(<MetricsGrid metrics={makeMetrics({ profit_factor: null })} />);
    expect(screen.getByText("∞")).toBeInTheDocument();
  });

  it("renders buy & hold comparison tiles only when present", () => {
    const { rerender } = render(<MetricsGrid metrics={makeMetrics()} />);
    expect(screen.queryByText("Buy & Hold")).not.toBeInTheDocument();

    rerender(
      <MetricsGrid
        metrics={makeMetrics({ buy_hold_return_pct: 50, excess_return: 95.2 })}
      />,
    );
    expect(screen.getByText("Buy & Hold")).toBeInTheDocument();
    expect(screen.getByText("Excess Return")).toBeInTheDocument();
  });

  it("renders secondary stats (durations, streaks, commission)", () => {
    render(<MetricsGrid metrics={makeMetrics()} />);
    expect(screen.getByText("Avg Trade Duration")).toBeInTheDocument();
    expect(screen.getByText("12.5h")).toBeInTheDocument();
    expect(screen.getByText("Max Trade Duration")).toBeInTheDocument();
    expect(screen.getByText("2d")).toBeInTheDocument(); // 48h
    expect(screen.getByText("Total Commission")).toBeInTheDocument();
  });

  it("renders the full FR-006 metric set (gross profit/loss, avg dd, winner/loser durations)", () => {
    render(<MetricsGrid metrics={makeMetrics()} />);
    expect(screen.getByText("Gross Profit")).toBeInTheDocument();
    expect(screen.getByText("Gross Loss")).toBeInTheDocument();
    expect(screen.getByText("Avg Drawdown")).toBeInTheDocument();
    expect(screen.getByText("Avg Winner Duration")).toBeInTheDocument();
    expect(screen.getByText("Avg Loser Duration")).toBeInTheDocument();
    // Exact values prove field wiring, not just label presence.
    expect(screen.getByText("+$2,000.00")).toBeInTheDocument(); // gross_profit 2000
    expect(screen.getByText("-$765.50")).toBeInTheDocument(); // gross_loss -Math.abs(765.5)
    expect(screen.getByText("3.20%")).toBeInTheDocument(); // avg_dd_pct 3.2
  });

  it("hides the per-strategy breakdown when there is no mean-reversion bucket", () => {
    render(<MetricsGrid metrics={makeMetrics({ by_strategy: { "trend:short": dir() } })} />);
    expect(screen.queryByTestId("strategy-breakdown")).toBeNull();
  });

  it("renders the per-strategy breakdown when MR trades are present (F2 validation)", () => {
    const metrics = makeMetrics({
      by_strategy: {
        "trend:short": dir({ total_trades: 5, net_profit: 500 }),
        "mean_reversion:short": dir({ total_trades: 3, net_profit: 120, win_rate: 66.7 }),
        "mean_reversion:long": dir({ total_trades: 2, net_profit: -40, win_rate: 25 }),
      },
    });
    render(<MetricsGrid metrics={metrics} />);
    const table = screen.getByTestId("strategy-breakdown");
    const rows = within(table).getAllByTestId("strategy-row");
    expect(rows).toHaveLength(3);
    expect(table.textContent).toMatch(/Mean-Rev/);
    expect(table.textContent).toMatch(/Trend/);
  });
});
