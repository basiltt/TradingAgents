import { describe, it, expect } from "vitest";
import { signalBucket } from "../ScanResultFilters";
import type { ScanResultItem } from "@/api/client";

function row(partial: Partial<ScanResultItem>): ScanResultItem {
  return {
    ticker: "X", run_id: null, status: "completed",
    direction: "hold", confidence: "none", score: 0, decision_summary: "",
    ...partial,
  };
}

describe("signalBucket", () => {
  it("classifies ta_prefilter rows as skipped even when direction is hold", () => {
    expect(signalBucket(row({ direction: "hold", signal_source: "ta_prefilter" }))).toBe("skipped");
  });

  it("classifies a real hold (non-prefilter) as hold", () => {
    expect(signalBucket(row({ direction: "hold", signal_source: "structured" }))).toBe("hold");
  });

  it("treats unknown/missing direction as hold", () => {
    expect(signalBucket(row({ direction: "unknown", signal_source: "regex_fallback" }))).toBe("hold");
    expect(signalBucket(row({ direction: "", signal_source: undefined }))).toBe("hold");
  });

  it("passes buy and sell through unchanged", () => {
    expect(signalBucket(row({ direction: "buy", signal_source: "structured" }))).toBe("buy");
    expect(signalBucket(row({ direction: "sell", signal_source: "structured" }))).toBe("sell");
  });

  it("never returns buy/sell for a ta_prefilter row", () => {
    expect(signalBucket(row({ direction: "buy", signal_source: "ta_prefilter" }))).toBe("skipped");
  });
});
