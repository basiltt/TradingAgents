import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityOverlayChart } from "../EquityOverlayChart";
import {
  mergeEquityDatasets,
  OVERLAY_COLORS,
  type EquityDataset,
} from "../equityOverlayData";

function ds(label: string, equities: number[]): EquityDataset {
  return {
    label,
    color: OVERLAY_COLORS[0],
    data: equities.map((equity, i) => ({ ts: `2026-01-0${i + 1}T00:00:00Z`, equity })),
  };
}

describe("mergeEquityDatasets", () => {
  it("merges datasets into index-aligned rows with s{i} keys", () => {
    const { rows, series } = mergeEquityDatasets([ds("A", [100, 110]), ds("B", [100, 90])]);
    expect(series.map((s) => s.key)).toEqual(["s0", "s1"]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ idx: 0, s0: 100, s1: 100 });
    expect(rows[1]).toMatchObject({ idx: 1, s0: 110, s1: 90 });
  });

  it("aligns datasets of different lengths by index (shorter series omits tail)", () => {
    const { rows } = mergeEquityDatasets([ds("A", [100, 110, 120]), ds("B", [100])]);
    expect(rows).toHaveLength(3);
    expect(rows[1].s1).toBeUndefined(); // B has no point at idx 1
    expect(rows[2].s0).toBe(120);
  });

  it("skips non-finite equity values", () => {
    const { rows } = mergeEquityDatasets([ds("A", [Infinity, 110])]);
    expect(rows[0].s0).toBeUndefined();
    expect(rows[1].s0).toBe(110);
  });
});

describe("EquityOverlayChart", () => {
  it("renders an overlay container with multiple datasets", () => {
    render(
      <EquityOverlayChart
        datasets={[
          { label: "Run A", color: OVERLAY_COLORS[0], data: [{ ts: "2026-01-01T00:00:00Z", equity: 100 }, { ts: "2026-01-02T00:00:00Z", equity: 120 }] },
          { label: "Run B", color: OVERLAY_COLORS[1], data: [{ ts: "2026-01-01T00:00:00Z", equity: 100 }, { ts: "2026-01-02T00:00:00Z", equity: 90 }] },
        ]}
      />,
    );
    const chart = screen.getByTestId("equity-overlay-chart");
    expect(chart).toBeInTheDocument();
    expect(chart.getAttribute("aria-label")).toMatch(/Run A, Run B/);
  });

  it("shows an empty state when all datasets are empty", () => {
    render(<EquityOverlayChart datasets={[{ label: "X", color: "#000", data: [] }]} />);
    expect(screen.getByTestId("overlay-empty")).toBeInTheDocument();
  });
});
