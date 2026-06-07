import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { uiSlice } from "@/store/ui-slice";
import accountsReducer from "@/store/accounts-slice";
import tradesReducer from "@/store/trades-slice";
import aiManagerReducer from "@/store/ai-manager-slice";

// The hook performs network I/O on socket open (dashboard refresh + active-trade
// fetch). Stub those so the hook can mount in isolation and we can focus purely
// on the WebSocket connection lifecycle.
vi.mock("@/api/client", () => ({
  accountsApi: { getDashboard: vi.fn().mockResolvedValue([]) },
}));
vi.mock("@/components/trades/hooks/useTradePolling", () => ({
  fetchAllActiveTrades: vi.fn().mockResolvedValue(undefined),
}));

import { useAccountWebSocket } from "../useAccountWebSocket";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readyState = 0;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = 3;
  });
  CONNECTING = 0;
  OPEN = 1;
  CLOSING = 2;
  CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  simulateOpen() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  simulateClose(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

function createWrapper() {
  const store = configureStore({
    reducer: {
      ui: uiSlice.reducer,
      accounts: accountsReducer,
      trades: tradesReducer,
      aiManager: aiManagerReducer,
    },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </Provider>
    ),
  };
}

describe("useAccountWebSocket — BFCache lifecycle", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("opens a single socket on mount", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAccountWebSocket(), { wrapper });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("closes the socket on pagehide (restores BFCache eligibility)", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAccountWebSocket(), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
    });
    expect(ws.close).toHaveBeenCalled();
  });

  // Regression guard: this hook's onclose schedules a reconnect unconditionally.
  // The intentional pagehide close MUST NOT trigger that reconnect — otherwise a
  // new socket re-opens ~2s later, defeating BFCache and racing the pageshow
  // reconnect into a duplicate connection.
  it("does NOT reconnect after the intentional pagehide close", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAccountWebSocket(), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
      ws.simulateClose(1000);
    });
    // Advance well past the reconnect backoff window — still only one socket.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("reconnects on pageshow after a pagehide", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAccountWebSocket(), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
      ws.simulateClose(1000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("normal unexpected close still reconnects (suppress flag is scoped to pagehide)", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAccountWebSocket(), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // An unexpected drop (no pagehide) should reconnect as before.
    act(() => ws.simulateClose(1006));
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });
});
