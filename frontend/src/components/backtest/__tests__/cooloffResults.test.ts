import { describe, it, expect } from "vitest";
import { extractCooloff, cooloffReasonLabel } from "../cooloffResults";

describe("extractCooloff", () => {
  it("returns an absent (present=false) record for undefined / non-object summary", () => {
    for (const s of [undefined, null as unknown as undefined, 42 as unknown as undefined]) {
      const r = extractCooloff(s);
      expect(r.present).toBe(false);
      expect(r.hasContent).toBe(false);
      expect(r.signalsSkipped).toBe(0);
      expect(r.bands).toEqual([]);
    }
  });

  it("returns absent when the summary has no cool-off keys (OFF run)", () => {
    const r = extractCooloff({ total_trades: 5, win_rate: 0.6 });
    expect(r.present).toBe(false);
    expect(r.hasContent).toBe(false);
  });

  it("marks present=true but hasContent=false for a tier enabled that never triggered", () => {
    // engine emits the skipped key (=0) and an empty bands array when a tier is on
    const r = extractCooloff({ cooloff_signals_skipped: 0, cooloff_bands: [] });
    expect(r.present).toBe(true);
    expect(r.hasContent).toBe(false);
    expect(r.signalsSkipped).toBe(0);
  });

  it("parses a populated summary (skipped + by-reason + bands)", () => {
    const r = extractCooloff({
      cooloff_signals_skipped: 9,
      cooloff_skipped_by_reason: { failure: 5, double_failure: 4 },
      cooloff_bands: [
        { start: "2026-01-01T00:00:00Z", end: "2026-01-01T06:00:00Z", reason: "failure" },
      ],
    });
    expect(r.present).toBe(true);
    expect(r.hasContent).toBe(true);
    expect(r.signalsSkipped).toBe(9);
    expect(r.byReason).toEqual([
      { reason: "failure", count: 5 },
      { reason: "double_failure", count: 4 },
    ]);
    expect(r.bands).toHaveLength(1);
  });

  it("sorts byReason descending by count, then by reason name", () => {
    const r = extractCooloff({
      cooloff_signals_skipped: 6,
      cooloff_skipped_by_reason: { success: 2, failure: 2, double_failure: 2 },
    });
    // equal counts → alphabetical by reason
    expect(r.byReason.map((x) => x.reason)).toEqual(["double_failure", "failure", "success"]);
  });

  it("ignores negative / non-finite / non-number skipped and reason counts", () => {
    const r = extractCooloff({
      cooloff_signals_skipped: -3,
      cooloff_skipped_by_reason: { failure: -1, success: "x" as unknown as number, double_success: 4 },
    });
    expect(r.signalsSkipped).toBe(0);
    expect(r.byReason).toEqual([{ reason: "double_success", count: 4 }]);
  });

  it("treats a non-object by-reason (e.g. array) as no reasons", () => {
    const r = extractCooloff({
      cooloff_signals_skipped: 3,
      cooloff_skipped_by_reason: [1, 2, 3] as unknown as Record<string, number>,
    });
    expect(r.byReason).toEqual([]);
    expect(r.hasContent).toBe(true); // skipped>0 still counts
  });

  it("drops malformed band entries and defaults a missing reason to 'unknown'", () => {
    const r = extractCooloff({
      cooloff_bands: [
        { start: "2026-01-01T00:00:00Z", end: "2026-01-01T06:00:00Z" }, // no reason
        { start: 123, end: "2026-01-02T00:00:00Z", reason: "failure" }, // non-string start
        "not-an-object",
        { start: "2026-01-03T00:00:00Z", end: "2026-01-03T06:00:00Z", reason: "success" },
      ] as unknown[],
    });
    expect(r.bands).toEqual([
      { start: "2026-01-01T00:00:00Z", end: "2026-01-01T06:00:00Z", reason: "unknown" },
      { start: "2026-01-03T00:00:00Z", end: "2026-01-03T06:00:00Z", reason: "success" },
    ]);
  });

  it("treats a non-array cooloff_bands as no bands", () => {
    const r = extractCooloff({ cooloff_bands: { start: "x" } as unknown as unknown[] });
    expect(r.bands).toEqual([]);
    // the key exists → present, but nothing renders
    expect(r.present).toBe(true);
    expect(r.hasContent).toBe(false);
  });

  it("is present (bands-only summary) even without the skipped key", () => {
    const r = extractCooloff({
      cooloff_bands: [{ start: "2026-01-01T00:00:00Z", end: "2026-01-01T06:00:00Z", reason: "success" }],
    });
    expect(r.present).toBe(true);
    expect(r.hasContent).toBe(true);
  });

  it("does NOT parse a by-reason-only summary (no skipped/bands key) → absent", () => {
    // The presence gate keys off cooloff_signals_skipped OR cooloff_bands; a summary
    // carrying only cooloff_skipped_by_reason (which the engine never emits alone)
    // is treated as not-present, so the reasons are intentionally ignored.
    const r = extractCooloff({ cooloff_skipped_by_reason: { failure: 3 } });
    expect(r.present).toBe(false);
    expect(r.hasContent).toBe(false);
    expect(r.byReason).toEqual([]);
  });
});

describe("cooloffReasonLabel", () => {
  it("maps the four known reasons to human labels", () => {
    expect(cooloffReasonLabel("success")).toBe("Success");
    expect(cooloffReasonLabel("failure")).toBe("Failure");
    expect(cooloffReasonLabel("double_success")).toBe("Double success");
    expect(cooloffReasonLabel("double_failure")).toBe("Double failure");
  });

  it("de-underscores an unknown reason rather than dropping it", () => {
    expect(cooloffReasonLabel("some_new_reason")).toBe("some new reason");
  });
});
