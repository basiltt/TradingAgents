/**
 * Tests for useTradeHistory — verifies the filters→params mapping, the injected
 * TERMINAL_STATUSES, the infinite-query key, and the getNextPageParam cursor logic.
 *
 * getNextPageParam is module-private, so it is exercised through its observable
 * effects: result.current.hasNextPage (derived from its return value) and the
 * cursor handed to the next tradesApi.list call on fetchNextPage.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { useTradeHistory } from "../useTradeHistory";
import { tradeQueryKeys } from "@/components/trades/queryKeys";
import { TERMINAL_STATUSES } from "@/components/trades/types";
import type { TradeFilters, TradeListResponse } from "@/components/trades/types";

vi.mock("@/api/client", () => ({
  tradesApi: { list: vi.fn() },
}));

import { tradesApi } from "@/api/client";

const list = tradesApi.list as ReturnType<typeof vi.fn>;

const EMPTY_FILTERS: TradeFilters = {
  account_ids: [],
  status: [],
  symbol: "",
  side: "",
  from_date: "",
  to_date: "",
};

const FULL_FILTERS: TradeFilters = {
  account_ids: ["a1", "a2"],
  status: [],
  symbol: "BTCUSDT",
  side: "buy",
  from_date: "2026-01-01",
  to_date: "2026-02-01",
};

function page(overrides: Partial<TradeListResponse>): TradeListResponse {
  return { items: [], cursor: null, has_more: false, ...overrides };
}

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
  list.mockResolvedValue(page({ has_more: false }));
});

describe("useTradeHistory", () => {
  it("does not fetch when disabled", async () => {
    renderHook(() => useTradeHistory(EMPTY_FILTERS, false), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(
          QueryClientProvider,
          { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
          children,
        ),
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(list).not.toHaveBeenCalled();
  });

  it("fetches the first page with TERMINAL_STATUSES and no cursor for empty filters", async () => {
    const { result } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ status: [...TERMINAL_STATUSES], cursor: undefined }),
    );
    // Empty filters must NOT contribute account_id / symbol / side / dates.
    const arg = list.mock.calls[0][0];
    expect(arg.account_id).toBeUndefined();
    expect(arg.symbol).toBeUndefined();
    expect(arg.side).toBeUndefined();
    expect(arg.from_date).toBeUndefined();
    expect(arg.to_date).toBeUndefined();
  });

  it("maps populated filters into list params (account_id stays an array)", async () => {
    const { result } = renderWithClient(() => useTradeHistory(FULL_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({
        account_id: ["a1", "a2"],
        symbol: "BTCUSDT",
        side: "buy",
        from_date: "2026-01-01",
        to_date: "2026-02-01",
        status: [...TERMINAL_STATUSES],
        cursor: undefined,
      }),
    );
  });

  it("registers the query under the historyList(filters) key", async () => {
    const { result, queryClient } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = queryClient.getQueryData(tradeQueryKeys.historyList(EMPTY_FILTERS)) as
      | { pages: TradeListResponse[] }
      | undefined;
    expect(cached?.pages?.[0]).toEqual(page({ has_more: false }));
  });

  it("exposes hasNextPage=true when has_more and a cursor are present", async () => {
    list.mockResolvedValue(page({ has_more: true, cursor: "cursor-1" }));
    const { result } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
  });

  it("exposes hasNextPage=false when has_more is false", async () => {
    list.mockResolvedValue(page({ has_more: false, cursor: "ignored" }));
    const { result } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("exposes hasNextPage=false when has_more is true but cursor is null", async () => {
    // The `lastPage.cursor ?? undefined` branch: a null cursor yields no next page.
    list.mockResolvedValue(page({ has_more: true, cursor: null }));
    const { result } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("passes the previous page's cursor to the next list call on fetchNextPage", async () => {
    list.mockResolvedValueOnce(page({ has_more: true, cursor: "cursor-1" }));
    list.mockResolvedValueOnce(page({ has_more: false, cursor: null }));

    const { result } = renderWithClient(() => useTradeHistory(EMPTY_FILTERS, true));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);

    await result.current.fetchNextPage();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));

    expect(list.mock.calls[0][0].cursor).toBeUndefined();
    expect(list.mock.calls[1][0].cursor).toBe("cursor-1");
  });
});
