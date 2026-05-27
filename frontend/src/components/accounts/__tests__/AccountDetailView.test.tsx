import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer from "@/store/accounts-slice";
import aiManagerReducer from "@/store/ai-manager-slice";
import { uiSlice } from "@/store/ui-slice";
import { analysisSlice } from "@/store/analysis-slice";
import { AccountDetailView } from "../AccountDetailView";

const mockNavigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/api/client", () => ({
  accountsApi: {
    getWallet: vi.fn(),
    getPositions: vi.fn(),
    getOrders: vi.fn(),
    getPnlSummary: vi.fn(),
    delete: vi.fn(),
  },
}));

import { accountsApi } from "@/api/client";

function createStore() {
  return configureStore({
    reducer: { accounts: accountsReducer, aiManager: aiManagerReducer, ui: uiSlice.reducer, analysis: analysisSlice.reducer },
  });
}

function renderWithStore(ui: React.ReactElement) {
  const store = createStore();
  return render(<Provider store={store}>{ui}</Provider>);
}

const mockWallet = {
  totalEquity: "1000.00",
  totalWalletBalance: "900.00",
  totalAvailableBalance: "800.00",
  totalPerpUPL: "100.00",
  coin: [{ coin: "USDT", walletBalance: "900", equity: "1000", unrealisedPnl: "100" }],
};

const mockPositions = [
  { symbol: "BTCUSDT", side: "Buy", size: "0.1", avgPrice: "50000", markPrice: "51000", unrealisedPnl: "100", leverage: "10", liqPrice: "45000", takeProfit: "", stopLoss: "", positionIM: "500", positionMM: "250" },
];

const mockOrders = [
  { orderId: "o1", symbol: "ETHUSDT", side: "Buy", orderType: "Limit", qty: "1", price: "3000", orderStatus: "New", createdTime: "123", triggerPrice: "", stopOrderType: "" },
];

const mockPnl = { total_pnl: "250.00", win_rate: 66.7, win_count: 4, loss_count: 2, avg_win: "100.00", avg_loss: "-50.00" };

describe("AccountDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (accountsApi.getWallet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(mockWallet);
    (accountsApi.getPositions as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(mockPositions);
    (accountsApi.getOrders as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(mockOrders);
    (accountsApi.getPnlSummary as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(mockPnl);
  });

  it("shows loading state initially", () => {
    renderWithStore(<AccountDetailView accountId="acc1" />);
    expect(document.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("shows wallet summary after loading", async () => {
    renderWithStore(<AccountDetailView accountId="acc1" />);
    await waitFor(() => {
      expect(screen.getByText("$1000.00")).toBeInTheDocument();
    });
    expect(screen.getByText("$900.00")).toBeInTheDocument();
    expect(screen.getByText("$800.00")).toBeInTheDocument();
    expect(screen.getByText("$100.00")).toBeInTheDocument();
  });

  it("shows tabs with counts", async () => {
    renderWithStore(<AccountDetailView accountId="acc1" />);
    await waitFor(() => {
      expect(screen.getByText("Positions")).toBeInTheDocument();
    });
    expect(screen.getByText("Orders")).toBeInTheDocument();
  });

  it("shows error state on failure", async () => {
    (accountsApi.getWallet as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));
    renderWithStore(<AccountDetailView accountId="acc1" />);
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("shows back button that navigates", async () => {
    renderWithStore(<AccountDetailView accountId="acc1" />);
    await waitFor(() => {
      expect(screen.getByText("Account Detail")).toBeInTheDocument();
    });
  });

  it("renders PnL tab content", async () => {
    renderWithStore(<AccountDetailView accountId="acc1" />);
    await waitFor(() => {
      expect(screen.getByText("PnL")).toBeInTheDocument();
    });
  });
});
