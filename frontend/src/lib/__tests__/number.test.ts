import { describe, it, expect } from "vitest";
import { clampNumber, clampNumberOrNull } from "../number";

describe("clampNumber", () => {
  it("returns a numeric value unchanged when within range", () => {
    expect(clampNumber("5", 1, 125, 1)).toBe(5);
  });

  it("clamps above max", () => {
    expect(clampNumber("130", 1, 125, 1)).toBe(125);
  });

  it("clamps below min", () => {
    expect(clampNumber("0", 1, 125, 1)).toBe(1);
  });

  it("uses the fallback for empty input", () => {
    expect(clampNumber("", 1, 125, 1)).toBe(1);
  });

  it("uses the fallback for whitespace-only input", () => {
    expect(clampNumber("   ", 1, 125, 1)).toBe(1);
  });

  it("uses the fallback for non-numeric input", () => {
    expect(clampNumber("abc", 0, 10, 0)).toBe(0);
  });

  it("accepts a numeric (non-string) raw value", () => {
    expect(clampNumber(7, 1, 125, 1)).toBe(7);
    expect(clampNumber(200, 1, 125, 1)).toBe(125);
  });

  it("handles fractional bounds (capital_pct style)", () => {
    expect(clampNumber("0.05", 0.1, 100, 1)).toBe(0.1);
    expect(clampNumber("50.5", 0.1, 100, 1)).toBe(50.5);
  });

  it("treats Infinity as out-of-range and clamps to max", () => {
    // Number("Infinity") is finite-checked: Infinity is NOT finite → fallback.
    expect(clampNumber("Infinity", 1, 125, 3)).toBe(3);
  });
});

describe("clampNumberOrNull", () => {
  it("returns a numeric value unchanged when within range", () => {
    expect(clampNumberOrNull("20", 1, 20)).toBe(20);
  });

  it("clamps above max", () => {
    expect(clampNumberOrNull("99", 1, 20)).toBe(20);
  });

  it("clamps below min", () => {
    expect(clampNumberOrNull("0", 1, 20)).toBe(1);
  });

  it("returns null for empty input (unset)", () => {
    expect(clampNumberOrNull("", 1, 20)).toBeNull();
  });

  it("returns null for whitespace-only input", () => {
    expect(clampNumberOrNull("   ", 1, 20)).toBeNull();
  });

  it("returns null for non-numeric input", () => {
    expect(clampNumberOrNull("abc", 1, 20)).toBeNull();
  });
});
