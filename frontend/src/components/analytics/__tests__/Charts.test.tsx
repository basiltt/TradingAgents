import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EquityCurveChart } from "../EquityCurveChart";
import { DrawdownChart } from "../DrawdownChart";
import type { CurvePoint, DrawdownPoint } from "../performanceTypes";

const curve: CurvePoint[] = [
  { t: "2026-05-01T08:00:00Z", cum_pnl: 5, peak: 5 },
  { t: "2026-05-02T08:00:00Z", cum_pnl: 3, peak: 5 },
];
const dd: DrawdownPoint[] = [
  { t: "2026-05-01T08:00:00Z", drawdown_pct: 0 },
  { t: "2026-05-02T08:00:00Z", drawdown_pct: -2.5 },
];

describe("EquityCurveChart", () => {
  it("renders an empty-state node when data is empty", () => {
    const { container } = render(<EquityCurveChart data={[]} />);
    expect(container.textContent).toContain("No closed trades");
  });

  it("renders the cumulative-P&L curve from CurvePoint[]", () => {
    const { container } = render(<EquityCurveChart data={curve} />);
    // Recharts ResponsiveContainer has no measurable layout in jsdom, so assert the
    // chart wrapper rendered (not the empty-state text) rather than querying <svg>.
    expect(container.firstChild).not.toBeNull();
    expect(container.textContent).not.toContain("No closed trades");
  });

  it("renders the live-equity path (secondary axis + now marker) without crashing", () => {
    // Exercises the startingEquity + equityNow branch: explicit dual-axis domains and the
    // anchored ReferenceDot. Must render the chart, not the empty state.
    const { container } = render(
      <EquityCurveChart
        data={curve}
        startingEquity={100}
        equityNow={{ t: "2026-06-14T12:00:00Z", equity: 108 }}
      />,
    );
    expect(container.firstChild).not.toBeNull();
    expect(container.textContent).not.toContain("No closed trades");
  });
});

describe("DrawdownChart", () => {
  it("renders an empty-state node when data is empty", () => {
    const { container } = render(<DrawdownChart data={[]} />);
    expect(container.textContent).toContain("No drawdown data");
  });

  it("renders the underwater area from DrawdownPoint[]", () => {
    const { container } = render(<DrawdownChart data={dd} />);
    expect(container.querySelector("figure")).toBeTruthy();
    expect(container.textContent).not.toContain("No drawdown data");
  });
});
