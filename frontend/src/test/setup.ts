import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// AI-CONTEXT: Global WebSocket stub for the test environment.
//
// Several route-level components (e.g. RootLayout via useAccountWebSocket) open a
// real WebSocket on mount. Under happy-dom that resolves to ws://localhost:3000,
// which has no server — producing ECONNREFUSED / "socket hang up" noise on every
// run and a (small) risk of flaky timing. Tests never need a live socket, so we
// replace the global with an inert mock that records instances but never connects.
// Suites that specifically assert WebSocket behavior can still spy on this class or
// drive its handlers manually.
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(): void {
    /* inert — no real socket */
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: 1000, reason: "test", wasClean: true });
  }

  addEventListener(): void {
    /* inert */
  }

  removeEventListener(): void {
    /* inert */
  }
}

vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

// AI-CONTEXT: We deliberately do NOT stub global fetch here. A global fetch stub
// interferes with suites that use vi.spyOn(globalThis,"fetch").mockResolvedValueOnce
// (e.g. useConnectivityCheck) and with MSW's own fetch interception. Instead, tests
// that render fetch-making components mock the API layer locally (vi.mock or MSW).
// The routing smoke test mocks @/api/client to avoid the unmocked-fetch → port-3000
// ECONNREFUSED noise. See src/routes/__tests__/routing.test.tsx.
