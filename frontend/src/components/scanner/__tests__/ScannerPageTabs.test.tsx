import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...p }: { children: React.ReactNode }) => <a {...p}>{children}</a>,
}));
vi.mock("@/hooks/useModels", () => ({ useModels: () => ({ data: undefined }) }));
vi.mock("@/hooks/useConnectivityCheck", () => ({
  useConnectivityCheck: () => ({ status: "idle", latency: null, errorMsg: null }),
}));
// Minimal WebSocket stub so the page mounts without a live socket.
class WS {
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}
vi.stubGlobal("WebSocket", WS as unknown as typeof WebSocket);

import { ScannerPage } from "../ScannerPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ScannerPage />
    </QueryClientProvider>,
  );
}

describe("ScannerPage config tabs", () => {
  beforeEach(() => localStorage.clear());

  it("renders the three config tabs", () => {
    renderPage();
    expect(screen.getByRole("tab", { name: "Scan" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Analysis" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Models & Connection" })).toBeInTheDocument();
  });

  it("defaults to the Scan tab", () => {
    renderPage();
    expect(screen.getByRole("tab", { name: "Scan" })).toHaveAttribute("data-active");
  });

  it("keeps a representative field from each tab reachable (keepMounted)", () => {
    renderPage();
    // keepMounted ⇒ all panels are in the DOM regardless of the active tab.
    expect(screen.getByText("Analysis date")).toBeInTheDocument();        // Scan
    expect(screen.getByText("Research depth")).toBeInTheDocument();       // Analysis
    expect(screen.getByText(/Backend URL/i)).toBeInTheDocument();         // Models
    // The easy-to-miss Analysis fields the redesign must not drop:
    expect(screen.getByText("Output language")).toBeInTheDocument();
    expect(screen.getByText("Enable checkpoints")).toBeInTheDocument();
    expect(screen.getByText("Prompt caching (Anthropic)")).toBeInTheDocument();
  });

  it("persists the active config tab on click", () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Models & Connection" }));
    expect(localStorage.getItem("tradingagents_scanner_config_tab")).toBe("models");
  });

  it("keeps the Auto-trade section and Start button below the tabs", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /Start full market scan/i })).toBeInTheDocument();
  });
});
