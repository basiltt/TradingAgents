import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { uiSlice } from "@/store/ui-slice";
import { analysisSlice } from "@/store/analysis-slice";
import { ConfigForm } from "../ConfigForm";

const mockNavigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mockNavigate,
}));

const mockStartAnalysis = vi.fn();
vi.mock("@/api/client", () => ({
  apiClient: {
    startAnalysis: (...args: unknown[]) => mockStartAnalysis(...args),
    getConfig: () => Promise.resolve({ defaults: {}, overrides: {}, resolved: {} }),
  },
}));

vi.mock("@/hooks/useModels", () => ({
  useModels: () => ({ data: null, isLoading: false, isError: false }),
}));

vi.mock("@/hooks/useConnectivityCheck", () => ({
  useConnectivityCheck: () => ({ status: "idle", latency: null, error: null }),
}));

function createWrapper() {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </Provider>
    );
  };
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, ticker: string, date = "2025-06-01") {
  await user.type(screen.getByLabelText(/ticker|trading pair/i), ticker);
  fireEvent.change(screen.getByLabelText(/date/i), { target: { value: date } });
  await user.click(screen.getByRole("button", { name: /start analysis/i }));
}

describe("ConfigForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders ticker and date fields", () => {
    render(<ConfigForm />, { wrapper: createWrapper() });
    expect(screen.getByLabelText(/ticker/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/date/i)).toBeInTheDocument();
  });

  it("renders asset type toggle", () => {
    render(<ConfigForm />, { wrapper: createWrapper() });
    expect(screen.getByText("Stock")).toBeInTheDocument();
    expect(screen.getByText("Crypto Futures")).toBeInTheDocument();
  });

  it("shows validation error for empty ticker on submit", async () => {
    const user = userEvent.setup();
    render(<ConfigForm />, { wrapper: createWrapper() });
    await user.click(screen.getByRole("button", { name: /start analysis/i }));
    expect(await screen.findByText(/ticker is required/i)).toBeInTheDocument();
  });

  it("shows validation error for invalid ticker format", async () => {
    const user = userEvent.setup();
    render(<ConfigForm />, { wrapper: createWrapper() });
    await user.type(screen.getByLabelText(/ticker/i), "invalid ticker!!");
    await user.click(screen.getByRole("button", { name: /start analysis/i }));
    expect(await screen.findByText(/valid ticker/i)).toBeInTheDocument();
  });

  it("submits valid form and navigates to run page", async () => {
    const user = userEvent.setup();
    mockStartAnalysis.mockResolvedValue({ run_id: "new-run-123", status: "running" });
    render(<ConfigForm />, { wrapper: createWrapper() });
    await fillAndSubmit(user, "SPY");
    await waitFor(() => {
      expect(mockStartAnalysis).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: "SPY", analysis_date: "2025-06-01" }),
      );
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.objectContaining({ to: "/analysis/$runId", params: { runId: "new-run-123" } }),
      );
    });
  });

  it("shows provider select field", () => {
    render(<ConfigForm />, { wrapper: createWrapper() });
    expect(screen.getByLabelText(/provider/i)).toBeInTheDocument();
  });

  it("disables submit button while submitting", async () => {
    const user = userEvent.setup();
    let resolveSubmit: (v: unknown) => void;
    mockStartAnalysis.mockReturnValue(new Promise((r) => { resolveSubmit = r; }));
    render(<ConfigForm />, { wrapper: createWrapper() });
    await fillAndSubmit(user, "AAPL");
    expect(screen.getByRole("button", { name: /starting/i })).toBeDisabled();
    resolveSubmit!({ run_id: "r1", status: "running" });
  });

  it("shows error message on submit failure", async () => {
    const user = userEvent.setup();
    mockStartAnalysis.mockRejectedValue(new Error("Network error"));
    render(<ConfigForm />, { wrapper: createWrapper() });
    await fillAndSubmit(user, "SPY");
    expect(await screen.findByText(/network error/i)).toBeInTheDocument();
  });

  it("rejects path-traversal ticker attempts", async () => {
    const user = userEvent.setup();
    render(<ConfigForm />, { wrapper: createWrapper() });
    await user.type(screen.getByLabelText(/ticker/i), "../etc");
    await user.click(screen.getByRole("button", { name: /start analysis/i }));
    expect(await screen.findByText(/valid ticker/i)).toBeInTheDocument();
    expect(mockStartAnalysis).not.toHaveBeenCalled();
  });

  // Crypto-specific tests
  describe("crypto mode", () => {
    it("switches to crypto mode and shows trading pair label", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      expect(screen.getByLabelText(/trading pair/i)).toBeInTheDocument();
    });

    it("shows crypto analysts when crypto mode selected", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      const checkboxes = screen.getAllByRole("checkbox");
      expect(checkboxes.length).toBe(3);
    });

    it("shows kline interval selector in crypto mode", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      expect(screen.getByText(/kline interval/i)).toBeInTheDocument();
    });

    it("hides data sources in crypto mode", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      expect(screen.queryByText(/data sources/i)).not.toBeInTheDocument();
    });

    it("submits with asset_type crypto", async () => {
      const user = userEvent.setup();
      mockStartAnalysis.mockResolvedValue({ run_id: "crypto-run", status: "running" });
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      await fillAndSubmit(user, "BTCUSDT");
      await waitFor(() => {
        expect(mockStartAnalysis).toHaveBeenCalledWith(
          expect.objectContaining({ ticker: "BTCUSDT", asset_type: "crypto" }),
        );
      });
    });

    it("clears ticker when switching asset type", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.type(screen.getByLabelText(/ticker/i), "AAPL");
      await user.click(screen.getByText("Crypto Futures"));
      expect(screen.getByLabelText(/trading pair/i)).toHaveValue("");
    });

    it("rejects invalid crypto ticker format", async () => {
      const user = userEvent.setup();
      render(<ConfigForm />, { wrapper: createWrapper() });
      await user.click(screen.getByText("Crypto Futures"));
      await user.type(screen.getByLabelText(/trading pair/i), "X");
      fireEvent.change(screen.getByLabelText(/date/i), { target: { value: "2025-06-01" } });
      await user.click(screen.getByRole("button", { name: /start analysis/i }));
      expect(await screen.findByText(/valid pair/i)).toBeInTheDocument();
    });
  });
});
