/**
 * Tests for useBacktestPolling — verifies it polls a running run and stops on
 * terminal status. Mocks backtestApi.get and drives TanStack Query.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { useBacktestPolling, BACKTEST_POLL_INTERVAL_MS } from "../useBacktestPolling";

vi.mock("@/api/client", () => ({
  backtestApi: { get: vi.fn() },
}));

import { backtestApi } from "@/api/client";

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useBacktestPolling", () => {
  it("is disabled when runId is undefined (no fetch)", async () => {
    renderHook(() => useBacktestPolling(undefined), { wrapper: createWrapper() });
    await new Promise((r) => setTimeout(r, 20));
    expect(backtestApi.get).not.toHaveBeenCalled();
  });

  it("fetches the run for a given runId", async () => {
    (backtestApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "run-1",
      status: "completed",
    });
    const { result } = renderHook(() => useBacktestPolling("run-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data?.id).toBe("run-1"));
    expect(backtestApi.get).toHaveBeenCalledWith("run-1", expect.anything());
  });

  it("stops polling once the run is terminal (completed)", async () => {
    (backtestApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "run-1",
      status: "completed",
    });
    const { result } = renderHook(() => useBacktestPolling("run-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data?.status).toBe("completed"));
    const callsAfterFirst = (backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length;
    // Wait > 2 poll intervals; since terminal, no further fetch should occur.
    await new Promise((r) => setTimeout(r, BACKTEST_POLL_INTERVAL_MS * 2 + 100));
    expect((backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterFirst);
  });

  it("keeps polling while the run is running", async () => {
    (backtestApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "run-1",
      status: "running",
    });
    renderHook(() => useBacktestPolling("run-1"), { wrapper: createWrapper() });
    await waitFor(() => expect(backtestApi.get).toHaveBeenCalled());
    const first = (backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length;
    // After one poll interval, it should fetch again (still running).
    await new Promise((r) => setTimeout(r, BACKTEST_POLL_INTERVAL_MS + 200));
    expect((backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(first);
  });

  it("stops polling on terminal failed status", async () => {
    (backtestApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "run-1",
      status: "failed",
    });
    const { result } = renderHook(() => useBacktestPolling("run-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data?.status).toBe("failed"));
    const calls = (backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length;
    await new Promise((r) => setTimeout(r, BACKTEST_POLL_INTERVAL_MS * 2 + 100));
    expect((backtestApi.get as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls);
  });

  it("stops polling after transitioning running → completed", async () => {
    const get = backtestApi.get as ReturnType<typeof vi.fn>;
    get.mockResolvedValueOnce({ id: "run-1", status: "running" });
    get.mockResolvedValue({ id: "run-1", status: "completed" });
    const { result } = renderHook(() => useBacktestPolling("run-1"), {
      wrapper: createWrapper(),
    });
    // The 2nd fetch (→completed) only fires after one poll interval, so allow >interval.
    await waitFor(() => expect(result.current.data?.status).toBe("completed"), {
      timeout: BACKTEST_POLL_INTERVAL_MS + 1500,
    });
    const calls = get.mock.calls.length;
    // Once terminal, polling must cease even though it was active a moment ago.
    await new Promise((r) => setTimeout(r, BACKTEST_POLL_INTERVAL_MS + 200));
    expect(get.mock.calls.length).toBe(calls);
  }, 10000);
});
