/**
 * Tests for the backtestApi namespace — verifies each endpoint method hits the
 * right URL/method and threads params/body correctly. Uses MSW like client.test.ts.
 */
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { backtestApi } from "../client";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("backtestApi.create", () => {
  it("POSTs to /backtest and returns run_id", async () => {
    server.use(
      http.post("/api/v1/backtest", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body.starting_capital).toBe(10000);
        return HttpResponse.json({ run_id: "run-1" }, { status: 201 });
      }),
    );
    const res = await backtestApi.create({
      starting_capital: 10000,
      date_range_start: "2026-01-01T00:00:00Z",
      date_range_end: "2026-01-10T00:00:00Z",
      scan_source: { mode: "date_range" },
    });
    expect(res.run_id).toBe("run-1");
  });
});

describe("backtestApi.list", () => {
  it("GETs /backtest with optional status filter", async () => {
    server.use(
      http.get("/api/v1/backtest", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("status")).toBe("running");
        return HttpResponse.json([{ id: "a", status: "running" }]);
      }),
    );
    const runs = await backtestApi.list({ status: "running" });
    expect(runs).toHaveLength(1);
    expect(runs[0].id).toBe("a");
  });

  it("GETs /backtest with no filter", async () => {
    server.use(http.get("/api/v1/backtest", () => HttpResponse.json([])));
    const runs = await backtestApi.list();
    expect(runs).toEqual([]);
  });
});

describe("backtestApi.get", () => {
  it("GETs /backtest/:id", async () => {
    server.use(
      http.get("/api/v1/backtest/run-1", () =>
        HttpResponse.json({ id: "run-1", status: "completed" }),
      ),
    );
    const run = await backtestApi.get("run-1");
    expect(run.id).toBe("run-1");
  });
});

describe("backtestApi.getTrades", () => {
  it("GETs /backtest/:id/trades with pagination + filters", async () => {
    server.use(
      http.get("/api/v1/backtest/run-1/trades", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("page")).toBe("2");
        expect(url.searchParams.get("limit")).toBe("25");
        expect(url.searchParams.get("side")).toBe("Buy");
        return HttpResponse.json({ trades: [], total: 0, page: 2 });
      }),
    );
    const res = await backtestApi.getTrades("run-1", { page: 2, limit: 25, side: "Buy" });
    expect(res.page).toBe(2);
  });

  it("omits the query string entirely when no params are given", async () => {
    server.use(
      http.get("/api/v1/backtest/run-1/trades", ({ request }) => {
        const url = new URL(request.url);
        // No params → bare path, no trailing "?" and no leftover keys.
        expect(url.search).toBe("");
        return HttpResponse.json({ trades: [], total: 0, page: 1 });
      }),
    );
    const res = await backtestApi.getTrades("run-1");
    expect(res.page).toBe(1);
  });
});

describe("backtestApi.cancel", () => {
  it("POSTs /backtest/:id/cancel", async () => {
    server.use(
      http.post("/api/v1/backtest/run-1/cancel", () =>
        HttpResponse.json({ cancelled: true, run_id: "run-1" }),
      ),
    );
    const res = await backtestApi.cancel("run-1");
    expect(res.cancelled).toBe(true);
  });
});

describe("backtestApi.remove", () => {
  it("DELETEs /backtest/:id (204)", async () => {
    server.use(
      http.delete("/api/v1/backtest/run-1", () => new HttpResponse(null, { status: 204 })),
    );
    await expect(backtestApi.remove("run-1")).resolves.toBeUndefined();
  });
});

describe("backtestApi.compare", () => {
  it("GETs /backtest/compare with run_ids", async () => {
    server.use(
      http.get("/api/v1/backtest/compare", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.getAll("run_ids")).toEqual(["a", "b"]);
        return HttpResponse.json({ runs: [{ id: "a" }, { id: "b" }] });
      }),
    );
    const res = await backtestApi.compare(["a", "b"]);
    expect(res.runs).toHaveLength(2);
  });
});

describe("backtestApi.cacheStatus", () => {
  it("GETs /backtest-cache/status", async () => {
    server.use(
      http.get("/api/v1/backtest-cache/status", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.getAll("symbols")).toEqual(["BTCUSDT"]);
        return HttpResponse.json({
          symbols_total: 1, symbols_cached: 1, symbols_with_gaps: [], ready: true,
        });
      }),
    );
    const res = await backtestApi.cacheStatus(
      ["BTCUSDT"], "5m", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
    );
    expect(res.ready).toBe(true);
  });
});

describe("backtestApi.warmupCache", () => {
  it("POSTs /backtest-cache/warmup (202)", async () => {
    server.use(
      http.post("/api/v1/backtest-cache/warmup", () =>
        HttpResponse.json({ cached: 1, fetched: 0, failed: 0 }, { status: 202 }),
      ),
    );
    const res = await backtestApi.warmupCache(
      ["BTCUSDT"], "5m", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
    );
    expect(res.cached).toBe(1);
  });
});
