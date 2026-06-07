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
      ],
    });
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(screen.getByTestId("strategy-pnl-table")).toBeTruthy());
  });

  it("requests the by_strategy breakdown for the account", async () => {
    getStats.mockResolvedValue({ by_strategy: [] });
    render(<StrategyTab accountId="a1" />);
    await waitFor(() => expect(getStats).toHaveBeenCalled());
    const [ids, , byStrategy] = getStats.mock.calls[0];
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
