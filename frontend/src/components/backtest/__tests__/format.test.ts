import { describe, it, expect } from "vitest";
import {
  formatUsd,
  formatPct,
  formatRatio,
  formatHours,
  formatInt,
  formatDateTime,
  signOf,
  pnlColorClass,
  NA,
} from "../format";

describe("formatUsd", () => {
  it("formats positive/negative with $ and commas", () => {
    expect(formatUsd(1234.5)).toBe("$1,234.50");
    expect(formatUsd(-1234.5)).toBe("-$1,234.50");
    expect(formatUsd(0)).toBe("$0.00");
  });
  it("adds + sign when requested for positives", () => {
    expect(formatUsd(100, { sign: true })).toBe("+$100.00");
    expect(formatUsd(-100, { sign: true })).toBe("-$100.00");
  });
  it("returns N/A for null/inf/nan", () => {
    expect(formatUsd(null)).toBe(NA);
    expect(formatUsd(undefined)).toBe(NA);
    expect(formatUsd(Infinity)).toBe(NA);
    expect(formatUsd(NaN)).toBe(NA);
  });
});

describe("formatPct", () => {
  it("formats with % and 2 digits", () => {
    expect(formatPct(12.345)).toBe("12.35%");
    expect(formatPct(-5)).toBe("-5.00%");
  });
  it("adds + sign for positives when requested", () => {
    expect(formatPct(5, { sign: true })).toBe("+5.00%");
  });
  it("returns N/A for null", () => {
    expect(formatPct(null)).toBe(NA);
  });
});

describe("formatRatio", () => {
  it("formats finite ratios", () => {
    expect(formatRatio(2.345)).toBe("2.35");
  });
  it("shows ∞ for null when infinite option set", () => {
    expect(formatRatio(null, { infinite: true })).toBe("∞");
    expect(formatRatio(null)).toBe(NA);
  });
});

describe("formatHours", () => {
  it("formats sub-day as Nh", () => {
    expect(formatHours(1.5)).toBe("1.5h");
    expect(formatHours(23.4)).toBe("23.4h");
  });
  it("formats multi-day as Nd Mh", () => {
    expect(formatHours(26)).toBe("1d 2h");
    expect(formatHours(48)).toBe("2d");
  });
  it("carries correctly when remainder hours round up to 24 (no '1d 24h')", () => {
    // 47.6h rounds to 48h → must be "2d", not "1d 24h"
    expect(formatHours(47.6)).toBe("2d");
    // 23.6h is sub-24 so stays "23.6h" (no day rollover)
    expect(formatHours(23.6)).toBe("23.6h");
  });
  it("returns N/A for null", () => {
    expect(formatHours(null)).toBe(NA);
  });
});

describe("formatDateTime", () => {
  it("compacts an ISO timestamp to 'YYYY-MM-DD HH:mm'", () => {
    expect(formatDateTime("2026-01-05T14:30:45Z")).toBe("2026-01-05 14:30");
  });
  it("returns an em dash for null/empty", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("")).toBe("—");
  });
});

describe("formatInt", () => {
  it("formats with thousands separators", () => {
    expect(formatInt(1234567)).toBe("1,234,567");
  });
  it("returns N/A for null", () => {
    expect(formatInt(null)).toBe(NA);
  });
});

describe("signOf", () => {
  it("classifies sign", () => {
    expect(signOf(5)).toBe("pos");
    expect(signOf(-5)).toBe("neg");
    expect(signOf(0)).toBe("zero");
    expect(signOf(null)).toBe("zero");
  });
});

describe("pnlColorClass", () => {
  it("maps sign to tailwind color", () => {
    expect(pnlColorClass(5)).toContain("emerald");
    expect(pnlColorClass(-5)).toContain("rose");
    expect(pnlColorClass(0)).toContain("muted");
  });
});
