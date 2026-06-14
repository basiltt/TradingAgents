import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { SignalsTab } from "../tabs/SignalsTab";
import { signalAnalyticsApi } from "@/api/client";

vi.mock("@/api/client", async (orig) => {
  const mod = (await orig()) as Record<string, unknown>;
  return {
    ...mod,
    signalAnalyticsApi: { summary: vi.fn(), winRate: vi.fn() },
  };
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("SignalsTab", () => {
  it("shows the honest empty state when there are no linked signals", async () => {
    (signalAnalyticsApi.summary as ReturnType<typeof vi.fn>).mockResolvedValue({
      total_trades: 0, win_rate: 0, avg_pnl_pct: 0, total_pnl: 0,
      avg_hold_minutes: 0, current_streak: 0, active_alerts: 0,
    });
    (signalAnalyticsApi.winRate as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    wrap(<SignalsTab scope="all" />);
    await waitFor(() => expect(screen.getByText(/scanner signals/i)).toBeInTheDocument());
  });

  it("renders the rolling win-rate view when signals exist", async () => {
    (signalAnalyticsApi.summary as ReturnType<typeof vi.fn>).mockResolvedValue({
      total_trades: 25, win_rate: 0.6, avg_pnl_pct: 1.2, total_pnl: 30,
      avg_hold_minutes: 90, current_streak: 3, active_alerts: 0,
    });
    (signalAnalyticsApi.winRate as ReturnType<typeof vi.fn>).mockResolvedValue([
      { date: "2026-05-01", win_rate: 0.5, trade_number: 1 },
      { date: "2026-05-02", win_rate: 0.6, trade_number: 2 },
    ]);
    wrap(<SignalsTab scope="all" />);
    await waitFor(() => expect(screen.getByText(/rolling win rate/i)).toBeInTheDocument());
  });
});
