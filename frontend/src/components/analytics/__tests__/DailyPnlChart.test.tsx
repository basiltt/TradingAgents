import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DailyPnlChart } from "../DailyPnlChart";
import type { DailyPnlPoint } from "../performanceTypes";

const data: DailyPnlPoint[] = [
  { date: "2026-05-01", pnl: 100.5 },
  { date: "2026-05-02", pnl: -50.25 },
  { date: "2026-05-03", pnl: 200.0 },
];

describe("DailyPnlChart", () => {
  it("renders without crashing with valid data", () => {
    const { container } = render(<DailyPnlChart data={data} />);
    expect(container.querySelector("figure")).toBeTruthy();
    expect(container.textContent).not.toContain("No daily P&L data");
  });

  it("renders an empty-state node for empty data", () => {
    const { container } = render(<DailyPnlChart data={[]} />);
    expect(container.textContent).toContain("No");
  });
});
