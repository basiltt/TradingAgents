import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BacktestConfigForm } from "../BacktestConfigForm";

describe("BacktestConfigForm", () => {
  it("renders the major sections", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    expect(screen.getByText("Capital & Time Range")).toBeInTheDocument();
    expect(screen.getByText("Signal Source")).toBeInTheDocument();
    expect(screen.getByText("Execution Model")).toBeInTheDocument();
    expect(screen.getByText("Trade Decisions")).toBeInTheDocument();
  });

  it("submits a valid config as an API request body", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.starting_capital).toBe(10000);
    expect(req.simulation_interval).toBe("1h");
    // dates normalized to ISO Z
    expect(req.date_range_start).toMatch(/Z$/);
    expect(req.date_range_end).toMatch(/Z$/);
  });

  it("seeds values from the seed prop", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} seed={{ starting_capital: 25000, leverage: 5 }} />);
    expect((screen.getByLabelText("Starting Capital ($)") as HTMLInputElement).value).toBe("25000");
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("5");
  });

  it("blocks submit and shows error when end is before start", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    const start = screen.getByLabelText("Start") as HTMLInputElement;
    const end = screen.getByLabelText("End") as HTMLInputElement;
    fireEvent.change(start, { target: { value: "2026-02-01T00:00" } });
    fireEvent.change(end, { target: { value: "2026-01-01T00:00" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(screen.getByText(/End must be after start/i)).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("reveals the schedule picker when source mode is 'schedule'", () => {
    render(
      <BacktestConfigForm
        onSubmit={vi.fn()}
        schedules={[{ value: "sched-1", label: "Hourly Top Movers" }]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Source Mode"), { target: { value: "schedule" } });
    expect(screen.getByLabelText("Schedule")).toBeInTheDocument();
    expect(screen.getByText("Hourly Top Movers")).toBeInTheDocument();
  });

  it("disables the submit button while submitting", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} isSubmitting />);
    expect(screen.getByRole("button", { name: /running/i })).toBeDisabled();
  });

  it("submits null (not 0 or '') for a cleared nullable close-rule field", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    // Open the collapsed Close Rules section.
    fireEvent.click(screen.getByText("Close Rules"));
    const field = screen.getByLabelText("Trailing Profit (%)") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "15" } });
    fireEvent.change(field, { target: { value: "" } }); // clear it again
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].trailing_profit_pct).toBeNull();
  });

  it("shows a schedule-required error when schedule mode has no schedule", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} schedules={[{ value: "s1", label: "S1" }]} />);
    fireEvent.change(screen.getByLabelText("Source Mode"), { target: { value: "schedule" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(screen.getByText(/Select a schedule/i)).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("auto-opens a collapsed section that contains a validation error", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    // Close Rules starts collapsed; put an out-of-range value in it, then submit.
    fireEvent.click(screen.getByText("Close Rules")); // open
    const dd = screen.getByLabelText("Max Drawdown (%)") as HTMLInputElement;
    fireEvent.change(dd, { target: { value: "500" } }); // > max 100
    fireEvent.click(screen.getByText("Close Rules")); // collapse again
    expect(screen.queryByLabelText("Max Drawdown (%)")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    // The section should auto-reveal so the error is visible.
    await waitFor(() => expect(screen.getByLabelText("Max Drawdown (%)")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not offer the unsupported 'Explicit scan IDs' source mode", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    const modeSelect = screen.getByLabelText("Source Mode") as HTMLSelectElement;
    const values = Array.from(modeSelect.options).map((o) => o.value);
    expect(values).toEqual(["date_range", "schedule"]);
  });

  it("parses a comma-separated symbol blacklist into an uppercased array", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    fireEvent.click(screen.getByText("Symbol Filters")); // expand section
    const field = screen.getByLabelText("Blacklist (never these)") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "btcusdt, eth usdt , solusdt" } });
    fireEvent.blur(field);
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].symbol_blacklist).toEqual([
      "BTCUSDT",
      "ETH",
      "USDT",
      "SOLUSDT",
    ]);
  });

  it("deduplicates and uppercases symbols in the blacklist", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    fireEvent.click(screen.getByText("Symbol Filters"));
    const field = screen.getByLabelText("Blacklist (never these)") as HTMLInputElement;
    // Duplicates (case-insensitive) must collapse so the 200-cap counts uniques.
    fireEvent.change(field, { target: { value: "BTC, btc, ETH, eth, BTC" } });
    fireEvent.blur(field);
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].symbol_blacklist).toEqual(["BTC", "ETH"]);
  });

  it("exposes the adaptive-blacklist and target-goal config sections", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    expect(screen.getByText("Adaptive Blacklist")).toBeInTheDocument();
    expect(screen.getByText("Target Goal")).toBeInTheDocument();
    // Expand adaptive section and confirm its fields exist.
    fireEvent.click(screen.getByText("Adaptive Blacklist"));
    expect(screen.getByLabelText("Min Trades")).toBeInTheDocument();
    expect(screen.getByLabelText("Max Win Rate (%)")).toBeInTheDocument();
    expect(screen.getByLabelText("Lookback (h)")).toBeInTheDocument();
  });
});
