import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { LiveTab } from "../tabs/LiveTab";
import { performanceApi } from "@/api/client";

vi.mock("@/api/client", async (orig) => {
  const mod = (await orig()) as Record<string, unknown>;
  return { ...mod, performanceApi: { getLive: vi.fn() } };
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("LiveTab", () => {
  it("renders positions + tiles + sector bars", async () => {
    (performanceApi.getLive as ReturnType<typeof vi.fn>).mockResolvedValue({
      positions: [{ account_id: "a1", symbol: "ETHUSDT", side: "Buy", size: 0.1,
                    leverage: 20, entry: 2950, unrealized_pnl: -1.6, unrealized_pnl_pct: -2.7 }],
      account_tiles: [{ account_id: "a1", label: "Main", type: "live", equity: 120,
                        today_pnl: 1.2, positions_count: 1, error: null }],
      sector_concentration: [{ sector: "L1", exposure_pct: 45, positions: 2 }],
      degraded: false,
    });
    wrap(<LiveTab scope="all" />);
    await waitFor(() => expect(screen.getByText(/ETHUSDT/)).toBeInTheDocument());
    expect(screen.getByText(/L1/)).toBeInTheDocument();
  });

  it("shows a degraded banner + per-account error", async () => {
    (performanceApi.getLive as ReturnType<typeof vi.fn>).mockResolvedValue({
      positions: [],
      account_tiles: [{ account_id: "a2", label: "Bad", type: "demo", equity: null,
                        today_pnl: null, positions_count: 0, error: "bybit down" }],
      sector_concentration: [],
      degraded: true,
    });
    wrap(<LiveTab scope="all" />);
    await waitFor(() => expect(screen.getByText(/some accounts could not be loaded/i)).toBeInTheDocument());
    expect(screen.getByText(/bybit down/i)).toBeInTheDocument();
  });
});
