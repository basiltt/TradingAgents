import { describe, it, expect } from "vitest";
import { formatDuration, formatDurationBetween } from "../format";

describe("formatDuration", () => {
  it("formats seconds only", () => {
    expect(formatDuration(5000)).toBe("5s");
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(59999)).toBe("59s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(60000)).toBe("1m 0s");
    expect(formatDuration(90000)).toBe("1m 30s");
    expect(formatDuration(3599000)).toBe("59m 59s");
  });

  it("formats hours, minutes, and seconds", () => {
    expect(formatDuration(3600000)).toBe("1h 0m 0s");
    expect(formatDuration(5025000)).toBe("1h 23m 45s");
  });

  it("floors partial seconds", () => {
    expect(formatDuration(1500)).toBe("1s");
    expect(formatDuration(999)).toBe("0s");
  });
});

describe("formatDurationBetween", () => {
  it("returns fallback for empty startedAt", () => {
    expect(formatDurationBetween("", null)).toBe("—");
    expect(formatDurationBetween("", null, "N/A")).toBe("N/A");
  });

  it("computes duration between two timestamps", () => {
    const result = formatDurationBetween("2025-01-01T00:00:00Z", "2025-01-01T01:23:45Z");
    expect(result).toBe("1h 23m 45s");
  });

  it("uses Date.now when completedAt is null", () => {
    const fiveSecondsAgo = new Date(Date.now() - 5000).toISOString();
    const result = formatDurationBetween(fiveSecondsAgo, null);
    expect(result).toMatch(/^\d+s$/);
  });

  it("clamps negative durations to 0", () => {
    const result = formatDurationBetween("2025-01-02T00:00:00Z", "2025-01-01T00:00:00Z");
    expect(result).toBe("0s");
  });
});
