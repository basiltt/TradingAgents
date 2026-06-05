import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { BacktestResultsPage } from "../BacktestResultsPage";
import type { BacktestMetrics, BacktestRun } from "../types";

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  toastSuccess.mockClear();
  toastError.mockClear();
});
afterAll(() => server.close());

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function metrics(): BacktestMetrics {
  return {
    total_trades: 5,
    winners: 3,
    losers: 2,
    net_profit: 500,
    net_profit_pct: 5,
    gross_profit: 900,
    gross_loss: -400,
    win_rate: 60,
    profit_factor: 2.25,
    sharpe: 1.2,
    sortino: 1.6,
    max_dd_pct: 7,
    max_dd_usd: 700,
    max_dd_duration_hours: 12,
    avg_dd_pct: 3,
    max_run_up_pct: 10,
    max_run_up_usd: 1000,
    avg_trade: 100,
    avg_win: 300,
    avg_loss: -200,
    avg_win_loss_ratio: 1.5,
    largest_win: 400,
    largest_loss: -250,
    total_commission: 12,
    recovery_factor: 0.7,
    cagr: 50,
    calmar: 7,
    expectancy: 100,
    max_consecutive_wins: 2,
    max_consecutive_losses: 1,
    max_consecutive_wins_usd: 600,
    max_consecutive_losses_usd: -200,
    avg_trade_duration_hours: 8,
    avg_winner_duration_hours: 7,
    avg_loser_duration_hours: 10,
    max_trade_duration_hours: 20,
    final_equity: 10500,
    by_direction: {
      all: { total_trades: 5, winners: 3, losers: 2, net_profit: 500, win_rate: 60, avg_trade: 100, avg_win: 300, avg_loss: -200 },
      long: { total_trades: 3, winners: 2, losers: 1, net_profit: 400, win_rate: 66.7, avg_trade: 133, avg_win: 300, avg_loss: -200 },
      short: { total_trades: 2, winners: 1, losers: 1, net_profit: 100, win_rate: 50, avg_trade: 50, avg_win: 300, avg_loss: -200 },
    },
  };
}

function run(overrides: Partial<BacktestRun> = {}): BacktestRun {
  return {
    id: "run-123",
    status: "completed",
    config: {},
    scan_source: {},
    progress_pct: 100,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:03Z",
    created_at: "2026-01-01T00:00:00Z",
    results: {
      metrics: metrics(),
      equity_curve: [
        { ts: "2026-01-01T00:00:00Z", equity: 10000 },
        { ts: "2026-01-02T00:00:00Z", equity: 10500 },
      ],
      summary: {},
      warnings: [],
    },
    ...overrides,
  };
}

