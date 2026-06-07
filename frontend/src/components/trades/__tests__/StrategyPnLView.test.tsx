import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { StrategyPnLView } from "../StrategyPnLView";
import type { StrategyDirectionStats } from "../types";

function row(overrides: Partial<StrategyDirectionStats> = {}): StrategyDirectionStats {
  return {
    strategy_kind: "trend",
    direction: "short",
    count: 10,
    total_pnl: 123.45,
    avg_pnl: 12.3,
    avg_hold_minutes: 95,
    win_rate: 0.6,
    ...overrides,
  };
}

describe("StrategyPnLView", () => {
  it("renders a row per strategy × direction (AC-016)", () => {
    const rows = [
      row({ strategy_kind: "trend", direction: "short" }),
      row({ strategy_kind: "mean_reversion", direction: "long", total_pnl: -5 }),
      row({ strategy_kind: "mean_reversion", direction: "short", total_pnl: 8 }),
    ];
    render(<StrategyPnLView rows={rows} />);
    expect(screen.getAllByTestId("strategy-pnl-row")).toHaveLength(3);
  });

  it("shows win-rate as a percentage and formats positive PnL with a sign", () => {
    render(<StrategyPnLView rows={[row({ win_rate: 0.6, total_pnl: 123.45 })]} />);
    const tr = screen.getByTestId("strategy-pnl-row");
    expect(within(tr).getByText("60.0")).toBeTruthy();
    expect(within(tr).getByText("+123.45")).toBeTruthy();
  });

  it("formats average hold in hours and minutes", () => {
    render(<StrategyPnLView rows={[row({ avg_hold_minutes: 95 })]} />);
    expect(screen.getByText("1h 35m")).toBeTruthy();
  });

  it("renders an empty-state note when there are no rows", () => {
    render(<StrategyPnLView rows={[]} />);
    expect(screen.getByTestId("strategy-pnl-empty")).toBeTruthy();
  });

  it("renders a loading state", () => {
    render(<StrategyPnLView rows={undefined} loading />);
    expect(screen.getByTestId("strategy-pnl-loading")).toBeTruthy();
  });
});
