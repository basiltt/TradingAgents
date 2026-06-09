import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityCurveChart } from "../EquityCurveChart";
import {
  prepareEquitySeries,
  equityDomain,
  formatTsLabel,
  buildBuyHoldSeries,
} from "../equityCurveData";
import type { EquityPoint } from "../types";

describe("formatTsLabel", () => {
  it("formats date-only as M/D", () => {
    expect(formatTsLabel("2026-01-05T00:00:00Z")).toBe("1/5");
  });
  it("includes time when non-midnight", () => {
    expect(formatTsLabel("2026-01-05T14:30:00Z")).toBe("1/5 14:30");
  });
  it("returns empty string for null", () => {
    expect(formatTsLabel(null)).toBe("");
  });
});

describe("prepareEquitySeries", () => {
  it("derives drawdown-from-peak percent when not provided", () => {
    const points: EquityPoint[] = [
      { ts: "2026-01-01T00:00:00Z", equity: 100 },
      { ts: "2026-01-02T00:00:00Z", equity: 120 }, // new peak
      { ts: "2026-01-03T00:00:00Z", equity: 90 }, // 25% below peak 120
    ];
    const series = prepareEquitySeries(points);
    expect(series[0].drawdown).toBe(0);
    expect(series[1].drawdown).toBe(0);
    expect(series[2].drawdown).toBe(-25);
  });

  it("uses provided drawdown_pct (normalized to negative)", () => {
    const points: EquityPoint[] = [
      { ts: "2026-01-01T00:00:00Z", equity: 100, drawdown_pct: 0 },
      { ts: "2026-01-02T00:00:00Z", equity: 80, drawdown_pct: 20 },
    ];
    const series = prepareEquitySeries(points);
    expect(series[1].drawdown).toBe(-20);
  });

  it("rounds equity to 2 decimals", () => {
    const series = prepareEquitySeries([{ ts: null, equity: 100.12345 }]);
    expect(series[0].equity).toBe(100.12);
  });

  it("handles non-finite equity defensively", () => {
    const series = prepareEquitySeries([{ ts: null, equity: Infinity }]);
    expect(series[0].equity).toBe(0);
  });

  it("reports zero drawdown when the account never has positive peak equity", () => {
    // All-negative equity → peak <= 0 → derived drawdown stays 0 (no div-by-neg).
    const series = prepareEquitySeries([
      { ts: "2026-01-01T00:00:00Z", equity: -100 },
      { ts: "2026-01-02T00:00:00Z", equity: -200 },
    ]);
    expect(series.every((d) => d.drawdown === 0)).toBe(true);
  });
});

describe("equityDomain", () => {
  it("pads a single flat point so min<max", () => {
    const series = prepareEquitySeries([{ ts: "2026-01-01T00:00:00Z", equity: 100 }]);
    const [lo, hi] = equityDomain(series);
    expect(lo).toBe(99); // 100 - max(0*0.02, 1)
    expect(hi).toBe(101);
  });
  it("pads the min/max", () => {
    const series = prepareEquitySeries([
      { ts: "2026-01-01T00:00:00Z", equity: 100 },
      { ts: "2026-01-02T00:00:00Z", equity: 200 },
    ]);
    const [lo, hi] = equityDomain(series);
    expect(lo).toBeLessThan(100);
    expect(hi).toBeGreaterThan(200);
  });
  it("returns [0,1] for empty", () => {
    expect(equityDomain([])).toEqual([0, 1]);
  });
});

describe("EquityCurveChart render", () => {
  it("shows empty state when no data", () => {
    render(<EquityCurveChart equityCurve={[]} />);
    expect(screen.getByTestId("equity-chart-empty")).toBeInTheDocument();
  });

  it("renders the chart container when data present", () => {
    const points: EquityPoint[] = [
      { ts: "2026-01-01T00:00:00Z", equity: 100 },
      { ts: "2026-01-02T00:00:00Z", equity: 110 },
    ];
    render(<EquityCurveChart equityCurve={points} />);
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
  });

  it("exposes an accessible text summary via role=img aria-label", () => {
    const points: EquityPoint[] = [
      { ts: "2026-01-01T00:00:00Z", equity: 10000 },
      { ts: "2026-01-02T00:00:00Z", equity: 8000 }, // 20% drawdown from peak
    ];
    render(<EquityCurveChart equityCurve={points} />);
    const img = screen.getByRole("img");
    const label = img.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/start \$10,000/);
    expect(label).toMatch(/end \$8,000/);
    expect(label).toMatch(/worst drawdown -20\.0%/);
  });

  it("renders without crashing when a buy & hold benchmark is supplied", () => {
    const points: EquityPoint[] = [
      { ts: "2026-01-01T00:00:00Z", equity: 10000 },
      { ts: "2026-01-02T00:00:00Z", equity: 11000 },
    ];
    render(<EquityCurveChart equityCurve={points} buyHoldFinalValue={12000} />);
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
  });
});

describe("buildBuyHoldSeries", () => {
  const series = (equities: number[]) =>
    prepareEquitySeries(equities.map((equity, i) => ({ ts: `2026-01-0${i + 1}T00:00:00Z`, equity })));

  it("interpolates linearly from the start equity to the final benchmark value", () => {
    const result = buildBuyHoldSeries(series([10000, 10500, 11000, 9000]), 13000);
    // start = first equity (10000), end = finalValue (13000), 4 points → n=3.
    expect(result[0].buyHold).toBe(10000);
    expect(result[3].buyHold).toBe(13000);
    // midpoints: 10000 + (3000)*(1/3) = 11000 ; *(2/3) = 12000
    expect(result[1].buyHold).toBe(11000);
    expect(result[2].buyHold).toBe(12000);
  });

  it("preserves the original equity/label/drawdown fields", () => {
    const result = buildBuyHoldSeries(series([10000, 12000]), 11000);
    expect(result[0].equity).toBe(10000);
    expect(result[1].equity).toBe(12000);
    expect(result[0]).toHaveProperty("drawdown");
  });

  it("returns the input unchanged (no buyHold key) when benchmark is null/non-finite", () => {
    const base = series([10000, 11000]);
    expect(buildBuyHoldSeries(base, null)[0]).not.toHaveProperty("buyHold");
    expect(buildBuyHoldSeries(base, Infinity)[0]).not.toHaveProperty("buyHold");
  });

  it("returns the input unchanged for fewer than 2 points", () => {
    const base = series([10000]);
    expect(buildBuyHoldSeries(base, 12000)[0]).not.toHaveProperty("buyHold");
  });
});
