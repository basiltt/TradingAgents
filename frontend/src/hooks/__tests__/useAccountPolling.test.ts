import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer from "@/store/accounts-slice";
import { uiSlice } from "@/store/ui-slice";
import { analysisSlice } from "@/store/analysis-slice";
import { useAccountPolling } from "../useAccountPolling";
import React from "react";

vi.mock("@/api/client", () => ({
  accountsApi: {
    getDashboard: vi.fn().mockResolvedValue([]),
  },
}));

import { accountsApi } from "@/api/client";

function createWrapper() {
  const store = configureStore({
    reducer: { accounts: accountsReducer, ui: uiSlice.reducer, analysis: analysisSlice.reducer },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(Provider, { store }, children);
}

describe("useAccountPolling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", { value: false, writable: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls on visibility change", async () => {
    vi.useRealTimers();
    renderHook(() => useAccountPolling(), { wrapper: createWrapper() });
    // Simulate visibility change to trigger poll
    Object.defineProperty(document, "hidden", { value: false, writable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => {
      expect(accountsApi.getDashboard).toHaveBeenCalled();
    });
  });

  it("manual refresh calls getDashboard", async () => {
    vi.useRealTimers();
    const { result } = renderHook(() => useAccountPolling(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.refresh();
    });
    expect(accountsApi.getDashboard).toHaveBeenCalled();
  });

  it("manual refresh has cooldown", async () => {
    vi.useRealTimers();
    const { result } = renderHook(() => useAccountPolling(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.refresh();
    });
    const callCount = vi.mocked(accountsApi.getDashboard).mock.calls.length;
    await act(async () => {
      await result.current.refresh();
    });
    expect(vi.mocked(accountsApi.getDashboard).mock.calls.length).toBe(callCount);
  });

  it("isRefreshDisabled is true after manual refresh", async () => {
    vi.useRealTimers();
    const { result } = renderHook(() => useAccountPolling(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.isRefreshDisabled).toBe(true);
  });

  it("skips poll when document is hidden", async () => {
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", { value: true, writable: true });
    vi.mocked(accountsApi.getDashboard).mockClear();
    renderHook(() => useAccountPolling(), { wrapper: createWrapper() });
    await new Promise((r) => setTimeout(r, 100));
    expect(accountsApi.getDashboard).not.toHaveBeenCalled();
  });
});
