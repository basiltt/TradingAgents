import { describe, it, expect, vi } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { TradeListTable } from "../TradeListTable";
import type { BacktestTrade } from "../types";

function trade(overrides: Partial<BacktestTrade> = {}): BacktestTrade {
  return {
    id: 1,
    symbol: "BTCUSDT",
    side: "buy",
    entry_price: 100,
    exit_price: 110,
    qty: 1,
    leverage: 5,
    entry_time: "2026-01-01T00:00:00Z",
    exit_time: "2026-01-01T04:00:00Z",
    pnl: 50,
    pnl_pct: 5,
    fees_paid: 1,
    close_reason: "take_profit",
    mfe_pct: 6,
    mae_pct: -1,
    signal_score: 80,
    signal_confidence: "high",
    scan_id: "scan-1",
    ...overrides,
  };
}

const sample = [
  trade({ id: 1, symbol: "BTCUSDT", side: "buy", pnl: 50, close_reason: "take_profit" }),
  trade({ id: 2, symbol: "ETHUSDT", side: "sell", pnl: -30, close_reason: "stop_loss" }),
  trade({ id: 3, symbol: "SOLUSDT", side: "buy", pnl: 20, close_reason: "max_duration" }),
];

describe("TradeListTable", () => {
  it("renders one row per trade with symbol + pnl", () => {
    render(<TradeListTable trades={sample} />);
    const table = screen.getByTestId("trade-table");
    expect(within(table).getByText("BTCUSDT")).toBeInTheDocument();
    expect(within(table).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(table).getByText("SOLUSDT")).toBeInTheDocument();
    // 3 data rows
    expect(table.querySelectorAll("tbody tr").length).toBe(3);
    // PnL column (5th cell, index 4) for the ETH row shows the loss.
    const ethRow = within(table).getByText("ETHUSDT").closest("tr") as HTMLElement;
    expect(ethRow.querySelectorAll("td")[4].textContent).toBe("-$30.00");
  });

  it("shows running cumulative PnL column in chronological order", () => {
    render(<TradeListTable trades={sample} />);
    const table = screen.getByTestId("trade-table");
    // Cumulative is the 7th cell (index 6). Chronological order = input order here
    // (entry_time identical), so cum = 50, 20, 40.
    const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLElement[];
    const cumCells = rows.map((r) => r.querySelectorAll("td")[6].textContent);
    expect(cumCells).toEqual(["+$50.00", "+$20.00", "+$40.00"]);
  });

  it("filters by outcome", () => {
    render(<TradeListTable trades={sample} />);
    fireEvent.change(screen.getByLabelText("Filter by outcome"), { target: { value: "loss" } });
    const table = screen.getByTestId("trade-table");
    expect(within(table).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(table).queryByText("BTCUSDT")).not.toBeInTheDocument();
  });

  it("filters by symbol search", () => {
    render(<TradeListTable trades={sample} />);
    fireEvent.change(screen.getByLabelText("Search symbol"), { target: { value: "sol" } });
    const table = screen.getByTestId("trade-table");
    expect(within(table).getByText("SOLUSDT")).toBeInTheDocument();
    expect(within(table).queryByText("BTCUSDT")).not.toBeInTheDocument();
  });

  it("sorts by PnL when the PnL header is clicked", () => {
    render(<TradeListTable trades={sample} />);
    fireEvent.click(screen.getByLabelText("Sort by PnL"));
    const rows = screen.getByTestId("trade-table").querySelectorAll("tbody tr");
    // First click → desc → highest pnl first (BTC 50)
    expect(within(rows[0] as HTMLElement).getByText("BTCUSDT")).toBeInTheDocument();
  });

  it("computes cumulative PnL in chronological order even when displayed sorted", () => {
    // Chronological by entry_time: A(+100)→cum100, B(-40)→cum60, C(+30)→cum90.
    const chrono = [
      trade({ id: 1, symbol: "AAA", pnl: 100, entry_time: "2026-01-01T00:00:00Z" }),
      trade({ id: 2, symbol: "BBB", pnl: -40, entry_time: "2026-01-01T01:00:00Z" }),
      trade({ id: 3, symbol: "CCC", pnl: 30, entry_time: "2026-01-01T02:00:00Z" }),
    ];
    render(<TradeListTable trades={chrono} />);
    const table = screen.getByTestId("trade-table");
    // Sort by PnL desc → display order A(100), C(30), B(-40)…
    fireEvent.click(screen.getByLabelText("Sort by PnL"));
    const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLElement[];
    const bySymbol = (s: string) => rows.find((r) => r.textContent?.includes(s))!;
    // …but cumulative stays the CHRONOLOGICAL running total, not re-accumulated by display order.
    expect(bySymbol("AAA").querySelectorAll("td")[6].textContent).toBe("+$100.00");
    expect(bySymbol("BBB").querySelectorAll("td")[6].textContent).toBe("+$60.00");
    expect(bySymbol("CCC").querySelectorAll("td")[6].textContent).toBe("+$90.00");
  });

  it("exports only the filtered subset as CSV", () => {
    const onExport = vi.fn();
    render(<TradeListTable trades={sample} onExport={onExport} />);
    // Filter to losers only (ETH), then export.
    fireEvent.change(screen.getByLabelText("Filter by outcome"), { target: { value: "loss" } });
    fireEvent.click(screen.getByText("Export CSV"));
    const csv = onExport.mock.calls[0][0] as string;
    expect(csv).toContain("ETHUSDT");
    expect(csv).not.toContain("BTCUSDT");
    expect(csv).not.toContain("SOLUSDT");
  });

  it("toggles sort direction on repeated header clicks", () => {
    render(<TradeListTable trades={sample} />);
    const pnlHeader = screen.getByLabelText("Sort by PnL");
    fireEvent.click(pnlHeader); // desc
    let rows = screen.getByTestId("trade-table").querySelectorAll("tbody tr");
    expect(within(rows[0] as HTMLElement).getByText("BTCUSDT")).toBeInTheDocument(); // 50 highest
    fireEvent.click(pnlHeader); // asc
    rows = screen.getByTestId("trade-table").querySelectorAll("tbody tr");
    expect(within(rows[0] as HTMLElement).getByText("ETHUSDT")).toBeInTheDocument(); // -30 lowest
  });

  it("labels the export as partial when totalCount exceeds the loaded rows", () => {
    render(<TradeListTable trades={sample} totalCount={5000} onExport={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Export CSV \(partial\)/i })).toBeInTheDocument();
  });

  it("labels the export plainly when all trades are loaded", () => {
    render(<TradeListTable trades={sample} totalCount={sample.length} onExport={vi.fn()} />);
    expect(screen.getByRole("button", { name: /^Export CSV$/i })).toBeInTheDocument();
  });

  it("shows empty state when filters match nothing", () => {
    render(<TradeListTable trades={sample} />);
    fireEvent.change(screen.getByLabelText("Search symbol"), { target: { value: "zzz" } });
    expect(screen.getByText(/No trades match/i)).toBeInTheDocument();
  });

  it("paginates when more than one page of trades", () => {
    const many = Array.from({ length: 30 }, (_, i) =>
      trade({ id: i + 1, symbol: `SYM${i}`, entry_time: `2026-01-01T${String(i % 24).padStart(2, "0")}:00:00Z` }),
    );
    render(<TradeListTable trades={many} />);
    expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();
    const rowsP1 = screen.getByTestId("trade-table").querySelectorAll("tbody tr");
    expect(rowsP1.length).toBe(25);
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText(/Page 2 of 2/i)).toBeInTheDocument();
  });
});
