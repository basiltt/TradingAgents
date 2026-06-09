/**
 * Tests for useTradeFilters.
 *
 * Harness choice: the hook only touches the router via useSearch (read) and
 * useNavigate (write), so we mock @tanstack/react-router directly — the same
 * idiom used in src/components/analysis/__tests__/ConfigForm.test.tsx — and pair
 * it with a REAL trades Redux store. A full createRouter/RouterProvider tree would
 * be disproportionate for two leaf hooks and far more brittle.
 *
 * This indirectly covers the module-private filtersToSearchParams() mapping via
 * the navigate() search payload produced by updateFilters().
 */
import { renderHook, act, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import tradesReducer from "@/store/trades-slice";
import { useTradeFilters } from "../useTradeFilters";

// Mutable router state shared with the mock; reset in beforeEach.
const routerState = vi.hoisted(() => ({
  navigate: vi.fn(),
  search: {} as Record<string, string | undefined>,
}));

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => routerState.navigate,
  useSearch: () => routerState.search,
}));

function setup() {
  const store = configureStore({ reducer: { trades: tradesReducer } });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(Provider, { store, children });
  return { store, ...renderHook(() => useTradeFilters(), { wrapper }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  routerState.search = {};
});

describe("useTradeFilters — URL → Redux sync (effect)", () => {
  it("parses comma-separated account_id into an account_ids array", async () => {
    routerState.search = { account_id: "a1,a2" };
    const { store } = setup();
    await waitFor(() =>
      expect(store.getState().trades.filters.account_ids).toEqual(["a1", "a2"]),
    );
  });

  it("maps symbol/side/from_date/to_date search params into filters", async () => {
    routerState.search = {
      symbol: "BTCUSDT",
      side: "buy",
      from_date: "2026-01-01",
      to_date: "2026-02-01",
    };
    const { store } = setup();
    await waitFor(() =>
      expect(store.getState().trades.filters).toMatchObject({
        symbol: "BTCUSDT",
        side: "buy",
        from_date: "2026-01-01",
        to_date: "2026-02-01",
      }),
    );
  });

  it("syncs the active tab from a valid ?tab param", async () => {
    routerState.search = { tab: "history" };
    const { store } = setup();
    await waitFor(() => expect(store.getState().trades.activeTab).toBe("history"));
  });

  it("ignores an invalid ?tab value (keeps default 'active')", async () => {
    routerState.search = { tab: "bogus" };
    const { store } = setup();
    await new Promise((r) => setTimeout(r, 20));
    expect(store.getState().trades.activeTab).toBe("active");
  });

  it("leaves filters at defaults when there are no search params", async () => {
    const { store } = setup();
    await new Promise((r) => setTimeout(r, 20));
    expect(store.getState().trades.filters).toEqual({
      account_ids: [],
      status: [],
      symbol: "",
      side: "",
      from_date: "",
      to_date: "",
    });
  });
});

describe("useTradeFilters — updateFilters (debounced → Redux + navigate)", () => {
  it("dispatches the new filters and navigates with mapped search params", async () => {
    const { result, store } = setup();

    act(() => {
      result.current.updateFilters({
        account_ids: ["x", "y"],
        symbol: "ETHUSDT",
        side: "sell",
        from_date: "2026-03-01",
        to_date: "2026-03-31",
      });
    });

    // navigate fires only after the 300ms debounce window.
    await waitFor(() => expect(routerState.navigate).toHaveBeenCalledTimes(1));

    // Redux received the raw partial (account_ids kept as an array).
    expect(store.getState().trades.filters).toMatchObject({
      account_ids: ["x", "y"],
      symbol: "ETHUSDT",
      side: "sell",
    });

    // navigate received the filtersToSearchParams mapping (account_ids → joined account_id).
    const navArg = routerState.navigate.mock.calls[0][0] as { search: Record<string, string> };
    expect(navArg.search).toMatchObject({
      account_id: "x,y",
      symbol: "ETHUSDT",
      side: "sell",
      from_date: "2026-03-01",
      to_date: "2026-03-31",
    });
  });

  it("merges new search params over the existing URL search", async () => {
    routerState.search = { tab: "history", symbol: "OLD" };
    const { result } = setup();

    act(() => {
      result.current.updateFilters({ symbol: "NEW" });
    });
    await waitFor(() => expect(routerState.navigate).toHaveBeenCalledTimes(1));

    const navArg = routerState.navigate.mock.calls[0][0] as { search: Record<string, string> };
    // Preserves unrelated params (tab) while overriding symbol.
    expect(navArg.search).toMatchObject({ tab: "history", symbol: "NEW" });
  });

  it("omits empty fields from the navigate search payload", async () => {
    const { result } = setup();
    act(() => {
      result.current.updateFilters({ symbol: "", account_ids: [] });
    });
    await waitFor(() => expect(routerState.navigate).toHaveBeenCalledTimes(1));

    const navArg = routerState.navigate.mock.calls[0][0] as { search: Record<string, string> };
    expect(navArg.search.symbol).toBeUndefined();
    expect(navArg.search.account_id).toBeUndefined();
  });
});

describe("useTradeFilters — clearFilters", () => {
  it("resets filters in Redux and navigates with only the active tab", async () => {
    routerState.search = { symbol: "BTCUSDT", tab: "history" };
    const { result, store } = setup();
    // Confirm the URL→Redux sync ran first.
    await waitFor(() => expect(store.getState().trades.filters.symbol).toBe("BTCUSDT"));
    await waitFor(() => expect(store.getState().trades.activeTab).toBe("history"));

    act(() => {
      result.current.clearFilters();
    });

    expect(store.getState().trades.filters).toMatchObject({
      account_ids: [],
      status: [],
      symbol: "",
      side: "",
      from_date: "",
      to_date: "",
    });
    // clearFilters is NOT debounced — navigate fires synchronously with the current tab.
    expect(routerState.navigate).toHaveBeenCalledWith({ search: { tab: "history" } });
  });

  it("uses the default 'active' tab when none was set", () => {
    const { result } = setup();
    act(() => {
      result.current.clearFilters();
    });
    expect(routerState.navigate).toHaveBeenCalledWith({ search: { tab: "active" } });
  });
});
