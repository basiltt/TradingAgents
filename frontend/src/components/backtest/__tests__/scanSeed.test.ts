import { describe, it, expect } from "vitest";
import {
  scanToBacktestSeed,
  scheduleToBacktestSeed,
  encodeSeedParam,
} from "../scanSeed";

describe("scanToBacktestSeed", () => {
  it("produces a date_range source anchored at the scan start", () => {
    const seed = scanToBacktestSeed({
      scan_id: "scan-1",
      started_at: "2026-05-01T08:00:00Z",
      completed_at: "2026-05-01T08:05:00Z",
    });
    expect(seed.scan_source).toEqual({ mode: "date_range" });
    expect(seed.date_range_start).toBe("2026-05-01T08:00:00.000Z");
  });

  it("falls back to completed_at when started_at is missing", () => {
    const seed = scanToBacktestSeed({ scan_id: "s", started_at: null, completed_at: "2026-05-02T00:00:00Z" });
    expect(seed.date_range_start).toBe("2026-05-02T00:00:00.000Z");
  });

  it("omits the date when no valid timestamp is present", () => {
    const seed = scanToBacktestSeed({ scan_id: "s" });
    expect(seed.date_range_start).toBeUndefined();
    expect(seed.scan_source).toEqual({ mode: "date_range" });
  });

  it("ignores an unparseable timestamp", () => {
    const seed = scanToBacktestSeed({ scan_id: "s", started_at: "not-a-date" });
    expect(seed.date_range_start).toBeUndefined();
  });
});

describe("scheduleToBacktestSeed", () => {
  it("produces a schedule source with the schedule id", () => {
    expect(scheduleToBacktestSeed("sched-9")).toEqual({
      scan_source: { mode: "schedule", schedule_id: "sched-9" },
    });
  });
});

describe("encodeSeedParam", () => {
  it("JSON-encodes the seed for the URL search param", () => {
    const encoded = encodeSeedParam({ scan_source: { mode: "date_range" } });
    expect(JSON.parse(encoded)).toEqual({ scan_source: { mode: "date_range" } });
  });
});
