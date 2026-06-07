import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Stub the scan list endpoint so the page mounts in isolation; we only care
// about the scanner WebSocket connection lifecycle here.
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      listScans: vi.fn().mockResolvedValue({ scans: [] }),
    },
  };
});

// Router <Link> needs a router context; stub it to a plain anchor so the page
// can render without wiring a full router tree.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
}));

import { ScanHistoryPage } from "../ScanHistoryPage";

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
    this.onclose?.({ code: 1000 } as CloseEvent);
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
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ScanHistoryPage />
    </QueryClientProvider>,
  );
}

describe("ScanHistoryPage — scanner WebSocket BFCache lifecycle", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("opens a single scanner socket on mount", () => {
    renderPage();
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/v1/scanner");
  });

  it("closes the socket on pagehide", () => {
    renderPage();
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
    });
    expect(ws.close).toHaveBeenCalled();
  });

  // Regression: onclose schedules a 3s reconnect unconditionally. The
  // intentional pagehide close must NOT trigger it, or a socket re-opens while
  // backgrounded — defeating BFCache and racing the pageshow reconnect.
  it("does NOT reconnect after the intentional pagehide close", () => {
    renderPage();
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
    });
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("reconnects on pageshow after a pagehide", () => {
    renderPage();
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
    });
    expect(MockWebSocket.instances.length).toBe(1);
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect(MockWebSocket.instances.length).toBe(2);
  });

  it("still reconnects after an unexpected drop (not a pagehide)", () => {
    renderPage();
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    // Unexpected close (server drop) — onclose fires without suppression.
    act(() => {
      ws.readyState = 3;
      ws.onclose?.({ code: 1006 } as CloseEvent);
    });
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(MockWebSocket.instances.length).toBe(2);
  });
});
