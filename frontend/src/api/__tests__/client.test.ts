/**
 * Tests for the API client module — covers retry logic, error handling,
 * ApiError.detail extraction, and method-based retry gating.
 *
 * Retry behaviour (from client.ts):
 *   - MAX_RETRIES = 2  → up to 3 total attempts for GET/HEAD
 *   - Retriable statuses: 502, 503, 504
 *   - POST/PATCH/DELETE: 0 retries (maxAttempts = 0)
 *   - Network errors wrapped in ApiError(0, …)
 *   - sleep(RETRY_DELAY_MS * attempt) between attempts — bypassed with fake timers
 */
import {
  describe,
  it,
  expect,
  beforeAll,
  afterAll,
  afterEach,
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { apiClient, ApiError } from "../client";

// ---------------------------------------------------------------------------
// MSW server — default happy-path handlers shared across describe blocks
// ---------------------------------------------------------------------------
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
    HttpResponse.json({
      defaults: {},
      resolved: { llm_provider: "openai" },
      overrides: {},
    }),
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

// ---------------------------------------------------------------------------
// Helper — run a promise while advancing fake timers so sleep() resolves
// ---------------------------------------------------------------------------
async function runWithFakeTimers<T>(fn: () => Promise<T>): Promise<T> {
  vi.useFakeTimers();
  try {
    const promise = fn();
    // Advance timers in a loop until the promise settles.
    // Each retry sleeps RETRY_DELAY_MS * attempt (1 s, 2 s).  We advance
    // by 5 s per tick which covers any retry window in one shot.
    for (let i = 0; i < 10; i++) {
      await vi.advanceTimersByTimeAsync(5_000);
    }
    return await promise;
  } finally {
    vi.useRealTimers();
  }
}

// Same helper but expects the promise to reject.
// The rejection handler is attached immediately (before timer advancement) to
// prevent "unhandled rejection" noise during the sleep() intervals.
async function runWithFakeTimersRejected(fn: () => Promise<unknown>): Promise<unknown> {
  vi.useFakeTimers();
  try {
    const promise = fn();
    // Attach rejection handler right away so the promise is never "unhandled"
    const settled = promise.then(
      (v) => ({ ok: true as const, value: v }),
      (e) => ({ ok: false as const, error: e }),
    );
    for (let i = 0; i < 10; i++) {
      await vi.advanceTimersByTimeAsync(5_000);
    }
    const result = await settled;
    if (!result.ok) return result.error;
    throw new Error(`Expected rejection but resolved with ${JSON.stringify(result.value)}`);
  } finally {
    vi.useRealTimers();
  }
}

// ---------------------------------------------------------------------------
// Existing happy-path and basic error tests
// ---------------------------------------------------------------------------
describe("apiClient — happy path", () => {
  it("fetches health", async () => {
    const data = await apiClient.getHealth();
    expect(data.status).toBe("ok");
  });

  it("sends X-Requested-With header on GET requests", async () => {
    server.use(
      http.get("/api/v1/health", ({ request }) => {
        expect(request.headers.get("X-Requested-With")).toBe("XMLHttpRequest");
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

  it("lists analyses with page/limit/ticker params", async () => {
    server.use(
      http.get("/api/v1/analysis", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("page")).toBe("2");
        expect(url.searchParams.get("limit")).toBe("10");
        expect(url.searchParams.get("ticker")).toBe("AAPL");
        return HttpResponse.json({ items: [], total: 0, page: 2, limit: 10 });
      }),
    );
    const data = await apiClient.listAnalyses({ page: 2, limit: 10, ticker: "AAPL" });
    expect(data.page).toBe(2);
  });

  it("starts analysis and returns run_id", async () => {
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

  it("gets report as plain text", async () => {
    const text = await apiClient.getReport("test-uuid");
    expect(text).toContain("BUY SPY");
  });

  it("fetches config", async () => {
    const data = await apiClient.getConfig();
    expect(data.resolved).toBeDefined();
  });

  it("updates config via PATCH", async () => {
    const data = await apiClient.updateConfig({ llm_provider: "anthropic" });
    expect(data.overrides.llm_provider).toBe("anthropic");
  });

  it("returns undefined on 204 No Content", async () => {
    server.use(
      http.post("/api/v1/analysis/test-uuid/cancel", () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const result = await apiClient.cancelAnalysis("test-uuid");
    expect(result).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// ApiError — detail extraction from various response shapes
// ---------------------------------------------------------------------------
describe("ApiError — detail extraction", () => {
  it("throws ApiError with correct status and string detail", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({ detail: "Server exploded" }, { status: 500 }),
      ),
    );
    await expect(apiClient.getHealth()).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      detail: "Server exploded",
    });
  });

  it("throws ApiError and extracts array detail (FastAPI validation errors)", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json(
          {
            detail: [
              { loc: ["body", "ticker"], msg: "field required" },
              { loc: ["body", "analysis_date"], msg: "invalid date" },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    const err = await apiClient.getHealth().catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    // Both field messages should appear, joined by "; "
    expect(err.detail).toContain("ticker: field required");
    expect(err.detail).toContain("analysis_date: invalid date");
  });

  it("throws ApiError with statusText when body is non-JSON", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        new HttpResponse("<html>Bad Gateway</html>", {
          status: 502,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );
    // The detail falls back to res.statusText when JSON parse fails
    const err = await runWithFakeTimersRejected(() => apiClient.getHealth()) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    // detail should be the HTTP reason phrase (statusText), not the HTML body
    expect(typeof err.detail).toBe("string");
    expect(err.detail.length).toBeGreaterThan(0);
  });

  it("throws ApiError with status 0 on network error", async () => {
    server.use(http.get("/api/v1/health", () => HttpResponse.error()));
    const err = await apiClient.getHealth().catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.detail).toMatch(/network error/i);
  });
});

// ---------------------------------------------------------------------------
// Retry behaviour — GET retries on 502 / 503 / 504
// ---------------------------------------------------------------------------
describe("retry logic — GET requests", () => {
  it("retries once on 503 and succeeds on second attempt", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        if (callCount < 2) {
          return HttpResponse.json({ detail: "unavailable" }, { status: 503 });
        }
        return HttpResponse.json({ status: "ok", db: "ok" });
      }),
    );

    const data = await runWithFakeTimers(() => apiClient.getHealth());
    expect(data.status).toBe("ok");
    expect(callCount).toBe(2);
  });

  it("retries twice on 502 and succeeds on third attempt (MAX_RETRIES=2)", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        if (callCount < 3) {
          return HttpResponse.json({ detail: "bad gateway" }, { status: 502 });
        }
        return HttpResponse.json({ status: "ok", db: "ok" });
      }),
    );

    const data = await runWithFakeTimers(() => apiClient.getHealth());
    expect(data.status).toBe("ok");
    expect(callCount).toBe(3);
  });

  it("throws ApiError after exhausting all retries on 503", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({ detail: "service unavailable" }, { status: 503 }),
      ),
    );

    const err = await runWithFakeTimersRejected(() => apiClient.getHealth()) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
  });

  it("retries on 504 Gateway Timeout", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        if (callCount < 2) {
          return HttpResponse.json({ detail: "timeout" }, { status: 504 });
        }
        return HttpResponse.json({ status: "ok", db: "ok" });
      }),
    );

    const data = await runWithFakeTimers(() => apiClient.getHealth());
    expect(data.status).toBe("ok");
    expect(callCount).toBe(2);
  });

  it("does NOT retry on 4xx errors (e.g. 404 Not Found)", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
    );

    const err = await apiClient.getHealth().catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    // Only one attempt — no retry on 4xx
    expect(callCount).toBe(1);
  });

  it("does NOT retry on 400 Bad Request", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        return HttpResponse.json({ detail: "bad request" }, { status: 400 });
      }),
    );

    await apiClient.getHealth().catch(() => undefined);
    expect(callCount).toBe(1);
  });

  it("does NOT retry on 401 Unauthorized", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        return HttpResponse.json({ detail: "unauthorized" }, { status: 401 });
      }),
    );

    await apiClient.getHealth().catch(() => undefined);
    expect(callCount).toBe(1);
  });

  it("does NOT retry on 500 Internal Server Error (not in retriable set)", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/health", () => {
        callCount++;
        return HttpResponse.json({ detail: "internal error" }, { status: 500 });
      }),
    );

    await apiClient.getHealth().catch(() => undefined);
    expect(callCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Retry behaviour — POST/PATCH/DELETE do NOT retry (non-idempotent)
// ---------------------------------------------------------------------------
describe("retry logic — mutating methods (POST/PATCH/DELETE)", () => {
  it("POST does NOT retry on 503", async () => {
    let callCount = 0;
    server.use(
      http.post("/api/v1/analysis", () => {
        callCount++;
        return HttpResponse.json({ detail: "unavailable" }, { status: 503 });
      }),
    );

    const err = await apiClient
      .startAnalysis({ ticker: "SPY", analysis_date: "2025-01-01" })
      .catch((e) => e) as ApiError;

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    // Exactly one attempt — no retry for POST
    expect(callCount).toBe(1);
  });

  it("PATCH does NOT retry on 502", async () => {
    let callCount = 0;
    server.use(
      http.patch("/api/v1/config", () => {
        callCount++;
        return HttpResponse.json({ detail: "bad gateway" }, { status: 502 });
      }),
    );

    await apiClient.updateConfig({ llm_provider: "openai" }).catch(() => undefined);
    expect(callCount).toBe(1);
  });

  it("POST does NOT retry on network error", async () => {
    let callCount = 0;
    server.use(
      http.post("/api/v1/analysis", () => {
        callCount++;
        return HttpResponse.error();
      }),
    );

    const err = await apiClient
      .startAnalysis({ ticker: "SPY", analysis_date: "2025-01-01" })
      .catch((e) => e) as ApiError;

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(callCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Network error wrapping
// ---------------------------------------------------------------------------
describe("network error handling", () => {
  it("wraps fetch TypeError in ApiError with status 0", async () => {
    server.use(http.get("/api/v1/health", () => HttpResponse.error()));
    const err = await apiClient.getHealth().catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/API error 0/);
  });

  it("ApiError.message contains status and detail", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({ detail: "Gone" }, { status: 410 }),
      ),
    );
    const err = await apiClient.getHealth().catch((e) => e) as ApiError;
    expect(err.message).toContain("410");
    expect(err.message).toContain("Gone");
  });

  it("AbortError is re-thrown as-is (not wrapped in ApiError)", async () => {
    const controller = new AbortController();
    controller.abort();
    const err = await apiClient.getHealth(controller.signal).catch((e) => e);
    // DOMException with name AbortError should propagate unchanged
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
  });

  it("network errors after retries throw ApiError with status 0", async () => {
    server.use(http.get("/api/v1/health", () => HttpResponse.error()));

    const err = await runWithFakeTimersRejected(() => apiClient.getHealth()) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });
});
