import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice, setActiveRun } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";
import { AnalysisDashboard } from "../AnalysisDashboard";

vi.mock("@/hooks/useAnalysisWebSocket", () => ({
  useAnalysisWebSocket: () => ({ status: "connected" as const, attempt: 0 }),
  emptyWsState: () => ({ agents: {}, reports: {}, messages: [], stats: null, progress: null }),
}));

function createWrapper(runId: string, status = "running") {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  if (status === "running") {
    store.dispatch(setActiveRun({ runId, ticker: "SPY", status: "running", progress: 0 }));
  }
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(["analysis", runId, "ws-state"], {
    agents: { Trader: "in_progress" },
    reports: { trader: "BUY SPY" },
    messages: [{ sender: "System", content: "Starting", seq: 1 }],
    stats: { tokens_in: 100, tokens_out: 50, llm_calls: 2, tool_calls: 1 },
    progress: { phase: "analyzing", detail: "Running" },
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

describe("AnalysisDashboard", () => {
  it("renders all dashboard panels with WS data", () => {
    const { wrapper } = createWrapper("run-1");
    render(<AnalysisDashboard runId="run-1" />, { wrapper });
    expect(screen.getAllByText("Trader").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/in progress/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/buy spy/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Starting").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/100/).length).toBeGreaterThan(0);
  });

  it("shows connected status", () => {
    const { wrapper } = createWrapper("run-1");
    render(<AnalysisDashboard runId="run-1" />, { wrapper });
    expect(screen.getAllByText(/connected/i).length).toBeGreaterThan(0);
  });

  it("shows empty state when no WS data", () => {
    const store = configureStore({
      reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </Provider>
    );
    render(<AnalysisDashboard runId="run-2" />, { wrapper });
    expect(screen.getAllByText(/waiting for agents/i).length).toBeGreaterThan(0);
  });
});
