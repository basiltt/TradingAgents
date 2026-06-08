import { describe, it, expect, beforeAll, beforeEach, afterAll, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { BacktestNewForm } from "../BacktestNewForm";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  // The form persists a draft to localStorage; isolate per-test.
  localStorage.clear();
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("BacktestNewForm", () => {
  it("fetches schedules and offers them in the schedule picker", async () => {
    server.use(
      http.get("/api/v1/scheduled-scans", () =>
        HttpResponse.json({
          schedules: [
            { id: "sched-1", name: "Hourly Top Movers", schedule_type: "interval", schedule_config: {}, scan_config: {}, status: "active", timezone: "UTC", next_run_at: null, last_run_at: null, last_scan_id: null, consecutive_failures: 0, is_running: false },
          ],
        }),
      ),
    );
    renderWithClient(<BacktestNewForm onCreated={vi.fn()} />);
    // Switch to schedule mode — the fetched schedule should be selectable.
    fireEvent.change(await screen.findByLabelText("Source Mode"), { target: { value: "schedule" } });
    await waitFor(() => expect(screen.getByText("Hourly Top Movers")).toBeInTheDocument());
  });

  it("shows guidance when schedule mode is chosen but no schedules exist", async () => {
    server.use(
      http.get("/api/v1/scheduled-scans", () => HttpResponse.json({ schedules: [] })),
    );
    renderWithClient(<BacktestNewForm onCreated={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Source Mode"), { target: { value: "schedule" } });
    expect(await screen.findByText(/No schedules available/i)).toBeInTheDocument();
  });

  it("creates a backtest and calls onCreated with the run id", async () => {
    const onCreated = vi.fn();
    server.use(
      http.get("/api/v1/scheduled-scans", () => HttpResponse.json({ schedules: [] })),
      http.post("/api/v1/backtest", () => HttpResponse.json({ run_id: "run-xyz" }, { status: 201 })),
    );
    renderWithClient(<BacktestNewForm onCreated={onCreated} />);
    fireEvent.click(await screen.findByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("run-xyz"));
  });

  it("submits a schedule-mode request body with the selected schedule_id", async () => {
    let body: Record<string, unknown> | undefined;
    server.use(
      http.get("/api/v1/scheduled-scans", () =>
        HttpResponse.json({
          schedules: [
            { id: "sched-1", name: "Hourly", schedule_type: "interval", schedule_config: {}, scan_config: {}, status: "active", timezone: "UTC", next_run_at: null, last_run_at: null, last_scan_id: null, consecutive_failures: 0, is_running: false },
          ],
        }),
      ),
      http.post("/api/v1/backtest", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ run_id: "run-s" }, { status: 201 });
      }),
    );
    renderWithClient(<BacktestNewForm onCreated={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Source Mode"), { target: { value: "schedule" } });
    await waitFor(() => expect(screen.getByText("Hourly")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Schedule"), { target: { value: "sched-1" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(body).toBeDefined());
    expect(body?.scan_source).toEqual({ mode: "schedule", schedule_id: "sched-1" });
  });
});
