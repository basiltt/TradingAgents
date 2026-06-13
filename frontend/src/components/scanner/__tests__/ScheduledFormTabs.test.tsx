import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
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

/** The single non-hidden tab panel (base-ui marks inactive keepMounted panels hidden). */
function activePanel(): HTMLElement {
  return screen.getByRole("tabpanel");
}

function openNewDialog() {
  fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
}

describe("ScheduledScansPage dialog tabs", () => {
  beforeEach(() => localStorage.clear());

  it("opens the New-schedule dialog on the Schedule tab and shows all 5 tabs", async () => {
    renderPage();
    openNewDialog();
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
    for (const label of ["Schedule", "Scan", "Analysis", "Models & Connection", "Auto-trade"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps a representative field per tab reachable (keepMounted), incl. moved/easy-to-miss fields", async () => {
    renderPage();
    openNewDialog();
    await screen.findByRole("tab", { name: "Schedule" });
    expect(screen.getByText(/Schedule Name/i)).toBeInTheDocument();        // Schedule
    expect(screen.getByText(/Analyst Team/i)).toBeInTheDocument();         // Scan
    expect(screen.getByText(/Output Language/i)).toBeInTheDocument();      // Analysis (moved)
    expect(screen.getByText(/Research Depth/i)).toBeInTheDocument();       // Analysis
    expect(screen.getByText(/Enable Checkpoints/i)).toBeInTheDocument();   // Analysis (easy-to-miss)
    expect(screen.getByText(/API Key/i)).toBeInTheDocument();             // Models
  });

  // Stronger than keepMounted: proves each field lives in the CORRECT panel, so a
  // field accidentally moved to the wrong tab is caught (not just a dropped field).
  it("places each field under its intended tab (panel-scoped)", async () => {
    renderPage();
    openNewDialog();
    await screen.findByRole("tab", { name: "Schedule" });

    // Schedule tab active on open.
    expect(within(activePanel()).getByText(/Schedule Name/i)).toBeInTheDocument();
    expect(within(activePanel()).queryByText(/Analyst Team/i)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Scan" }));
    expect(within(activePanel()).getByText(/Analyst Team/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Analysis" }));
    expect(within(activePanel()).getByText(/Output Language/i)).toBeInTheDocument();
    expect(within(activePanel()).getByText(/Research Depth/i)).toBeInTheDocument();
    expect(within(activePanel()).getByText(/Enable Checkpoints/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Models & Connection" }));
    expect(within(activePanel()).getByText(/API Key/i)).toBeInTheDocument();
    expect(within(activePanel()).queryByText(/Output Language/i)).toBeNull();
  });

  it("forces the Schedule tab on open-for-new even if another tab was remembered", async () => {
    localStorage.setItem("tradingagents_scheduled_form_tab", "models");
    renderPage();
    openNewDialog();
    // editingId == null ⇒ force Schedule despite the stored "models".
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
  });

  it("persists the active dialog tab on click", async () => {
    renderPage();
    openNewDialog();
    await screen.findByRole("tab", { name: "Schedule" });
    fireEvent.click(screen.getByRole("tab", { name: "Analysis" }));
    expect(localStorage.getItem("tradingagents_scheduled_form_tab")).toBe("analysis");
  });
});

describe("ScheduledScansPage Auto-trade cool-off wayfinding", () => {
  beforeEach(() => localStorage.clear());

  /** An account-bound config with an enabled tier but a blank duration ⇒ the cool-off
   *  gate is invalid, so the Auto-trade tab must flag it and the save hint must point there. */
  function seedInvalidCooloff() {
    localStorage.setItem(
      "tradingagents_auto_trade_configs",
      JSON.stringify([
        { account_id: "acct-1", cooloff_on_success_enabled: true, cooloff_on_success_minutes: null },
      ]),
    );
  }

  it("flags the Auto-trade tab with a badge when a cool-off duration is invalid", async () => {
    seedInvalidCooloff();
    renderPage();
    openNewDialog();
    const autotradeTab = await screen.findByRole("tab", { name: /Auto-trade/i });
    // The danger dot carries an accessible label so the warning isn't colour-only.
    expect(within(autotradeTab).getByLabelText(/needs attention/i)).toBeInTheDocument();
  });

  it("points the save hint at the Auto-trade tab", async () => {
    seedInvalidCooloff();
    renderPage();
    openNewDialog();
    await screen.findByRole("tab", { name: "Schedule" });
    const hint = screen.getByTestId("cooloff-save-hint");
    expect(hint).toHaveTextContent(/Auto-trade tab/i);
  });

  it("shows no badge when cool-off settings are valid", async () => {
    // No invalid seed ⇒ gate valid ⇒ no badge, no hint.
    renderPage();
    openNewDialog();
    const autotradeTab = await screen.findByRole("tab", { name: /Auto-trade/i });
    expect(within(autotradeTab).queryByLabelText(/needs attention/i)).toBeNull();
    expect(screen.queryByTestId("cooloff-save-hint")).toBeNull();
  });
});
