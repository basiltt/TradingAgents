import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useScanAutoTradeProgressWS } from "../useScanAutoTradeProgressWS";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
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
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  message(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) } as MessageEvent);
  }
  closeWith(code: number) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

function ev(partial: Record<string, unknown>) {
  return {
    type: "scan_auto_trade_progress",
    schema_version: 1,
    scan_id: "scan-1",
    stage: "execute_batch",
    status: "active",
    pct: null,
    seq: 1,
    ts: 0,
    ...partial,
  };
}

beforeEach(() => {
  MockWebSocket.instances = [];
  // @ts-expect-error test shim
  global.WebSocket = MockWebSocket;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useScanAutoTradeProgressWS", () => {
  it("projects step + per-account + order state from events", () => {
    const { result } = renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() =>
      ws.message(
        ev({
          stage: "execute_batch",
          status: "active",
          acct_ordinal: 1,
          symbol: "BTCUSDT",
          side: "buy",
          trades_executed: 1,
          seq: 2,
        }),
      ),
    );
    expect(result.current.connected).toBe(true);
    expect(result.current.steps.some((s) => s.stage === "execute_batch")).toBe(true);
    expect(result.current.accounts[0].acctOrdinal).toBe(1);
    expect(result.current.accounts[0].tradesExecuted).toBe(1);
    expect(result.current.orders[0].symbol).toBe("BTCUSDT");
  });

  it("marks terminal on a complete event", () => {
    const { result } = renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.message(ev({ stage: "complete", status: "done", seq: 9 })));
    expect(result.current.terminal).toBe(true);
  });

  it("does NOT reconnect on a permanent close code (1000)", () => {
    vi.useFakeTimers();
    renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.closeWith(1000)); // clean close = terminal, no reconnect
    act(() => vi.advanceTimersByTime(10000));
    expect(MockWebSocket.instances.length).toBe(1);
    vi.useRealTimers();
  });

  it("reconnects on a transient close code (1006)", () => {
    vi.useFakeTimers();
    renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.closeWith(1006)); // abnormal -> reconnect
    act(() => vi.advanceTimersByTime(5000));
    expect(MockWebSocket.instances.length).toBeGreaterThan(1);
    vi.useRealTimers();
  });

  it("ignores malformed payloads (guard-parse)", () => {
    const { result } = renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.message({ type: "garbage" }));
    act(() => ws.message({ foo: "bar" }));
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.orders).toHaveLength(0);
  });

  it("drops events tagged with a stale scan_id", () => {
    const { result } = renderHook(() => useScanAutoTradeProgressWS("scan-1", true));
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.message(ev({ scan_id: "OTHER", symbol: "ETHUSDT", seq: 3 })));
    expect(result.current.orders).toHaveLength(0);
  });

  it("does not open a socket when inactive", () => {
    renderHook(() => useScanAutoTradeProgressWS("scan-1", false));
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
