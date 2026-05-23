import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice, setActiveRun } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";
import { HomeDashboard } from "../HomeDashboard";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

function createWrapper(activeRuns = false) {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  if (activeRuns) {
    store.dispatch(setActiveRun({ runId: "r1", ticker: "SPY", status: "running", progress: 50 }));
  }
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    store,
    queryClient,
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </Provider>
    ),
  };
}

describe("HomeDashboard", () => {
  it("shows welcome and start CTA when no active runs", () => {
    const { wrapper } = createWrapper(false);
    render(<HomeDashboard />, { wrapper });
    expect(
      screen.getByRole("heading", { name: /trading workspace/i }),
    ).toBeInTheDocument();
    const startLinks = screen.getAllByRole("link", { name: /start analysis/i });
    expect(startLinks.length).toBeGreaterThan(0);
    expect(startLinks[0]).toHaveAttribute("href", "/analysis/new");
  });

  it("shows active analysis cards", () => {
    const { wrapper } = createWrapper(true);
    render(<HomeDashboard />, { wrapper });
    expect(screen.getByText(/spy/i)).toBeInTheDocument();
    expect(screen.getAllByText(/running/i).length).toBeGreaterThan(0);
  });
});
