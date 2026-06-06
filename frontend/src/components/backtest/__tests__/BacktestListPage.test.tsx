import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { BacktestListPage } from "../BacktestListPage";
import type { BacktestMetrics, BacktestRun } from "../types";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function run(overrides: Partial<BacktestRun> = {}): BacktestRun {
  return {
    id: "run-abcdef12",
    status: "completed",
    config: {},
    scan_source: {},
    progress_pct: 100,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:03Z",
    created_at: "2026-01-01T00:00:00Z",
    results: {
      // Only the fields the list page reads matter; cast keeps the fixture lean.
      metrics: { net_profit: 500, net_profit_pct: 5 } as unknown as BacktestMetrics,
      equity_curve: [],
      summary: {},
      warnings: [],
    },
    ...overrides,
  };
}

describe("BacktestListPage", () => {
  it("renders a row per run with status + net profit", async () => {
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json([run({ id: "run-1" }), run({ id: "run-2", status: "failed", results: null })]),
      ),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    expect(screen.getAllByTestId("run-row").length).toBe(2);
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
  });

  it("shows empty state when there are no runs", async () => {
    server.use(http.get("/api/v1/backtest", () => HttpResponse.json([])));
    renderWithClient(<BacktestListPage onCreate={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/No backtests yet/i)).toBeInTheDocument());
  });

  it("calls onOpen when Open is clicked", async () => {
    const onOpen = vi.fn();
    server.use(http.get("/api/v1/backtest", () => HttpResponse.json([run({ id: "run-1" })])));
    renderWithClient(<BacktestListPage onOpen={onOpen} />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onOpen).toHaveBeenCalledWith("run-1");
  });

  it("enables Compare once two completed runs are selected", async () => {
    const onCompare = vi.fn();
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json([run({ id: "run-1" }), run({ id: "run-2" })]),
      ),
    );
    renderWithClient(<BacktestListPage onCompare={onCompare} />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Select run-1"));
    fireEvent.click(screen.getByLabelText("Select run-2"));
    const compareBtn = await screen.findByRole("button", { name: /Compare \(2\)/ });
    fireEvent.click(compareBtn);
    expect(onCompare).toHaveBeenCalledWith(["run-1", "run-2"]);
  });

  it("deletes a terminal run", async () => {
    window.confirm = vi.fn(() => true);
    let deleted = false;
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json(deleted ? [] : [run({ id: "run-1" })]),
      ),
      http.delete("/api/v1/backtest/run-1", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Delete run-1"));
    await waitFor(() => expect(screen.queryByTestId("runs-table")).not.toBeInTheDocument());
  });

  it("does not delete when the confirm dialog is dismissed", async () => {
    window.confirm = vi.fn(() => false);
    let deleteHit = false;
    server.use(
      http.get("/api/v1/backtest", () => HttpResponse.json([run({ id: "run-1" })])),
      http.delete("/api/v1/backtest/run-1", () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Delete run-1"));
    await new Promise((r) => setTimeout(r, 50));
    expect(deleteHit).toBe(false);
    expect(screen.getByTestId("runs-table")).toBeInTheDocument();
  });

  it("disables selection and hides Delete for non-terminal runs", async () => {
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json([run({ id: "run-run", status: "running", results: null })]),
      ),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    expect(screen.getByLabelText("Select run-run")).toBeDisabled();
    expect(screen.queryByLabelText("Delete run-run")).not.toBeInTheDocument();
  });

  it("purges a deleted run from the sessionStorage comparison basket", async () => {
    window.confirm = vi.fn(() => true);
    sessionStorage.setItem("backtest_comparison_basket", JSON.stringify(["run-1", "run-2"]));
    let deleted = false;
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json(
          deleted ? [run({ id: "run-2" })] : [run({ id: "run-1" }), run({ id: "run-2" })],
        ),
      ),
      http.delete("/api/v1/backtest/run-1", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Delete run-1"));
    await waitFor(() => {
      const basket = JSON.parse(sessionStorage.getItem("backtest_comparison_basket") ?? "[]");
      expect(basket).toEqual(["run-2"]);
    });
    sessionStorage.clear();
  });

  it("seeds the comparison selection from the sessionStorage basket", async () => {
    sessionStorage.setItem("backtest_comparison_basket", JSON.stringify(["run-1", "run-2"]));
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json([run({ id: "run-1" }), run({ id: "run-2" }), run({ id: "run-3" })]),
      ),
    );
    renderWithClient(<BacktestListPage onCompare={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    // The two basket runs are pre-selected → Compare button shows (2).
    expect(screen.getByRole("button", { name: /Compare \(2\)/ })).toBeInTheDocument();
    expect((screen.getByLabelText("Select run-1") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Select run-3") as HTMLInputElement).checked).toBe(false);
    sessionStorage.clear();
  });

  it("prunes a deleted run from the comparison selection", async () => {
    window.confirm = vi.fn(() => true);
    let deleted = false;
    server.use(
      http.get("/api/v1/backtest", () =>
        HttpResponse.json(
          deleted ? [run({ id: "run-2" })] : [run({ id: "run-1" }), run({ id: "run-2" })],
        ),
      ),
      http.delete("/api/v1/backtest/run-1", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithClient(<BacktestListPage />);
    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Select run-1"));
    fireEvent.click(screen.getByLabelText("Select run-2"));
    expect(await screen.findByRole("button", { name: /Compare \(2\)/ })).toBeInTheDocument();
    // Delete run-1 → selection should drop to just run-2 → Compare hidden (needs >=2).
    fireEvent.click(screen.getByLabelText("Delete run-1"));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Compare/ })).not.toBeInTheDocument());
  });
});
