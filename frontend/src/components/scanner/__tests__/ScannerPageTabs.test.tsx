import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
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
import { apiClient, type ScanStatus } from "@/api/client";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <ScannerPage />
    </QueryClientProvider>,
  );
  return { qc, ...utils };
}

/** The single non-hidden tab panel. base-ui marks inactive keepMounted panels
 *  `hidden`, so role queries (which skip hidden nodes) return only the active one. */
function activePanel(): HTMLElement {
  return screen.getByRole("tabpanel");
}

function makeStatus(id: string, status: string): ScanStatus {
  return {
    scan_id: id,
    status,
    total: 3,
    completed: status === "completed" ? 3 : 1,
    failed: 0,
    current_batch: 1,
    total_batches: 1,
    current_tickers: [],
    results: [],
    started_at: "2026-06-13T00:00:00Z",
    completed_at: status === "completed" ? "2026-06-13T00:01:00Z" : null,
  };
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

  // Stronger than the keepMounted test: proves each field lives in the CORRECT
  // panel, so a field moved to the wrong tab is caught (not just a dropped field).
  it("places each field under its intended tab (panel-scoped)", () => {
    renderPage();

    // Scan tab is active by default.
    expect(within(activePanel()).getByText("Analysis date")).toBeInTheDocument();
    expect(within(activePanel()).queryByText("Research depth")).toBeNull();
    expect(within(activePanel()).queryByText(/Backend URL/i)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Analysis" }));
    expect(within(activePanel()).getByText("Research depth")).toBeInTheDocument();
    expect(within(activePanel()).getByText("Output language")).toBeInTheDocument();
    expect(within(activePanel()).getByText("Enable checkpoints")).toBeInTheDocument();
    expect(within(activePanel()).getByText("Prompt caching (Anthropic)")).toBeInTheDocument();
    expect(within(activePanel()).queryByText("Analysis date")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Models & Connection" }));
    expect(within(activePanel()).getByText(/Backend URL/i)).toBeInTheDocument();
    expect(within(activePanel()).queryByText("Research depth")).toBeNull();
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

describe("ScannerPage results tabs + auto-switch", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  /** Spy startScan/getScan/listScans so a scan can be driven running→completed
   *  deterministically (no live backend, no fake timers). */
  function stubScanApi() {
    let counter = 0;
    const scans: Record<string, ScanStatus> = {};
    vi.spyOn(apiClient, "listScans").mockResolvedValue({ scans: [] });
    vi.spyOn(apiClient, "startScan").mockImplementation(async () => {
      counter += 1;
      const id = `scan-${counter}`;
      scans[id] = makeStatus(id, "running");
      return { scan_id: id, status: "running" };
    });
    vi.spyOn(apiClient, "getScan").mockImplementation(async (id: string) => {
      const s = scans[id];
      if (!s) throw new Error(`unknown scan ${id}`);
      return s;
    });
    const complete = (id: string) => {
      scans[id] = makeStatus(id, "completed");
    };
    return { complete };
  }

  it("shows Results/Progress/Config tabs once a scan is active, Progress first", async () => {
    stubScanApi();
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Start full market scan/i }));
    // Default results tab is "progress" while running.
    expect(await screen.findByRole("tab", { name: "Progress" })).toHaveAttribute("data-active");
    for (const label of ["Results", "Progress", "Config"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps Cancel reachable from every result tab (lifted above the tab bar)", async () => {
    stubScanApi();
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Start full market scan/i }));
    await screen.findByRole("tab", { name: "Progress" });
    // Cancel is visible on the default (Progress) tab…
    expect(screen.getByRole("button", { name: /^Cancel$/i })).toBeInTheDocument();
    // …and still visible after switching to the Results tab (it lives above the tabs).
    fireEvent.click(screen.getByRole("tab", { name: "Results" }));
    expect(screen.getByRole("button", { name: /^Cancel$/i })).toBeInTheDocument();
  });

  it("auto-switches to Results when the scan completes", async () => {
    const { complete } = stubScanApi();
    const { qc } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Start full market scan/i }));
    await screen.findByRole("tab", { name: "Progress" });
    expect(screen.getByRole("tab", { name: "Progress" })).toHaveAttribute("data-active");

    complete("scan-1");
    await qc.invalidateQueries({ queryKey: ["scan", "scan-1"] });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Results" })).toHaveAttribute("data-active"),
    );
    // The Results panel is now the visible one.
    expect(within(activePanel()).getByText(/No results for this scan/i)).toBeInTheDocument();
  });

  it("does not fight the user: stays put if they pick a tab after the one auto-switch", async () => {
    const { complete } = stubScanApi();
    const { qc } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Start full market scan/i }));
    await screen.findByRole("tab", { name: "Progress" });

    complete("scan-1");
    await qc.invalidateQueries({ queryKey: ["scan", "scan-1"] });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Results" })).toHaveAttribute("data-active"),
    );

    // User goes back to Config; a further refetch of the same completed scan must NOT
    // yank them back to Results (the one-shot guard).
    fireEvent.click(screen.getByRole("tab", { name: "Config" }));
    await qc.invalidateQueries({ queryKey: ["scan", "scan-1"] });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Config" })).toHaveAttribute("data-active"),
    );
    expect(screen.getByRole("tab", { name: "Results" })).not.toHaveAttribute("data-active");
  });

  it("re-arms the auto-switch for the next scan", async () => {
    const { complete } = stubScanApi();
    const { qc } = renderPage();

    // First scan: run → complete → auto-switch to Results.
    fireEvent.click(screen.getByRole("button", { name: /Start full market scan/i }));
    await screen.findByRole("tab", { name: "Progress" });
    complete("scan-1");
    await qc.invalidateQueries({ queryKey: ["scan", "scan-1"] });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Results" })).toHaveAttribute("data-active"),
    );

    // Reset to the config form, then launch a second scan.
    fireEvent.click(screen.getByRole("button", { name: /New Scan/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Start full market scan/i }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Progress" })).toHaveAttribute("data-active"),
    );

    // Second scan completes → must auto-switch again (guard was re-armed on new id).
    complete("scan-2");
    await qc.invalidateQueries({ queryKey: ["scan", "scan-2"] });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Results" })).toHaveAttribute("data-active"),
    );
  });
});
