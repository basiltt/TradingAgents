import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EquityCurveChart } from "../EquityCurveChart";
import { DrawdownChart } from "../DrawdownChart";
import type { DailySnapshot } from "@/api/client";

const baseSnapshot = {
  wallet_balance: 10000,
  available_balance: 9500,
  unrealised_pnl: 0,
  positions_count: 1,
  margin_used: 500,
  daily_return_pct: 1,
  cumulative_pnl: 0,
  realised_pnl: 50,
};

const mockSnapshots: DailySnapshot[] = [
  { ...baseSnapshot, snapshot_date: "2025-01-01", equity: 10000, peak_equity: 10000, drawdown_pct: 0 },
  { ...baseSnapshot, snapshot_date: "2025-01-02", equity: 10200, peak_equity: 10200, drawdown_pct: 0 },
  { ...baseSnapshot, snapshot_date: "2025-01-03", equity: 9800, peak_equity: 10200, drawdown_pct: 3.92 },
];

describe("EquityCurveChart", () => {
  it("returns null for empty data", () => {
    const { container } = render(<EquityCurveChart snapshots={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders without crashing with valid data", () => {
    const { container } = render(<EquityCurveChart snapshots={mockSnapshots} />);
    expect(container.firstChild).not.toBeNull();
  });
});

describe("DrawdownChart", () => {
  it("returns null for empty data", () => {
    const { container } = render(<DrawdownChart snapshots={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders without crashing with valid data", () => {
    const { container } = render(<DrawdownChart snapshots={mockSnapshots} />);
    expect(container.firstChild).not.toBeNull();
  });
});
