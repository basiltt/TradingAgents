import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DailyPnlChart } from "../DailyPnlChart";
import type { DailySnapshot } from "@/api/client";

const mockSnapshots: DailySnapshot[] = [
  { snapshot_date: "2025-01-01", realised_pnl: 100.5, equity: 10100, cumulative_pnl: 100.5, wallet_balance: 10000, available_balance: 9500, unrealised_pnl: 0, positions_count: 2, margin_used: 500, daily_return_pct: 1.0, peak_equity: 10100, drawdown_pct: 0 },
  { snapshot_date: "2025-01-02", realised_pnl: -50.25, equity: 10050, cumulative_pnl: 50.25, wallet_balance: 10050, available_balance: 9550, unrealised_pnl: 0, positions_count: 1, margin_used: 500, daily_return_pct: -0.5, peak_equity: 10100, drawdown_pct: 0.5 },
  { snapshot_date: "2025-01-03", realised_pnl: 200.0, equity: 10250, cumulative_pnl: 250.25, wallet_balance: 10250, available_balance: 9750, unrealised_pnl: 0, positions_count: 3, margin_used: 500, daily_return_pct: 2.0, peak_equity: 10250, drawdown_pct: 0 },
];

describe("DailyPnlChart", () => {
  it("renders without crashing with valid data", () => {
    const { container } = render(<DailyPnlChart snapshots={mockSnapshots} />);
    expect(container.firstChild).not.toBeNull();
  });

  it("returns null for empty snapshots", () => {
    const { container } = render(<DailyPnlChart snapshots={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