describe("BacktestResultsPage", () => {
  it("renders metrics for a completed run", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(screen.getByTestId("backtest-results-page")).toBeInTheDocument());
    expect(screen.getByTestId("status-badge")).toHaveAttribute("data-status", "completed");
    // Metrics grid renders the overview tab by default
    expect(await screen.findByTestId("metrics-grid")).toBeInTheDocument();
  });

  it("renders the equity chart when the Equity tab is selected", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    fireEvent.click(await screen.findByRole("tab", { name: /equity/i }));
    expect(await screen.findByTestId("equity-curve-chart")).toBeInTheDocument();
  });

  it("renders the Analysis tab with aggregated charts", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({
          trades: [
            {
              id: 1, symbol: "BTCUSDT", side: "buy", entry_price: 1, exit_price: 2, qty: 1, leverage: 1,
              entry_time: "2026-01-01T00:00:00Z", exit_time: "2026-01-01T04:00:00Z", pnl: 100, pnl_pct: 5,
              fees_paid: 0, close_reason: "take_profit", mfe_pct: 1, mae_pct: 0, signal_score: 50, signal_confidence: "high", scan_id: "s1",
            },
          ],
          total: 1,
          page: 1,
        }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    fireEvent.click(await screen.findByRole("tab", { name: /analysis/i }));
    expect(await screen.findByTestId("backtest-analysis-tab")).toBeInTheDocument();
  });

  it("shows the hero metric strip for a completed run", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    expect(await screen.findByTestId("hero-metrics")).toBeInTheDocument();
  });

  it("adds the run to the comparison basket", async () => {
    sessionStorage.clear();
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    const addBtn = await screen.findByRole("button", { name: /add to comparison/i });
    fireEvent.click(addBtn);
    expect(await screen.findByRole("button", { name: /in comparison/i })).toBeInTheDocument();
    expect(sessionStorage.getItem("backtest_comparison_basket")).toContain("run-123");
  });

  it("offers Retry on a failed run and calls onRetry with the config", async () => {
    const onRetry = vi.fn();
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "failed", error_message: "boom", results: null, config: { leverage: 7 } })),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" onRetry={onRetry} />);
    fireEvent.click(await screen.findByRole("button", { name: /retry with same settings/i }));
    expect(onRetry).toHaveBeenCalledWith({ leverage: 7 });
  });

  it("calls cancel when the Cancel button is confirmed", async () => {
    window.confirm = vi.fn(() => true);
    let cancelHit = false;
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "running", results: null })),
      ),
      http.post("/api/v1/backtest/run-123/cancel", () => {
        cancelHit = true;
        return HttpResponse.json({ cancelled: true, run_id: "run-123" });
      }),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    fireEvent.click(await screen.findByRole("button", { name: /^cancel$/i }));
    await waitFor(() => expect(cancelHit).toBe(true));
  });

  it("does not cancel when the confirm dialog is dismissed", async () => {
    window.confirm = vi.fn(() => false);
    let cancelHit = false;
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "running", results: null })),
      ),
      http.post("/api/v1/backtest/run-123/cancel", () => {
        cancelHit = true;
        return HttpResponse.json({ cancelled: true, run_id: "run-123" });
      }),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    fireEvent.click(await screen.findByRole("button", { name: /^cancel$/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(cancelHit).toBe(false);
  });

  it("shows a running state with progress", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "running", progress_pct: 42, results: null })),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(screen.getByTestId("backtest-running")).toBeInTheDocument());
    expect(screen.getByText(/42%/)).toBeInTheDocument();
  });

  it("shows the error message for a failed run", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(
          run({ status: "failed", error_message: "Insufficient kline coverage", results: null }),
        ),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(screen.getByText(/Backtest failed/i)).toBeInTheDocument());
    expect(screen.getByText(/Insufficient kline coverage/)).toBeInTheDocument();
  });

  it("shows the cancelled state for a cancelled run", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "cancelled", results: null })),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(screen.getByText(/was cancelled/i)).toBeInTheDocument());
  });

  it("renders a progressbar with aria-valuenow while running", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () =>
        HttpResponse.json(run({ status: "running", progress_pct: 37, results: null })),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "37");
  });

  it("warns when the trade table is showing a truncated subset", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({
          trades: [
            {
              id: 1,
              symbol: "BTCUSDT",
              side: "buy",
              entry_price: 1,
              exit_price: 2,
              qty: 1,
              leverage: 1,
              entry_time: "2026-01-01T00:00:00Z",
              exit_time: "2026-01-01T01:00:00Z",
              pnl: 1,
              pnl_pct: 1,
              fees_paid: 0,
              close_reason: "take_profit",
              mfe_pct: 1,
              mae_pct: 0,
              signal_score: 50,
              signal_confidence: "high",
              scan_id: "s1",
            },
          ],
          total: 5000,
          page: 1,
        }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    // Switch to the Trades tab (lazy fetch).
    fireEvent.click(await screen.findByRole("tab", { name: /trades/i }));
    await waitFor(() => expect(screen.getByText(/Showing first 1 of 5,000 trades/i)).toBeInTheDocument());
  });

  it("does NOT toast when opening an already-completed run (no active→terminal transition)", async () => {
    server.use(
      http.get("/api/v1/backtest/run-123", () => HttpResponse.json(run())),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(screen.getByTestId("hero-metrics")).toBeInTheDocument());
    // Mounting on a finished run must be silent — the toast is for landings only.
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("toasts once when a watched run transitions running → completed", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/backtest/run-123", () => {
        calls += 1;
        // First poll: running. Subsequent polls: completed.
        return HttpResponse.json(calls < 2 ? run({ status: "running", results: null }) : run());
      }),
      http.get("/api/v1/backtest/run-123/trades", () =>
        HttpResponse.json({ trades: [], total: 0, page: 1 }),
      ),
    );
    renderWithClient(<BacktestResultsPage runId="run-123" />);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Backtest completed"), {
      timeout: 4000,
    });
    expect(toastSuccess).toHaveBeenCalledTimes(1);
  });
});
