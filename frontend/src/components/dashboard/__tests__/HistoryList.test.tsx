import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";
import { HistoryList } from "../HistoryList";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

const server = setupServer(
  http.get("/api/v1/analysis", () =>
    HttpResponse.json({
      items: [
        { run_id: "r1", ticker: "SPY", status: "completed", analysis_date: "2025-06-01", started_at: "2025-06-01T10:00:00Z" },
        { run_id: "r2", ticker: "AAPL", status: "failed", analysis_date: "2025-06-02", started_at: "2025-06-02T10:00:00Z" },
      ],
      total: 2,
      page: 1,
      limit: 20,
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function createWrapper() {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </Provider>
  );
}

describe("HistoryList", () => {
  it("renders analysis history from API", async () => {
    render(<HistoryList />, { wrapper: createWrapper() });
    expect((await screen.findAllByText("SPY")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
  });

  it("shows status badges", async () => {
    render(<HistoryList />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
      expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
    });
  });

  it("shows empty state when no history", async () => {
    server.use(
      http.get("/api/v1/analysis", () =>
        HttpResponse.json({ items: [], total: 0, page: 1, limit: 20 }),
      ),
    );
    render(<HistoryList />, { wrapper: createWrapper() });
    expect(await screen.findByText(/no analyses/i)).toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(<HistoryList />, { wrapper: createWrapper() });
    expect(document.querySelector(".animate-pulse")).toBeTruthy();
  });
});
