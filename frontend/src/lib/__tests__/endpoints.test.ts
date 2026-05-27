import { describe, it, expect, beforeEach } from "vitest";
import { loadEndpoints, saveEndpoint, removeEndpoint } from "../endpoints";
import type { EndpointProfile } from "../endpoints";

describe("endpoints — localStorage CRUD", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns empty array when nothing stored", () => {
    expect(loadEndpoints()).toEqual([]);
  });

  it("returns empty array on corrupted JSON", () => {
    localStorage.setItem("tradingagents_endpoints", "not json{");
    expect(loadEndpoints()).toEqual([]);
  });

  it("saves and loads a new endpoint", () => {
    const ep: EndpointProfile = { url: "http://localhost:8000", apiKey: "key1" };
    saveEndpoint(ep);
    const loaded = loadEndpoints();
    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toEqual(ep);
  });

  it("updates existing endpoint by URL match", () => {
    saveEndpoint({ url: "http://a.com", apiKey: "old" });
    saveEndpoint({ url: "http://a.com", apiKey: "new" });
    const loaded = loadEndpoints();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].apiKey).toBe("new");
  });

  it("appends a second endpoint with different URL", () => {
    saveEndpoint({ url: "http://a.com" });
    saveEndpoint({ url: "http://b.com" });
    expect(loadEndpoints()).toHaveLength(2);
  });

  it("removes endpoint by URL", () => {
    saveEndpoint({ url: "http://a.com" });
    saveEndpoint({ url: "http://b.com" });
    removeEndpoint("http://a.com");
    const loaded = loadEndpoints();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].url).toBe("http://b.com");
  });

  it("removeEndpoint is no-op for non-existent URL", () => {
    saveEndpoint({ url: "http://a.com" });
    removeEndpoint("http://z.com");
    expect(loadEndpoints()).toHaveLength(1);
  });

  it("persists deepModel and quickModel fields", () => {
    const ep: EndpointProfile = { url: "http://x.com", deepModel: "gpt-4", quickModel: "gpt-3.5" };
    saveEndpoint(ep);
    const loaded = loadEndpoints();
    expect(loaded[0].deepModel).toBe("gpt-4");
    expect(loaded[0].quickModel).toBe("gpt-3.5");
  });
});
