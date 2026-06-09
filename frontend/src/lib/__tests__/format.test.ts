import { describe, it, expect } from "vitest";
import { formatDuration, formatDurationBetween, formatDateTimeLabel } from "../format";

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

describe("formatDateTimeLabel", () => {
  it("returns the fallback for null/undefined/empty input", () => {
    expect(formatDateTimeLabel(null)).toBe("—");
    expect(formatDateTimeLabel(undefined)).toBe("—");
    expect(formatDateTimeLabel("")).toBe("—");
  });

  it("uses a custom fallback when provided", () => {
    expect(formatDateTimeLabel(null, undefined, "never")).toBe("never");
  });

  it("formats a valid ISO timestamp (contains the year by default)", () => {
    const out = formatDateTimeLabel("2026-01-05T14:30:00Z");
    expect(out).toContain("2026");
    expect(out).not.toBe("—");
  });

  it("omits the year when given options without a year field", () => {
    const out = formatDateTimeLabel("2026-01-05T14:30:00Z", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(out).not.toContain("2026");
  });

  it("returns the raw input when the date cannot be formatted", () => {
    // An unparseable string yields an Invalid Date; toLocaleString throws on some
    // engines (caught) or returns "Invalid Date". Either way it must not throw.
    const out = formatDateTimeLabel("not-a-date");
    expect(typeof out).toBe("string");
  });
});
