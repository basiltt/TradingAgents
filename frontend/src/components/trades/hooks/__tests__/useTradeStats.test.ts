/**
 * Tests for useTradeStats — verifies it calls tradesApi.getStats with the raw
 * account ids and registers the query under the sorted stats query key.
 *
 * The query KEY is sorted (tradeQueryKeys.statsFor) while the API call uses the
 * caller's original order, so the two assertions are intentionally distinct.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { useTradeStats } from "../useTradeStats";
import { tradeQueryKeys } from "@/components/trades/queryKeys";
import type { TradeStatsResponse } from "@/components/trades/types";

vi.mock("@/api/client", () => ({
  tradesApi: { getStats: vi.fn() },
}));

import { tradesApi } from "@/api/client";

const getStats = tradesApi.getStats as ReturnType<typeof vi.fn>;

const STATS: TradeStatsResponse = {
  total_trades: 12,
  open_count: 3,
  win_rate: 0.5,
  avg_pnl: 1.25,
  total_pnl: 15,
};

function renderWithClient<T>(hook: () => T) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, ...renderHook(hook, { wrapper }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  getStats.mockResolvedValue(STATS);
});

describe("useTradeStats", () => {
  it("calls tradesApi.getStats with the provided account ids", async () => {
    const { result } = renderWithClient(() => useTradeStats(["a1", "a2"]));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getStats).toHaveBeenCalledTimes(1);
    expect(getStats).toHaveBeenCalledWith(["a1", "a2"]);
  });

  it("returns the stats payload from the API", async () => {
    const { result } = renderWithClient(() => useTradeStats(["a1"]));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(STATS);
  });

  it("registers the query under the sorted statsFor key", async () => {
    // Pass ids out of order: the API call keeps original order, the cache key sorts.
    const { result, queryClient } = renderWithClient(() => useTradeStats(["b", "a"]));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // API receives the caller's original (unsorted) order.
    expect(getStats).toHaveBeenCalledWith(["b", "a"]);
    // Cache is keyed by the sorted key factory.
    expect(queryClient.getQueryData(tradeQueryKeys.statsFor(["b", "a"]))).toEqual(STATS);
    expect(queryClient.getQueryData(["trades", "stats", ["a", "b"]])).toEqual(STATS);
  });

  it("defaults to an empty account-id list when called with no args", async () => {
    const { result, queryClient } = renderWithClient(() => useTradeStats());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getStats).toHaveBeenCalledWith([]);
    expect(queryClient.getQueryData(["trades", "stats", []])).toEqual(STATS);
  });
});
