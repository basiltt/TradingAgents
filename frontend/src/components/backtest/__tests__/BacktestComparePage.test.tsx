import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { BacktestComparePage, bestRunIndex } from "../BacktestComparePage";
import type { BacktestMetrics, BacktestRun } from "../types";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function run(id: string, netProfit: number, maxDd: number): BacktestRun {
  return {
    id,
    status: "completed",
    config: {},
    scan_source: {},
    progress_pct: 100,
    error_message: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    results: {
      metrics: {
        net_profit: netProfit,
        net_profit_pct: netProfit / 100,
        max_dd_pct: maxDd,
        win_rate: 55,
        total_trades: 10,
      } as unknown as BacktestMetrics,
      equity_curve: [],
      summary: {},
      warnings: [],
    },
  };
}

describe("bestRunIndex", () => {
  const runs = [run("a", 100, 10), run("b", 300, 5), run("c", 200, 8)];
  it("picks the highest for 'high' metrics", () => {
    expect(bestRunIndex(runs, (r) => r.results!.metrics.net_profit, "high")).toBe(1);
  });
  it("picks the lowest for 'low' metrics", () => {
    expect(bestRunIndex(runs, (r) => r.results!.metrics.max_dd_pct, "low")).toBe(1);
  });
  it("returns -1 when no comparator", () => {
    expect(bestRunIndex(runs, undefined, undefined)).toBe(-1);
  });
  it("returns -1 when every value is null", () => {
    expect(bestRunIndex(runs, () => null, "high")).toBe(-1);
  });
  it("keeps the first run on a tie", () => {
    const tied = [run("a", 100, 5), run("b", 100, 5)];
    expect(bestRunIndex(tied, (r) => r.results!.metrics.net_profit, "high")).toBe(0);
  });
  it("skips non-finite values (e.g. Infinity)", () => {
    const withInf = [run("a", 100, 5), run("b", 200, 5)];
    // Force an Infinity into run a's accessor; finite run b should win.
    expect(
      bestRunIndex(withInf, (r) => (r.id === "a" ? Infinity : r.results!.metrics.net_profit), "high"),
    ).toBe(1);
  });
});

describe("BacktestComparePage", () => {
  it("renders a column per run and a row per metric", async () => {
    server.use(
      http.get("/api/v1/backtest/compare", () =>
        HttpResponse.json({ runs: [run("run-1", 100, 10), run("run-2", 300, 5)] }),
      ),
    );
    renderWithClient(<BacktestComparePage runIds={["run-1", "run-2"]} />);
    await waitFor(() => expect(screen.getByTestId("compare-table")).toBeInTheDocument());
    expect(screen.getByText("Run 1")).toBeInTheDocument();
    expect(screen.getByText("Run 2")).toBeInTheDocument();
    expect(screen.getByText("Net Profit")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
  });

  it("marks the best run per metric with a star", async () => {
    server.use(
      http.get("/api/v1/backtest/compare", () =>
        HttpResponse.json({ runs: [run("run-1", 100, 10), run("run-2", 300, 5)] }),
      ),
    );
    renderWithClient(<BacktestComparePage runIds={["run-1", "run-2"]} />);
    await waitFor(() => expect(screen.getByTestId("compare-table")).toBeInTheDocument());
    // run-2 wins Net Profit (300>100) AND Max Drawdown (5<10, "low" path).
    // Net Profit row: run-2 cell is best, run-1 is not.
    const netRow = screen.getByText("Net Profit").closest("tr") as HTMLElement;
    const netCells = netRow.querySelectorAll("td");
    expect(netCells[0].getAttribute("data-best")).toBeNull(); // run-1
    expect(netCells[1].getAttribute("data-best")).toBe("true"); // run-2
    // Max Drawdown (lower is better): run-2 best.
    const ddRow = screen.getByText("Max Drawdown").closest("tr") as HTMLElement;
    const ddCells = ddRow.querySelectorAll("td");
    expect(ddCells[1].getAttribute("data-best")).toBe("true");
    // SR-only "(best)" label present.
    expect(screen.getAllByText(/\(best\)/).length).toBeGreaterThan(0);
  });

  it("prompts when fewer than two runs", () => {
    renderWithClient(<BacktestComparePage runIds={["only-one"]} />);
    expect(screen.getByText(/at least two runs/i)).toBeInTheDocument();
  });

  it("overlays equity curves when runs carry equity data", async () => {
    const withEquity = (id: string, np: number): BacktestRun => ({
      ...run(id, np, 5),
      results: {
        metrics: run(id, np, 5).results!.metrics,
        equity_curve: [
          { ts: "2026-01-01T00:00:00Z", equity: 10000 },
          { ts: "2026-01-02T00:00:00Z", equity: 10000 + np },
        ],
        summary: {},
        warnings: [],
      },
    });
    server.use(
      http.get("/api/v1/backtest/compare", () =>
        HttpResponse.json({ runs: [withEquity("run-1", 100), withEquity("run-2", 300)] }),
      ),
    );
    renderWithClient(<BacktestComparePage runIds={["run-1", "run-2"]} />);
    expect(await screen.findByTestId("equity-overlay-chart")).toBeInTheDocument();
  });
});
