import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MonthlyPnlGrid } from "../MonthlyPnlGrid";
import type { DailySnapshot } from "@/api/client";

const baseSnapshot = {
  equity: 10000,
  wallet_balance: 10000,
  available_balance: 9500,
  unrealised_pnl: 0,
  positions_count: 1,
  margin_used: 500,
  daily_return_pct: 1,
  peak_equity: 10000,
  drawdown_pct: 0,
  cumulative_pnl: 0,
};

const mockSnapshots: DailySnapshot[] = [
  { ...baseSnapshot, snapshot_date: "2025-01-15", realised_pnl: 100.5 },
  { ...baseSnapshot, snapshot_date: "2025-01-20", realised_pnl: 50.0 },
  { ...baseSnapshot, snapshot_date: "2025-02-10", realised_pnl: -30.0 },
  { ...baseSnapshot, snapshot_date: "2024-12-01", realised_pnl: 200.0 },
];

describe("MonthlyPnlGrid", () => {
  it("returns null for empty data", () => {
    const { container } = render(<MonthlyPnlGrid snapshots={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders year rows", () => {
    render(<MonthlyPnlGrid snapshots={mockSnapshots} />);
    expect(screen.getByText("2025")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
  });

  it("renders month headers", () => {
    render(<MonthlyPnlGrid snapshots={mockSnapshots} />);
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.getByText("Dec")).toBeInTheDocument();
  });

  it("aggregates multiple entries in same month", () => {
    render(<MonthlyPnlGrid snapshots={mockSnapshots} />);
    // Jan 2025: 100.5 + 50 = 150.5
    expect(screen.getByText("+$150.50")).toBeInTheDocument();
  });

  it("shows negative values with correct format", () => {
    render(<MonthlyPnlGrid snapshots={mockSnapshots} />);
    expect(screen.getByText("-$30.00")).toBeInTheDocument();
  });
});
