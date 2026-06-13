import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...p }: { children: React.ReactNode }) => <a {...p}>{children}</a>,
  useNavigate: () => vi.fn(),
}));
vi.mock("@/hooks/useModels", () => ({ useModels: () => ({ data: undefined }) }));
vi.mock("@/hooks/useConnectivityCheck", () => ({
  useConnectivityCheck: () => ({ status: "idle", latency: null, errorMsg: null }),
}));

import { ScheduledScansPage } from "../ScheduledScansPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ScheduledScansPage />
    </QueryClientProvider>,
  );
}

describe("ScheduledScansPage dialog tabs", () => {
  beforeEach(() => localStorage.clear());

  it("opens the New-schedule dialog on the Schedule tab and shows all 5 tabs", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
    for (const label of ["Schedule", "Scan", "Analysis", "Models & Connection", "Auto-trade"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps a representative field per tab reachable (keepMounted), incl. moved/easy-to-miss fields", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    await screen.findByRole("tab", { name: "Schedule" });
    expect(screen.getByText(/Schedule Name/i)).toBeInTheDocument();        // Schedule
    expect(screen.getByText(/Analyst Team/i)).toBeInTheDocument();         // Scan
    expect(screen.getByText(/Output Language/i)).toBeInTheDocument();      // Analysis (moved)
    expect(screen.getByText(/Research Depth/i)).toBeInTheDocument();       // Analysis
    expect(screen.getByText(/Enable Checkpoints/i)).toBeInTheDocument();   // Analysis (easy-to-miss)
    expect(screen.getByText(/API Key/i)).toBeInTheDocument();             // Models
  });

  it("forces the Schedule tab on open-for-new even if another tab was remembered", async () => {
    localStorage.setItem("tradingagents_scheduled_form_tab", "models");
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    // editingId == null ⇒ force Schedule despite the stored "models".
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
  });
});
