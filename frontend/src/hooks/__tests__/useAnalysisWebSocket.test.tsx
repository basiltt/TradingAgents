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

  it("caps messages at 500", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    for (let i = 1; i <= 510; i++) {
      act(() => ws.simulateMessage({ type: "message", seq: i, sender: "Bot", content: `msg-${i}` }));
    }
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    const msgs = data!.messages as Array<{ seq: number }>;
    expect(msgs.length).toBe(500);
    expect(msgs[0].seq).toBe(11);
    expect(msgs[499].seq).toBe(510);
  });

  it("terminal phase 'completed' closes connection and sets status to disconnected", () => {
    const { wrapper, store } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    expect(result.current.status).toBe("connected");
    act(() => ws.simulateMessage({ type: "progress", phase: "completed", detail: "Analysis done" }));
    expect(ws.close).toHaveBeenCalledWith(1000, "Run terminal");
    expect(result.current.status).toBe("disconnected");
    const runState = store.getState().analysis.activeRuns["run-1"];
    expect(runState?.status).toBe("completed");
  });

  it("terminal phase 'failed' closes connection and sets status to disconnected", () => {
    const { wrapper, store } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "progress", phase: "failed", detail: "Something went wrong" }));
    expect(ws.close).toHaveBeenCalledWith(1000, "Run terminal");
    expect(result.current.status).toBe("disconnected");
    const runState = store.getState().analysis.activeRuns["run-1"];
    expect(runState?.status).toBe("failed");
  });

  it("terminal phase 'cancelled' closes connection and sets status to disconnected", () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "progress", phase: "cancelled", detail: "User cancelled" }));
    expect(ws.close).toHaveBeenCalledWith(1000, "Run terminal");
    expect(result.current.status).toBe("disconnected");
  });

  it("terminal phase marks all in-progress agents as completed", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Put two agents in_progress
    act(() => ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "in_progress" }));
    act(() => ws.simulateMessage({ type: "agent_status", agent: "trader", status: "in_progress" }));
    act(() => ws.simulateMessage({ type: "progress", phase: "completed", detail: "Done" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    const agents = data!.agents as Record<string, string>;
    expect(agents["researcher"]).toBe("completed");
    expect(agents["trader"]).toBe("completed");
  });

  it("agent_status in_progress updates cache immediately", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "in_progress" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    const agents = data!.agents as Record<string, string>;
    expect(agents["researcher"]).toBe("in_progress");
  });

  it("agent_status completed is delayed by MIN_IN_PROGRESS_MS when in_progress just arrived", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Send in_progress and completed back-to-back (0ms elapsed)
    act(() => {
      ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "in_progress" });
      ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "completed" });
    });
    // Completed should not be applied yet (< 1500ms elapsed)
    let data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["researcher"]).toBe("in_progress");
    // After delay, completed should be applied
    act(() => { vi.advanceTimersByTime(1500); });
    data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["researcher"]).toBe("completed");
  });

  it("agent_status completed without prior in_progress shows in_progress briefly then completed", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Send completed without ever sending in_progress
    act(() => ws.simulateMessage({ type: "agent_status", agent: "analyst", status: "completed" }));
    // Should immediately flip to in_progress first
    let data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["analyst"]).toBe("in_progress");
    // After MIN_IN_PROGRESS_MS, should become completed
    act(() => { vi.advanceTimersByTime(1500); });
    data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["analyst"]).toBe("completed");
  });

  it("agent_status completed applies immediately when in_progress has been visible long enough", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "in_progress" }));
    // Advance past the minimum display time
    act(() => { vi.advanceTimersByTime(2000); });
    act(() => ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "completed" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["researcher"]).toBe("completed");
  });

  it("agent_status with other status (failed) updates cache without delay", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "agent_status", agent: "researcher", status: "failed" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.agents as Record<string, string>)["researcher"]).toBe("failed");
  });

  it("non-terminal progress event dispatches running status with currentAgent", () => {
    const { wrapper, store } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "progress", phase: "market_analysis", detail: "Fetching data" }));
    const runState = store.getState().analysis.activeRuns["run-1"];
    expect(runState?.status).toBe("running");
    expect(runState?.currentAgent).toBe("market_analysis");
  });

  it("non-terminal progress updates progress in query cache", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "progress", phase: "market_analysis", detail: "Fetching data" }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect(data!.progress).toEqual({ phase: "market_analysis", detail: "Fetching data" });
  });

  it("does not reconnect on non-retriable code 4404", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateClose(4404));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("does not reconnect on non-retriable code 4403", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateClose(4403));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("status is reconnecting after unexpected close", () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateClose(1006));
    expect(result.current.status).toBe("reconnecting");
  });

  it("attempt counter reflects the current reconnect attempt number", () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    expect(result.current.attempt).toBe(0);
    act(() => MockWebSocket.instances[0].simulateOpen());
    act(() => MockWebSocket.instances[0].simulateClose(1006));
    // After first unexpected close, attempt becomes 1
    expect(result.current.attempt).toBe(1);
    act(() => { vi.advanceTimersByTime(1000); });
    // After reconnect opens, attemptRef resets to 0 internally
    act(() => MockWebSocket.instances[1].simulateOpen());
    // A second unexpected close starts counting from 0 again → attempt becomes 1
    act(() => MockWebSocket.instances[1].simulateClose(1006));
    expect(result.current.attempt).toBe(1);
  });

  it("report_chunk with append=true concatenates content", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "report_chunk", section: "summary", content: "Hello", append: false }));
    act(() => ws.simulateMessage({ type: "report_chunk", section: "summary", content: " World", append: true }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.reports as Record<string, string>)["summary"]).toBe("Hello World");
  });

  it("report_chunk with append=false replaces content", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => ws.simulateMessage({ type: "report_chunk", section: "summary", content: "First", append: false }));
    act(() => ws.simulateMessage({ type: "report_chunk", section: "summary", content: "Second", append: false }));
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect((data!.reports as Record<string, string>)["summary"]).toBe("Second");
  });

  it("ignores malformed JSON messages without throwing", () => {
    const { wrapper } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Simulate raw string message (not JSON)
    expect(() => {
      act(() => ws.onmessage?.({ data: "not valid json" } as MessageEvent));
    }).not.toThrow();
  });

  it("does not reconnect after unmount", () => {
    const { wrapper } = createWrapper();
    const { unmount } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    unmount();
    act(() => ws.simulateClose(1006));
    act(() => { vi.advanceTimersByTime(5000); });
    // Still only the original WebSocket — no reconnect after unmount
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("initial state has empty agents, reports, messages and null stats/progress", () => {
    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    expect(data).toBeDefined();
    expect(data!.agents).toEqual({});
    expect(data!.reports).toEqual({});
    expect(data!.messages).toEqual([]);
    expect(data!.stats).toBeNull();
    expect(data!.progress).toBeNull();
  });

  it("pending completion timers are cleared on unmount", () => {
    const { wrapper, queryClient } = createWrapper();
    const { unmount } = renderHook(() => useAnalysisWebSocket("run-1"), { wrapper });
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Trigger a delayed completion
    act(() => ws.simulateMessage({ type: "agent_status", agent: "analyst", status: "completed" }));
    // Unmount before timer fires
    unmount();
    // Advance past the delay — the update should NOT have been applied (hook is gone)
    act(() => { vi.advanceTimersByTime(2000); });
    // Cache state should still show in_progress (timer was cleared, not in_progress→completed)
    const data = queryClient.getQueryData<Record<string, unknown>>(["analysis", "run-1", "ws-state"]);
    // Either the cache entry doesn't exist or it still shows in_progress — never completed
    if (data) {
      expect((data.agents as Record<string, string>)["analyst"]).not.toBe("completed");
    }
  });
});
