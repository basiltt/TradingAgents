import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { severityClass, acknowledgeAlert } from "../decayAlerts";

describe("severityClass", () => {
  it("maps critical to the destructive palette", () => {
    expect(severityClass("critical")).toContain("destructive");
  });

  it("maps warning to the amber palette", () => {
    expect(severityClass("warning")).toContain("amber");
  });

  it("is case-insensitive", () => {
    expect(severityClass("CRITICAL")).toBe(severityClass("critical"));
    expect(severityClass("Warning")).toBe(severityClass("warning"));
  });

  it("falls back to a neutral palette for unknown severities", () => {
    const out = severityClass("informational");
    expect(out).toContain("border-border");
    expect(out).not.toContain("destructive");
    expect(out).not.toContain("amber");
  });
});

describe("acknowledgeAlert", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to the acknowledge endpoint for the given alert id with the XRW header", async () => {
    await acknowledgeAlert(42);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain("/api/v1/signal-analytics/decay-alerts/42/acknowledge");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Requested-With"]).toBe("XMLHttpRequest");
  });
});
