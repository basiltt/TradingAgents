import { describe, it, expect } from "vitest";
import { formatRelativeTime, formatPrice, formatQty, formatPnl, formatAbsoluteTime } from "../utils";

describe("formatRelativeTime", () => {
  it("returns '--' for empty string", () => {
    expect(formatRelativeTime("")).toBe("--");
  });

  it("returns '--' for invalid date", () => {
    expect(formatRelativeTime("not-a-date")).toBe("--");
  });

  it("returns 'just now' for timestamps < 5s ago", () => {
    const now = new Date().toISOString();
    expect(formatRelativeTime(now)).toBe("just now");
  });

  it("returns relative time for older timestamps", () => {
    const twoMinAgo = new Date(Date.now() - 120_000).toISOString();
    const result = formatRelativeTime(twoMinAgo);
    expect(result).toContain("minute");
  });

  it("returns relative time for hours ago", () => {
    const threeHrsAgo = new Date(Date.now() - 3 * 3600_000).toISOString();
    const result = formatRelativeTime(threeHrsAgo);
    expect(result).toContain("hour");
  });
});

describe("formatPrice", () => {
  it("returns '--' for null", () => {
    expect(formatPrice(null)).toBe("--");
  });

  it("formats number with 2 decimals by default", () => {
    expect(formatPrice(1234.5)).toBe("1,234.50");
  });

  it("respects custom decimals", () => {
    expect(formatPrice(1.123456, 4)).toBe("1.1235");
  });
});

describe("formatQty", () => {
  it("returns '--' for null", () => {
    expect(formatQty(null)).toBe("--");
  });

  it("returns '--' for undefined", () => {
    expect(formatQty(undefined)).toBe("--");
  });

  it("formats number", () => {
    expect(formatQty(0.0123)).toBe("0.0123");
  });
});

describe("formatPnl", () => {
  it("adds + prefix for positive", () => {
    expect(formatPnl(100)).toBe("+100.00");
  });

  it("no prefix for negative", () => {
    expect(formatPnl(-50)).toBe("-50.00");
  });

  it("no prefix for zero", () => {
    expect(formatPnl(0)).toBe("0.00");
  });
});

describe("formatAbsoluteTime", () => {
  it("returns '--' for empty string", () => {
    expect(formatAbsoluteTime("")).toBe("--");
  });

  it("returns '--' for invalid date", () => {
    expect(formatAbsoluteTime("nope")).toBe("--");
  });

  it("returns local and UTC time for valid date", () => {
    const result = formatAbsoluteTime("2025-01-15T12:00:00Z");
    expect(result).toContain("(");
    expect(result).toContain("GMT");
  });
});
