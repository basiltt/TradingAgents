import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { TradesTab } from "../tabs/TradesTab";
import { performanceApi } from "@/api/client";

vi.mock("@/api/client", async (orig) => {
  const mod = (await orig()) as Record<string, unknown>;
  return {
    ...mod,
    performanceApi: { getTradesBreakdown: vi.fn(), getTradesPage: vi.fn() },
  };
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const breakdown = {
  by_symbol: [{ symbol: "BTCUSDT", trades: 5, count: 5, pnl: 7.2, win_rate: 60 }],
  by_strategy: [{ strategy: "trend", trades: 11, count: 11, pnl: 9.8, win_rate: 63.6 }],
  by_close_reason: [{ reason: "take_profit", count: 8, pnl: 18.4 }],
  pnl_distribution: [{ bucket: "0 to 2%", count: 4 }],
  hold_time_buckets: [{ bucket: "<1h", count: 3, win_rate: 66.7 }],
  meta: { strategy_legacy_approximate: true },
};
const page = {
  rows: [{ id: "t1", symbol: "BTCUSDT", side: "Buy", net_pnl: 3.1, net_pnl_pct: 1.6,
           close_reason: "take_profit", opened_at: null, closed_at: null, hold_hours: 6.2 }],
  cursor: null, has_more: false,
};

describe("TradesTab", () => {
  it("renders the per-symbol leaderboard from breakdown data", async () => {
    (performanceApi.getTradesBreakdown as ReturnType<typeof vi.fn>).mockResolvedValue(breakdown);
    (performanceApi.getTradesPage as ReturnType<typeof vi.fn>).mockResolvedValue(page);
    wrap(<TradesTab scope="all" timeframe="ALL" />);
    await waitFor(() => expect(screen.getAllByText(/BTCUSDT/).length).toBeGreaterThan(0));
  });

  it("shows the legacy-strategy hint when meta flag is set", async () => {
    (performanceApi.getTradesBreakdown as ReturnType<typeof vi.fn>).mockResolvedValue(breakdown);
    (performanceApi.getTradesPage as ReturnType<typeof vi.fn>).mockResolvedValue(page);
    wrap(<TradesTab scope="all" timeframe="ALL" />);
    await waitFor(() => expect(screen.getByText(/legacy/i)).toBeInTheDocument());
  });
});
