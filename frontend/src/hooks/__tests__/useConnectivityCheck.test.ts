import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useConnectivityCheck } from "../useConnectivityCheck";

describe("useConnectivityCheck", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns idle when no url and no provider", () => {
    const { result } = renderHook(() => useConnectivityCheck(undefined));
    expect(result.current.status).toBe("idle");
  });

  it("returns idle when url is empty and no apiKey", () => {
    const { result } = renderHook(() => useConnectivityCheck(""));
    expect(result.current.status).toBe("idle");
  });

  it("transitions to checking when url is provided", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
    const { result } = renderHook(() => useConnectivityCheck("http://localhost:8000", "key123", 10));
    expect(result.current.status).toBe("checking");
  });

  it("transitions to ok on successful response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok", latency_ms: 42 }), { status: 200 }),
    );

    const { result } = renderHook(() => useConnectivityCheck("http://localhost:8000", "key", 10));
    await waitFor(() => expect(result.current.status).toBe("ok"), { timeout: 2000 });
    expect(result.current.latency).toBe(42);
    expect(result.current.errorMsg).toBeNull();
  });

  it("transitions to error on failed response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "error", error: "Invalid key" }), { status: 200 }),
    );

    const { result } = renderHook(() => useConnectivityCheck("http://localhost:8000", "bad", 10));
    await waitFor(() => expect(result.current.status).toBe("error"), { timeout: 2000 });
    expect(result.current.errorMsg).toBe("Invalid key");
  });

  it("transitions to error on HTTP error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 500 }),
    );

    const { result } = renderHook(() => useConnectivityCheck("http://localhost:8000", "key", 10));
    await waitFor(() => expect(result.current.status).toBe("error"), { timeout: 2000 });
    expect(result.current.errorMsg).toContain("500");
  });

  it("transitions to error on network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useConnectivityCheck("http://localhost:8000", "key", 10));
    await waitFor(() => expect(result.current.status).toBe("error"), { timeout: 2000 });
    expect(result.current.errorMsg).toBe("Backend unavailable");
  });

  it("checks with provider and apiKey when no url", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok", latency_ms: 10 }), { status: 200 }),
    );

    const { result } = renderHook(() => useConnectivityCheck(undefined, "key123", 10, "openai"));
    await waitFor(() => expect(result.current.status).toBe("ok"), { timeout: 2000 });
    expect(fetchSpy).toHaveBeenCalledOnce();
    const body = JSON.parse(fetchSpy.mock.calls[0][1]?.body as string);
    expect(body.provider).toBe("openai");
    expect(body.api_key).toBe("key123");
  });
});
