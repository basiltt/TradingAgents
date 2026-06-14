import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PerformanceDashboard } from "../PerformanceDashboard";
import { performanceApi } from "@/api/client";

vi.mock("@/api/client", async (orig) => {
  const mod = (await orig()) as Record<string, unknown>;
  return {
    ...mod,
    performanceApi: { getOverview: vi.fn() },
    accountsApi: { ...(mod.accountsApi as object), list: vi.fn().mockResolvedValue([]) },
  };
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const emptyOverview = {
  kpis: { net_pnl: 0, realized_pnl_gross: 0, win_count: 0, loss_count: 0,
          max_consecutive_wins: 0, max_consecutive_losses: 0, total_trades: 0,
          total_equity: null, unrealized_pnl: null, open_count: null,
          total_return_pct: null, win_rate: null, profit_factor: null, expectancy: null,
          avg_win: null, avg_loss: null, avg_win_loss_ratio: null, best_trade: null,
          worst_trade: null, avg_hold_time_hours: null, max_drawdown_pct: null,
          max_drawdown_abs: null, drawdown_duration_days: null, drawdown_recovered: null,
          sharpe_ratio: null, sortino_ratio: null, calmar_ratio: null },
  kpis_prev: null, equity_curve: [], equity_now: null, drawdown_series: [],
  daily_pnl: [], monthly_pnl: [],
  meta: { currency: "USDT", grouping_tz: "UTC", trading_days: 0, starting_equity: null,
          return_basis: "recorded_history", live_equity_available: false,
          live_sourced: [], degraded: true },
};

describe("PerformanceDashboard", () => {
  it("renders the empty state when there are no closed trades", async () => {
    (performanceApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue(emptyOverview);
    wrap(<PerformanceDashboard />);
    await waitFor(() => expect(document.body.textContent).toMatch(/no closed trades/i));
  });

  it("embedded mode hides the scope selector and scopes to the account", async () => {
    (performanceApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue(emptyOverview);
    wrap(<PerformanceDashboard embedded accountId="acc_1" />);
    await waitFor(() => {
      expect(performanceApi.getOverview).toHaveBeenCalledWith("acc_1", expect.any(String), expect.anything());
    });
    expect(screen.queryByLabelText(/Performance scope/i)).toBeNull();
  });
});
