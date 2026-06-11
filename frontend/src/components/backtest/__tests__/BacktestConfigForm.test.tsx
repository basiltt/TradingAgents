import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BacktestConfigForm } from "../BacktestConfigForm";

describe("BacktestConfigForm", () => {
  // The form persists a draft to localStorage; isolate it so a draft from one
  // test cannot leak default-overriding values into the next (the env does not
  // reset storage between tests).
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders the major sections", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    expect(screen.getByText("Backtest Setup (backtest-only)")).toBeInTheDocument();
    expect(screen.getByText("Signal Source (backtest-only)")).toBeInTheDocument();
    expect(screen.getByText("Execution Model (backtest-only)")).toBeInTheDocument();
    expect(screen.getByText("Trade Decisions")).toBeInTheDocument();
  });

  it("submits a valid config as an API request body", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.starting_capital).toBe(10000);
    // Defaults mirror the backend / production AutoTradeConfig (5m, leverage 20, …).
    expect(req.simulation_interval).toBe("5m");
    expect(req.leverage).toBe(20);
    expect(req.execution_mode).toBe("immediate");
    // dates normalized to ISO Z
    expect(req.date_range_start).toMatch(/Z$/);
    expect(req.date_range_end).toMatch(/Z$/);
  });

  it("clearing a cost field restores its default, not zero (no silent zero-cost run)", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    // Clear the Fee Rate field — an empty value must NOT submit as 0 (which would be
    // zero-cost trading and inflate PnL), it must restore the production default.
    const fee = screen.getByLabelText(/Fee Rate/i) as HTMLInputElement;
    fireEvent.change(fee, { target: { value: "" } });
    const slip = screen.getByLabelText(/Slippage/i) as HTMLInputElement;
    fireEvent.change(slip, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.fee_rate_pct).toBe(0.055);  // default restored, NOT 0
    expect(req.slippage_bps).toBe(2);       // default restored, NOT 0
  });

  it("seeds values from the seed prop", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} seed={{ starting_capital: 25000, leverage: 5 }} />);
    expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("25000");
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
    await waitFor(() => expect(screen.getAllByText(/End must be after start/i).length).toBeGreaterThan(0));
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

  it("toggling a close-rule switch off submits null (not 0) for its field", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    // Open the collapsed Close Rules section.
    fireEvent.click(screen.getByText("Close Rules"));
    // The "Trailing profit stop" toggle seeds 2.0 when on, then null when off.
    const toggle = screen.getByText("Trailing profit stop");
    fireEvent.click(toggle); // on -> 2.0
    fireEvent.click(toggle); // off -> null
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].trailing_profit_pct).toBeNull();
  });

  it("shows a schedule-required error when schedule mode has no schedule", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} schedules={[{ value: "s1", label: "S1" }]} />);
    fireEvent.change(screen.getByLabelText("Source Mode"), { target: { value: "schedule" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() => expect(screen.getAllByText(/Select a schedule/i).length).toBeGreaterThan(0));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits specific schedule mode when inactive scan source fields are stale nulls", async () => {
    const onSubmit = vi.fn();
    render(
      <BacktestConfigForm
        onSubmit={onSubmit}
        schedules={[{ value: "sched-1", label: "Dad Demo schedule" }]}
        seed={{
          starting_capital: 234.02,
          date_range_start: "2026-06-05T00:00",
          date_range_end: "2026-06-11T00:00",
          scan_source: {
            mode: "schedule",
            schedule_id: "sched-1",
            scan_ids: null,
            replay_account_id: null,
          } as never,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Invalid input/i)).not.toBeInTheDocument();
    expect(onSubmit.mock.calls[0][0].scan_source).toEqual({
      mode: "schedule",
      schedule_id: "sched-1",
    });
  });

  it("applies the Dad Demo reference config with the stored schedule/date range", async () => {
    const referenceScheduleId = "d9c5f14f-a71f-4907-9449-dab3b75a52cb";
    const onSubmit = vi.fn();
    render(
      <BacktestConfigForm
        onSubmit={onSubmit}
        schedules={[
          { value: "sched-1", label: "Other Schedule" },
          { value: referenceScheduleId, label: "Every 2 Hour Scan" },
        ]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Source Mode"), { target: { value: "schedule" } });
    fireEvent.change(screen.getByLabelText("Schedule"), { target: { value: "sched-1" } });
    fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "99" } });

    fireEvent.click(screen.getByRole("button", { name: /reference config/i }));

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("234"),
    );
    expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe("2026-06-05T00:00");
    expect((screen.getByLabelText("End") as HTMLInputElement).value).toBe("2026-06-11T11:37");
    expect((screen.getByLabelText("Source Mode") as HTMLSelectElement).value).toBe("schedule");
    expect((screen.getByLabelText("Schedule") as HTMLSelectElement).value).toBe(referenceScheduleId);
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("8");
    expect((screen.getByLabelText("Capital %") as HTMLInputElement).value).toBe("22");
    expect((screen.getByLabelText("Max trades") as HTMLInputElement).value).toBe("3");
    expect((screen.getByLabelText("Execution mode") as HTMLSelectElement).value).toBe("batch");

    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.scan_source).toEqual({ mode: "schedule", schedule_id: referenceScheduleId });
    expect(req.date_range_start).toBe(new Date("2026-06-05T00:00").toISOString());
    expect(req.date_range_end).toBe(new Date("2026-06-11T11:37").toISOString());
    expect(req.starting_capital).toBe(234);
    expect(req.leverage).toBe(8);
    expect(req.capital_pct).toBe(22);
    expect(req.max_trades).toBe(3);
    expect(req.funding_rate_model).toBe("fixed_8h");
    expect(req.max_drawdown_pct).toBe(12);
    expect(req.breakeven_timeout_hours).toBe(12);
    expect(req.max_trade_duration_hours).toBe(24);
    expect(req.target_goal_type).toBe("profit_pct");
    expect(req.target_goal_value).toBe(15);
    expect(req.max_same_sector).toBe(4);
    expect(req.max_price_drift_pct).toBe(6);
    expect(req.symbol_blacklist).toBeNull();
    expect(req.adaptive_blacklist_enabled).toBe(false);
    expect("account_id" in req).toBe(false);
  });

  it("ignores a stale saved reference with blank date fields", async () => {
    const referenceScheduleId = "d9c5f14f-a71f-4907-9449-dab3b75a52cb";
    localStorage.setItem(
      "tradingagents_backtest_reference_config",
      JSON.stringify({
        starting_capital: 999,
        date_range_start: "",
        date_range_end: "",
        scan_source: { mode: "schedule", schedule_id: "sched-1" },
        leverage: 99,
      }),
    );

    render(
      <BacktestConfigForm
        onSubmit={vi.fn()}
        schedules={[
          { value: "sched-1", label: "Other Schedule" },
          { value: referenceScheduleId, label: "Every 2 Hour Scan" },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /reference config/i }));

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("234"),
    );
    expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe("2026-06-05T00:00");
    expect((screen.getByLabelText("End") as HTMLInputElement).value).toBe("2026-06-11T11:37");
    expect((screen.getByLabelText("Schedule") as HTMLSelectElement).value).toBe(referenceScheduleId);
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("8");
  });

  it("stores the current fill as the reusable reference config", async () => {
    const onSubmit = vi.fn();
    render(
      <BacktestConfigForm
        onSubmit={onSubmit}
        schedules={[{ value: "sched-1", label: "Every 2 Hour Scan" }]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Source Mode"), { target: { value: "schedule" } });
    fireEvent.change(screen.getByLabelText("Schedule"), { target: { value: "sched-1" } });
    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), { target: { value: "777" } });
    fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Capital %"), { target: { value: "33" } });
    fireEvent.change(screen.getByLabelText("Max trades"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Execution mode"), { target: { value: "batch" } });

    fireEvent.click(screen.getByRole("button", { name: /store reference/i }));

    expect(localStorage.getItem("tradingagents_backtest_reference_config") ?? "").toContain("777");

    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("Capital %"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Max trades"), { target: { value: "999" } });
    fireEvent.change(screen.getByLabelText("Execution mode"), { target: { value: "immediate" } });

    fireEvent.click(screen.getByRole("button", { name: /reference config/i }));

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("777"),
    );
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("12");
    expect((screen.getByLabelText("Capital %") as HTMLInputElement).value).toBe("33");
    expect((screen.getByLabelText("Max trades") as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("Execution mode") as HTMLSelectElement).value).toBe("batch");
    expect((screen.getByLabelText("Source Mode") as HTMLSelectElement).value).toBe("schedule");
    expect((screen.getByLabelText("Schedule") as HTMLSelectElement).value).toBe("sched-1");

    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.scan_source).toEqual({ mode: "schedule", schedule_id: "sched-1" });
    expect(req.starting_capital).toBe(777);
    expect(req.leverage).toBe(12);
    expect(req.capital_pct).toBe(33);
    expect(req.max_trades).toBe(4);
    expect(req.execution_mode).toBe("batch");
    expect("account_id" in req).toBe(false);
  });

  it("applies the optimized reference config as a separate preset", async () => {
    const referenceScheduleId = "d9c5f14f-a71f-4907-9449-dab3b75a52cb";
    const onSubmit = vi.fn();
    render(
      <BacktestConfigForm
        onSubmit={onSubmit}
        schedules={[{ value: referenceScheduleId, label: "Every 2 Hour Scan" }]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), { target: { value: "999" } });
    fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "99" } });

    fireEvent.click(screen.getByRole("button", { name: /optimized reference/i }));

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("234.02"),
    );
    expect((screen.getByLabelText("Source Mode") as HTMLSelectElement).value).toBe("schedule");
    expect((screen.getByLabelText("Schedule") as HTMLSelectElement).value).toBe(referenceScheduleId);
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("7");
    expect((screen.getByLabelText("Capital %") as HTMLInputElement).value).toBe("30");
    expect((screen.getByLabelText("Min score") as HTMLInputElement).value).toBe("9");
    expect((screen.getByLabelText("Min confidence") as HTMLSelectElement).value).toBe("low");
    expect((screen.getByLabelText("Max trades") as HTMLInputElement).value).toBe("6");

    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const req = onSubmit.mock.calls[0][0];
    expect(req.scan_source).toEqual({ mode: "schedule", schedule_id: referenceScheduleId });
    expect(req.starting_capital).toBe(234.02);
    expect(req.leverage).toBe(7);
    expect(req.capital_pct).toBe(30);
    expect(req.min_score).toBe(9);
    expect(req.confidence_filter).toBe("low");
    expect(req.max_trades).toBe(6);
    expect(req.max_signal_age_minutes).toBe(90);
    expect(req.max_price_drift_pct).toBe(5);
    expect(req.max_drawdown_pct).toBe(15);
    expect(req.breakeven_timeout_hours).toBeNull();
    expect(req.max_trade_duration_hours).toBe(12);
    expect(req.trailing_profit_pct).toBe(3);
    expect(req.target_goal_type).toBe("profit_pct");
    expect(req.target_goal_value).toBe(18);
    expect("account_id" in req).toBe(false);
  });

  it("reset clears edited values and prevents stale draft restore", async () => {
    const { unmount } = render(<BacktestConfigForm onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), { target: { value: "999" } });
    fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "88" } });

    await waitFor(() =>
      expect(localStorage.getItem("tradingagents_backtest_draft") ?? "").toContain("999"),
    );

    fireEvent.click(screen.getByRole("button", { name: /^reset$/i }));

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("10000"),
    );
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("20");
    expect(localStorage.getItem("tradingagents_backtest_draft") ?? "").not.toContain("999");
    expect(localStorage.getItem("tradingagents_backtest_draft") ?? "").not.toContain("88");

    unmount();
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("10000");
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("20");
  });

  it("auto-opens a collapsed section that contains a validation error", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);
    // Close Rules starts collapsed; put an out-of-range value in it, then submit.
    fireEvent.click(screen.getByText("Close Rules")); // open
    const dd = screen.getByLabelText("Max drawdown %") as HTMLInputElement;
    fireEvent.change(dd, { target: { value: "500" } }); // > max 100
    fireEvent.click(screen.getByText("Close Rules")); // collapse again
    expect(screen.queryByLabelText("Max drawdown %")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    // The section should auto-reveal so the error is visible.
    await waitFor(() => expect(screen.getByLabelText("Max drawdown %")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a visible summary and opens target goal when close-on-profit needs a goal value", async () => {
    const onSubmit = vi.fn();
    render(<BacktestConfigForm onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText("Close Rules"));
    fireEvent.click(screen.getByText("Close and re-trade on profit"));
    expect(screen.queryByLabelText("Goal Value")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() =>
      expect(screen.getByTestId("backtest-validation-summary")).toHaveTextContent(
        "Goal Value: Close on Profit requires a Goal Value",
      ),
    );
    expect(screen.getByLabelText("Goal Value")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("offers date_range, schedule, and replay source modes (not the unsupported 'explicit')", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    const modeSelect = screen.getByLabelText("Source Mode") as HTMLSelectElement;
    const values = Array.from(modeSelect.options).map((o) => o.value);
    expect(values).toEqual(["date_range", "schedule", "replay"]);
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

  it("exposes the advanced engine-level and target-goal config sections", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    expect(screen.getByText("Advanced (engine-level)")).toBeInTheDocument();
    expect(screen.getByText("Target Goal")).toBeInTheDocument();
    // Expand advanced section and confirm its fields exist.
    fireEvent.click(screen.getByText("Advanced (engine-level)"));
    expect(screen.getByLabelText("Min trades")).toBeInTheDocument();
    expect(screen.getByLabelText("Max win rate %")).toBeInTheDocument();
    expect(screen.getByLabelText("Lookback (hours)")).toBeInTheDocument();
  });

  it("exposes the regime section and shows the F2-long danger note when enabled", () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByText("Market Regime & Strategy (F1/F2/F3)"));
    // F3 cohort select is uniquely labeled; confirms the section rendered.
    expect(screen.getByLabelText("Strategy cohort (F3)")).toBeInTheDocument();
    // The negative-expectancy note appears only after enabling the long side. The
    // neu Checkbox duplicates its label text, so target the visible label directly.
    expect(screen.queryByTestId("mr-long-danger")).toBeNull();
    fireEvent.click(screen.getByText("MR long side (neg. expectancy)"));
    expect(screen.getByTestId("mr-long-danger")).toBeInTheDocument();
  });

  it("restores entered values after the form is remounted (draft persistence)", async () => {
    // Reproduces the bug: navigating away and back lost everything the user typed.
    const { unmount } = render(<BacktestConfigForm onSubmit={vi.fn()} />);
    const capital = screen.getByLabelText("Initial Balance ($)") as HTMLInputElement;
    fireEvent.change(capital, { target: { value: "73210" } });
    const leverage = screen.getByLabelText("Leverage") as HTMLInputElement;
    fireEvent.change(leverage, { target: { value: "11" } });

    // Simulate leaving the page and coming back (route unmounts the lazy form).
    unmount();
    render(<BacktestConfigForm onSubmit={vi.fn()} />);

    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("73210"),
    );
    expect((screen.getByLabelText("Leverage") as HTMLInputElement).value).toBe("11");
  });

  it("persists a select-field change across a remount", async () => {
    const { unmount } = render(<BacktestConfigForm onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Simulation Interval"), { target: { value: "1h" } });
    unmount();
    render(<BacktestConfigForm onSubmit={vi.fn()} />);
    await waitFor(() =>
      expect((screen.getByLabelText("Simulation Interval") as HTMLSelectElement).value).toBe("1h"),
    );
  });

  it("saves a complete draft snapshot, not only the field that changed", async () => {
    render(<BacktestConfigForm onSubmit={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), {
      target: { value: "12345" },
    });

    await waitFor(() => {
      const raw = localStorage.getItem("tradingagents_backtest_draft");
      expect(raw).not.toBeNull();
      const draft = JSON.parse(raw ?? "{}");
      expect(draft.starting_capital).toBe("12345");
      expect(draft.leverage).toBe(20);
      expect(draft.capital_pct).toBe(5);
      expect(draft.max_drawdown_pct).toBe(100);
      expect(draft.adaptive_blacklist_min_trades).toBe(5);
      expect(draft.mr_leverage).toBe(10);
      expect(draft.scan_source).toEqual({ mode: "date_range" });
    });
  });

  it("an explicit seed wins over a saved draft", async () => {
    // A user types a draft...
    const { unmount } = render(<BacktestConfigForm onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Initial Balance ($)"), { target: { value: "500" } });
    unmount();
    // ...but a "Backtest these settings"/Retry seed must take precedence over it.
    render(<BacktestConfigForm onSubmit={vi.fn()} seed={{ starting_capital: 25000 }} />);
    await waitFor(() =>
      expect((screen.getByLabelText("Initial Balance ($)") as HTMLInputElement).value).toBe("25000"),
    );
  });
});
