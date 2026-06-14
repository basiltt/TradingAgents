import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MonthlyPnlGrid } from "../MonthlyPnlGrid";
import type { MonthlyPnlPoint } from "../performanceTypes";

const data: MonthlyPnlPoint[] = [
  { month: "2024-12", pnl: 200.0, return_pct: 2.0 },
  { month: "2025-01", pnl: 150.5, return_pct: 1.5 },
  { month: "2025-02", pnl: -30.0, return_pct: -0.3 },
];

describe("MonthlyPnlGrid", () => {
  it("renders an empty-state node for empty data", () => {
    const { container } = render(<MonthlyPnlGrid data={[]} />);
    expect(container.textContent).toContain("No");
  });

  it("renders year rows", () => {
    render(<MonthlyPnlGrid data={data} />);
    expect(screen.getByText("2025")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
  });

  it("renders month headers", () => {
    render(<MonthlyPnlGrid data={data} />);
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.getByText("Dec")).toBeInTheDocument();
  });

  it("shows aggregated month value", () => {
    render(<MonthlyPnlGrid data={data} />);
    expect(screen.getByText("+$150.50")).toBeInTheDocument();
  });

  it("shows negative values with correct format", () => {
    render(<MonthlyPnlGrid data={data} />);
    expect(screen.getByText("-$30.00")).toBeInTheDocument();
  });
});
