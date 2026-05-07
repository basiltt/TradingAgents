import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer from "@/store/accounts-slice";
import { uiSlice } from "@/store/ui-slice";
import { analysisSlice } from "@/store/analysis-slice";
import { AddAccountDialog } from "../AddAccountDialog";

vi.mock("@/api/client", () => ({
  accountsApi: {
    create: vi.fn(),
  },
}));

import { accountsApi } from "@/api/client";

function createWrapper() {
  const store = configureStore({
    reducer: { accounts: accountsReducer, ui: uiSlice.reducer, analysis: analysisSlice.reducer },
  });
  return {
    store,
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    ),
  };
}

describe("AddAccountDialog", () => {
  const onOpenChange = vi.fn();
  const onCreated = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders step 1 with label input", () => {
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });
    expect(screen.getByText("Add Trading Account")).toBeInTheDocument();
    expect(screen.getByLabelText("Account Label")).toBeInTheDocument();
  });

  it("Next button disabled when label empty", () => {
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });
    const nextBtn = screen.getByRole("button", { name: "Next" });
    expect(nextBtn).toBeDisabled();
  });

  it("advances to step 2 when label filled and Next clicked", async () => {
    const user = userEvent.setup();
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });
    await user.type(screen.getByLabelText("Account Label"), "My Account");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();
    expect(screen.getByLabelText("API Secret")).toBeInTheDocument();
  });

  it("Test & Save button disabled when credentials empty", async () => {
    const user = userEvent.setup();
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });
    await user.type(screen.getByLabelText("Account Label"), "My Account");
    await user.click(screen.getByRole("button", { name: "Next" }));
    const saveBtn = screen.getByRole("button", { name: "Test & Save" });
    expect(saveBtn).toBeDisabled();
  });

  it("shows success on step 3 after successful creation", async () => {
    const user = userEvent.setup();
    (accountsApi.create as any).mockResolvedValue({ id: "1", label: "My Account", account_type: "demo" });
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });

    await user.type(screen.getByLabelText("Account Label"), "My Account");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("API Key"), "my-api-key-123456");
    await user.type(screen.getByLabelText("API Secret"), "my-secret-key-12345");
    await user.click(screen.getByRole("button", { name: "Test & Save" }));

    await waitFor(() => {
      expect(screen.getByText(/connected successfully/)).toBeInTheDocument();
    });
    expect(onCreated).toHaveBeenCalled();
  });

  it("shows error when creation fails", async () => {
    const user = userEvent.setup();
    (accountsApi.create as any).mockRejectedValue({ detail: "Invalid API key" });
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={true} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });

    await user.type(screen.getByLabelText("Account Label"), "My Account");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("API Key"), "my-api-key-123456");
    await user.type(screen.getByLabelText("API Secret"), "my-secret-key-12345");
    await user.click(screen.getByRole("button", { name: "Test & Save" }));

    await waitFor(() => {
      expect(screen.getByText("Invalid API key")).toBeInTheDocument();
    });
  });

  it("does not render when open is false", () => {
    const { wrapper } = createWrapper();
    render(<AddAccountDialog open={false} onOpenChange={onOpenChange} onCreated={onCreated} />, { wrapper });
    expect(screen.queryByText("Add Trading Account")).not.toBeInTheDocument();
  });
});
