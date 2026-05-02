import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { apiClient, ApiError } from "../client";

const server = setupServer(
  http.get("/api/v1/health", () =>
    HttpResponse.json({ status: "ok", db: "ok" }),
  ),
  http.get("/api/v1/analysis", ({ request }) => {
    const url = new URL(request.url);
    return HttpResponse.json({
      items: [],
      total: 0,
      page: Number(url.searchParams.get("page") ?? 1),
      limit: Number(url.searchParams.get("limit") ?? 20),
    });
  }),
  http.post("/api/v1/analysis", async ({ request }) => {
    expect(request.headers.get("X-Requested-With")).toBe("XMLHttpRequest");
    return HttpResponse.json(
      { run_id: "test-uuid", status: "running" },
      { status: 201 },
    );
  }),
  http.get("/api/v1/analysis/test-uuid", () =>
    HttpResponse.json({
      run_id: "test-uuid",
      status: "completed",
      ticker: "SPY",
    }),
  ),
  http.post("/api/v1/analysis/test-uuid/cancel", ({ request }) => {
    expect(request.headers.get("X-Requested-With")).toBe("XMLHttpRequest");
    return HttpResponse.json({ status: "cancelled" });
  }),
  http.get("/api/v1/analysis/test-uuid/report", () =>
    new HttpResponse("# Report\nBUY SPY", {
      status: 200,
      headers: { "Content-Type": "text/markdown" },
    }),
  ),
  http.get("/api/v1/config", () =>
    HttpResponse.json({ defaults: {}, resolved: { llm_provider: "openai" }, overrides: {} }),
  ),
  http.patch("/api/v1/config", async ({ request }) => {
    expect(request.headers.get("X-Requested-With")).toBe("XMLHttpRequest");
    const body = (await request.json()) as Record<string, unknown>;
    expect(body).toHaveProperty("overrides");
    return HttpResponse.json({
      defaults: {},
      resolved: { llm_provider: "anthropic" },
      overrides: { llm_provider: "anthropic" },
    });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("apiClient", () => {
  it("fetches health", async () => {
    const data = await apiClient.getHealth();
    expect(data.status).toBe("ok");
  });

  it("sends X-Requested-With on GET requests", async () => {
    server.use(
      http.get("/api/v1/health", ({ request }) => {
        expect(request.headers.get("X-Requested-With")).toBe(
          "XMLHttpRequest",
        );
        return HttpResponse.json({ status: "ok", db: "ok" });
      }),
    );
    await apiClient.getHealth();
  });

  it("lists analyses without params", async () => {
    const data = await apiClient.listAnalyses();
    expect(data.items).toEqual([]);
    expect(data.total).toBe(0);
  });

  it("lists analyses with params", async () => {
    server.use(
      http.get("/api/v1/analysis", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("page")).toBe("2");
        expect(url.searchParams.get("limit")).toBe("10");
        expect(url.searchParams.get("ticker")).toBe("AAPL");
        return HttpResponse.json({ items: [], total: 0, page: 2, limit: 10 });
      }),
    );
    const data = await apiClient.listAnalyses({
      page: 2,
      limit: 10,
      ticker: "AAPL",
    });
    expect(data.page).toBe(2);
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

  it("cancels analysis", async () => {
    const data = await apiClient.cancelAnalysis("test-uuid");
    expect(data.status).toBe("cancelled");
  });

  it("gets report as text", async () => {
    const text = await apiClient.getReport("test-uuid");
    expect(text).toContain("BUY SPY");
  });

  it("fetches config", async () => {
    const data = await apiClient.getConfig();
    expect(data.resolved).toBeDefined();
  });

  it("updates config", async () => {
    const data = await apiClient.updateConfig({ llm_provider: "anthropic" });
    expect(data.overrides.llm_provider).toBe("anthropic");
  });

  it("throws ApiError with status and detail on non-ok response", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    try {
      await apiClient.getHealth();
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(500);
      expect((err as ApiError).detail).toBe("Server error");
    }
  });

  it("throws on network error", async () => {
    server.use(http.get("/api/v1/health", () => HttpResponse.error()));
    await expect(apiClient.getHealth()).rejects.toThrow();
  });

  it("supports AbortSignal cancellation", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(apiClient.getHealth(controller.signal)).rejects.toThrow();
  });

  it("handles 204 No Content response", async () => {
    server.use(
      http.post("/api/v1/analysis/test-uuid/cancel", () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const result = await apiClient.cancelAnalysis("test-uuid");
    expect(result).toBeUndefined();
  });
});
