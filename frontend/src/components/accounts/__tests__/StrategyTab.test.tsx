import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { getStats } = vi.hoisted(() => ({ getStats: vi.fn() }));
vi.mock("@/api/client", () => ({
  tradesApi: { getStats },
}));

import { StrategyTab } from "../StrategyTab";

describe("StrategyTab", () => {
  beforeEach(() => getStats.mockReset());

  it("renders the per-strategy breakdown once loaded", async () => {
    getStats.mockResolvedValue({
      by_strategy: [
        { strategy_kind: "trend", direction: "short", count: 3, total_pnl: 10, avg_pnl: 3, avg_hold_minutes: 60, win_rate: 0.5 },
        { strategy_kind: "mean_reversion", direction: "long", count: 2, total_pnl: -4, avg_pnl: -2, avg_hold_minutes: 90, win_rate: 0.25 },
      ],
    });
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(screen.getByTestId("strategy-pnl-table")).toBeTruthy());
    // assert ACTUAL rendered content, not just the container — a table that drops
    // rows or shows wrong values must fail.
    const rows = screen.getAllByTestId("strategy-pnl-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toMatch(/short/i);
    expect(rows[0].textContent).toContain("+10.00");   // trend total PnL, signed
    expect(rows[0].textContent).toContain("50.0");     // win rate %
    expect(rows[1].textContent).toMatch(/long/i);
    expect(rows[1].textContent).toContain("-4.00");    // MR total PnL
  });

  it("requests the by_strategy breakdown for the account", async () => {
    getStats.mockResolvedValue({ by_strategy: [] });
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(getStats).toHaveBeenCalled());
    const [ids, byStrategy] = getStats.mock.calls[0];
    expect(ids).toEqual(["a1"]);
    expect(byStrategy).toBe(true);
  });

  it("shows an error state when the fetch rejects", async () => {
    getStats.mockRejectedValueOnce(new Error("boom"));
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(screen.getByTestId("strategy-tab-error")).toBeTruthy());
  });

  it("shows the empty state when there are no strategy rows", async () => {
    getStats.mockResolvedValue({ by_strategy: [] });
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(screen.getByTestId("strategy-pnl-empty")).toBeTruthy());
  });
});
