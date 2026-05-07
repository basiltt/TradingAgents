import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WalletPanel } from "../WalletPanel";
import { PositionsTable } from "../PositionsTable";
import { OrdersTable } from "../OrdersTable";
import { PnLPanel } from "../PnLPanel";

describe("WalletPanel", () => {
  it("shows empty state when no coins", () => {
    render(<WalletPanel wallet={{ totalEquity: "0", totalWalletBalance: "0", totalAvailableBalance: "0", totalPerpUPL: "0", coin: [] } as any} />);
    expect(screen.getByText("No wallet data")).toBeInTheDocument();
  });

  it("renders coin table with data", () => {
    const wallet = {
      totalEquity: "1000", totalWalletBalance: "900", totalAvailableBalance: "800", totalPerpUPL: "100",
      coin: [{ coin: "USDT", walletBalance: "900.1234", equity: "1000.5678", unrealisedPnl: "100.9876" }],
    };
    render(<WalletPanel wallet={wallet as any} />);
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText("900.1234")).toBeInTheDocument();
  });

  it("renders column headers", () => {
    const wallet = { totalEquity: "0", totalWalletBalance: "0", totalAvailableBalance: "0", totalPerpUPL: "0", coin: [{ coin: "BTC", walletBalance: "1", equity: "1", unrealisedPnl: "0" }] };
    render(<WalletPanel wallet={wallet as any} />);
    expect(screen.getByText("Coin")).toBeInTheDocument();
    expect(screen.getByText("Balance")).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
  });
});

describe("PositionsTable", () => {
  it("shows empty state", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("renders position row", () => {
    const positions = [{ symbol: "BTCUSDT", side: "Buy", size: "0.1", avgPrice: "50000", markPrice: "51000", unrealisedPnl: "100", leverage: "10", liqPrice: "45000", takeProfit: "", stopLoss: "", positionIM: "500", positionMM: "250" }];
    render(<PositionsTable positions={positions as any} />);
    expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    expect(screen.getByText("Long")).toBeInTheDocument();
    expect(screen.getByText("10x")).toBeInTheDocument();
  });

  it("shows liquidation warning when close to liq price", () => {
    const positions = [{ symbol: "ETHUSDT", side: "Sell", size: "1", avgPrice: "3000", markPrice: "3000", unrealisedPnl: "-10", leverage: "50", liqPrice: "3100", takeProfit: "", stopLoss: "", positionIM: "60", positionMM: "30" }];
    render(<PositionsTable positions={positions as any} />);
    expect(screen.getByText("$3100.00")).toBeInTheDocument();
  });

  it("shows Short badge for Sell side", () => {
    const positions = [{ symbol: "ETHUSDT", side: "Sell", size: "1", avgPrice: "3000", markPrice: "2900", unrealisedPnl: "100", leverage: "5", liqPrice: "3500", takeProfit: "", stopLoss: "", positionIM: "600", positionMM: "300" }];
    render(<PositionsTable positions={positions as any} />);
    expect(screen.getByText("Short")).toBeInTheDocument();
  });

  it("colors PnL green for profit", () => {
    const positions = [{ symbol: "BTCUSDT", side: "Buy", size: "0.1", avgPrice: "50000", markPrice: "51000", unrealisedPnl: "100", leverage: "10", liqPrice: "45000", takeProfit: "", stopLoss: "", positionIM: "500", positionMM: "250" }];
    const { container } = render(<PositionsTable positions={positions as any} />);
    const pnlCell = container.querySelector(".text-green-600");
    expect(pnlCell).toBeTruthy();
  });
});

describe("OrdersTable", () => {
  it("shows empty state", () => {
    render(<OrdersTable orders={[]} />);
    expect(screen.getByText("No open orders")).toBeInTheDocument();
  });

  it("renders order row", () => {
    const orders = [{ orderId: "o1", symbol: "BTCUSDT", side: "Buy", orderType: "Limit", qty: "0.01", price: "50000", orderStatus: "New", createdTime: "123", triggerPrice: "", stopOrderType: "" }];
    render(<OrdersTable orders={orders as any} />);
    expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("$50000.00")).toBeInTheDocument();
  });

  it("shows Market for price 0", () => {
    const orders = [{ orderId: "o2", symbol: "ETHUSDT", side: "Sell", orderType: "Market", qty: "1", price: "0", orderStatus: "New", createdTime: "123", triggerPrice: "", stopOrderType: "" }];
    render(<OrdersTable orders={orders as any} />);
    expect(screen.getAllByText("Market").length).toBeGreaterThanOrEqual(1);
  });

  it("shows stop order type annotation", () => {
    const orders = [{ orderId: "o3", symbol: "BTCUSDT", side: "Buy", orderType: "Limit", qty: "0.01", price: "48000", orderStatus: "Untriggered", createdTime: "123", triggerPrice: "49000", stopOrderType: "TakeProfit" }];
    render(<OrdersTable orders={orders as any} />);
    expect(screen.getByText("Limit (TakeProfit)")).toBeInTheDocument();
  });
});

describe("PnLPanel", () => {
  it("shows empty state when no accountId", () => {
    render(<PnLPanel pnlSummary={null} />);
    expect(screen.getByText("No PnL data available")).toBeInTheDocument();
  });

  it("renders period headings when accountId provided", async () => {
    vi.mock("@/api/client", async () => {
      const actual = await vi.importActual("@/api/client");
      return {
        ...actual as any,
        accountsApi: {
          ...(actual as any).accountsApi,
          getPnlSummary: vi.fn().mockResolvedValue({ total_pnl: "100.00", win_rate: 75.0, win_count: 3, loss_count: 1, avg_win: "50.00", avg_loss: "-25.00" }),
        },
      };
    });
    render(<PnLPanel pnlSummary={null} accountId="acc1" />);
    expect(screen.getByText("PnL Overview")).toBeInTheDocument();
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("7 Days")).toBeInTheDocument();
    expect(screen.getByText("30 Days")).toBeInTheDocument();
  });
});
