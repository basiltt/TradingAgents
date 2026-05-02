import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { apiClient } from "../client";

const server = setupServer(
  http.get("/api/v1/health", () =>
    HttpResponse.json({ status: "ok", db: "ok" }),
  ),
  http.get("/api/v1/analysis", () =>
    HttpResponse.json({ items: [], total: 0, page: 1, limit: 20 }),
  ),
  http.post("/api/v1/analysis", async () => {
    return HttpResponse.json(
      { run_id: "test-uuid", status: "running" },
      { status: 201 },
    );
  }),
  http.get("/api/v1/analysis/test-uuid", () =>
    HttpResponse.json({ run_id: "test-uuid", status: "completed", ticker: "SPY" }),
  ),
  http.get("/api/v1/config", () =>
    HttpResponse.json({ resolved: {}, overrides: {} }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("apiClient", () => {
  it("fetches health", async () => {
    const data = await apiClient.getHealth();
    expect(data.status).toBe("ok");
  });

  it("lists analyses", async () => {
    const data = await apiClient.listAnalyses();
    expect(data.items).toEqual([]);
    expect(data.total).toBe(0);
  });

  it("starts analysis with CSRF header", async () => {
    const data = await apiClient.startAnalysis({
      ticker: "SPY",
      analysis_date: "2025-06-01",
    });
    expect(data.run_id).toBe("test-uuid");
    expect(data.status).toBe("running");
  });

  it("gets analysis by ID", async () => {
    const data = await apiClient.getAnalysis("test-uuid");
    expect(data.run_id).toBe("test-uuid");
  });

  it("fetches config", async () => {
    const data = await apiClient.getConfig();
    expect(data.resolved).toBeDefined();
  });

  it("throws on non-ok response", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    await expect(apiClient.getHealth()).rejects.toThrow();
  });
});
