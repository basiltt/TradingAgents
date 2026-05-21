import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer from "@/store/accounts-slice";
import { uiSlice } from "@/store/ui-slice";
import { analysisSlice } from "@/store/analysis-slice";
import { AccountsDashboard } from "../AccountsDashboard";

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock("@/api/client", () => ({
  accountsApi: {
    getDashboard: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("@/hooks/useAccountPolling", () => ({
  useAccountPolling: vi.fn(),
}));

import { accountsApi } from "@/api/client";

function createStore() {
  return configureStore({
    reducer: { accounts: accountsReducer, ui: uiSlice.reducer, analysis: analysisSlice.reducer },
  });
}

function renderWithStore(store: ReturnType<typeof createStore>) {
  return render(
    <Provider store={store}>
      <AccountsDashboard />
    </Provider>
  );
}

describe("AccountsDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows empty state when no accounts loaded", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("No accounts connected")).toBeInTheDocument();
    });
  });

  it("shows account cards when accounts exist", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "1", label: "Demo Scalp", account_type: "demo", status: "active", total_equity: "1000", total_perp_upl: "50", positions_count: 2, last_connected_at: new Date().toISOString() },
    ]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("Demo Scalp")).toBeInTheDocument();
    });
  });

  it("shows error state", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("shows aggregate equity when accounts loaded", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "1", label: "A", account_type: "demo", status: "active", total_equity: "500.00", total_perp_upl: "25.00", positions_count: 1 },
      { id: "2", label: "B", account_type: "live", status: "active", total_equity: "1500.00", total_perp_upl: "-10.00", positions_count: 0 },
    ]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("$2000.00")).toBeInTheDocument();
    });
  });

  it("renders filter buttons", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("All")).toBeInTheDocument();
    });
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders Add Account button", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add account/i })).toBeInTheDocument();
    });
  });

  it("fetches dashboard on mount", async () => {
    (accountsApi.getDashboard as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([{ id: "1", label: "Fetched", account_type: "demo", status: "active", total_equity: "100", total_perp_upl: "5", positions_count: 0 }]);
    const store = createStore();
    renderWithStore(store);
    await waitFor(() => {
      expect(screen.getByText("Fetched")).toBeInTheDocument();
    });
  });
});
