import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice, setActiveRun } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";
import { useAnalysisWebSocket } from "../useAnalysisWebSocket";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readyState = 0;
  send = vi.fn();
  close = vi.fn();
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

  simulateMessage(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }

  simulateClose(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }

  simulateError() {
    this.onerror?.(new Event("error"));
  }
}

function createWrapper() {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  store.dispatch(setActiveRun({ runId: "run-1", ticker: "SPY", status: "running", progress: 0 }));
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    store,
    queryClient,
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </Provider>
    ),
  };
}

describe("useAnalysisWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("connects to the correct URL", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/v1/analysis/run-1");
  });

  it("sends replay on open", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: "replay" }));
  });

  it("responds to heartbeat with pong", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    ws.send.mockClear();
    act(() => ws.simulateMessage({ type: "heartbeat", seq: 1 }));
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: "pong" }));
  });

  it("updates Redux state on progress event", () => {
    const { wrapper, store } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "progress", seq: 2, phase: "analyzing", detail: "Running market analysis" }));
    const state = store.getState().analysis.activeRuns["run-1"];
    expect(state.currentAgent).toBe("analyzing");
  });

  it("updates query cache on stats event", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() =>
      ws.simulateMessage({
        type: "stats",
        seq: 3,
        tokens_in: 100,
        tokens_out: 50,
        llm_calls: 3,
        tool_calls: 2,
      }),
    );
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect(data).toBeDefined();
    expect(data!.stats).toEqual(
      expect.objectContaining({ tokens_in: 100, tokens_out: 50 }),
    );
  });

  it("cleans up WebSocket on unmount", () => {
    const { wrapper } = createWrapper();
    const { unmount } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    unmount();
    expect(ws.close).toHaveBeenCalled();
  });

  it("reconnects with backoff on unexpected close", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateClose(1006));
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect on clean close (1000)", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateClose(1000));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("stops reconnecting after max attempts", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    // Exhaust all 10 reconnect attempts
    for (let i = 0; i <= 10; i++) {
      const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
      act(() => ws.simulateOpen());
      act(() => ws.simulateClose(1006));
      act(() => { vi.advanceTimersByTime(60_000); });
    }
    const countAfterExhaustion = MockWebSocket.instances.length;
    // No more reconnections should happen
    act(() => { vi.advanceTimersByTime(120_000); });
    expect(MockWebSocket.instances.length).toBe(countAfterExhaustion);
  });

  it("accumulates messages in query cache", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "message", seq: 1, sender: "System", content: "Hello" }));
    act(() => ws.simulateMessage({ type: "message", seq: 2, sender: "Tool", content: "Done" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.messages as unknown[]).length).toBe(2);
  });

  it("accumulates report chunks in query cache", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "report_chunk", seq: 1, section: "trader", content: "BUY" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect(data!.reports).toBeDefined();
  });

  it("returns connection status and attempt", () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    expect(result.current.status).toBe("connecting");
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    expect(result.current.status).toBe("connected");
  });
});
