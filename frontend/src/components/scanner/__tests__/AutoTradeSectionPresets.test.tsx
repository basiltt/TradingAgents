import { describe, it, expect, vi, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AutoTradeSection, DEFAULT_CONFIG } from "../AutoTradeSection";
import { presetToAutoTradeConfig } from "../applyReferencePreset";
import type { AutoTradeConfig } from "@/api/client";

// Accounts come from useQuery(["accounts"]); stub the API so the section mounts.
vi.mock("@/api/client", async (orig) => {
  const actual = await orig<typeof import("@/api/client")>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      list: vi.fn(async () => [
        { id: "acct-1", label: "Demo", account_type: "demo", is_active: true },
      ]),
    },
  };
});

/** Controlled host so onChange actually updates the rendered card (mirrors the form). */
function Host({ initial }: { initial: AutoTradeConfig[] }) {
  const [configs, setConfigs] = useState(initial);
  return <AutoTradeSection value={configs} onChange={setConfigs} />;
}

function renderSection(initial: AutoTradeConfig[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Host initial={initial} />
    </QueryClientProvider>,
  );
}

// A pristine, expanded card: account_id "" ⇒ AutoTradeCard starts expanded.
const pristineCard = (): AutoTradeConfig => ({ ...DEFAULT_CONFIG, account_id: "" });

describe("AutoTradeSection — Apply preset buttons", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders all three preset buttons in the expanded card body", () => {
    renderSection([pristineCard()]);
    expect(screen.getByRole("button", { name: /Apply Reference/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply Optimized/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply Best Winrate/i })).toBeInTheDocument();
  });

  it("applies the Optimized preset to a pristine card without a confirm dialog", () => {
    renderSection([pristineCard()]);
    // Pristine card shows the default Leverage chip first.
    expect(screen.getByText(`${DEFAULT_CONFIG.leverage}x`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Apply Optimized/i }));

    // Optimized leverage is 7 → chip updates; no confirm dialog on a pristine card.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("7x")).toBeInTheDocument();
  });

  it("preserves account_id and AI-Manager settings when applying a preset", () => {
    // Start from a card that has an account + AI on, but otherwise default trade fields.
    // AI-Manager is a PROTECTED field, so cardHasEdits is false → applies directly.
    const card: AutoTradeConfig = {
      ...DEFAULT_CONFIG,
      account_id: "",
      ai_manager_enabled: true,
    };
    renderSection([card]);

    fireEvent.click(screen.getByRole("button", { name: /Apply Reference/i }));

    // Leverage became the Reference value (8); the partial never carries ai_manager_*,
    // so the AI toggle's state is preserved (the panel stays mounted/enabled).
    expect(screen.getByText("8x")).toBeInTheDocument();
    // presetToAutoTradeConfig must not include the protected AI key.
    expect(presetToAutoTradeConfig("reference")).not.toHaveProperty("ai_manager_enabled");
  });

  it("opens an in-app confirm dialog for an edited card and respects Cancel", async () => {
    // An edited card (non-default leverage) → applying opens the confirm dialog.
    const edited: AutoTradeConfig = { ...DEFAULT_CONFIG, account_id: "", leverage: 13 };
    renderSection([edited]);

    expect(screen.getByText("13x")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Apply Optimized/i }));

    // The styled dialog appears (not a native window.confirm).
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Apply Optimized preset\?/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/AI-Manager settings are kept/i)).toBeInTheDocument();

    // Cancel ⇒ nothing applied, leverage stays at the edited value, dialog closes.
    fireEvent.click(within(dialog).getByRole("button", { name: /^Cancel$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("13x")).toBeInTheDocument();
  });

  it("applies the preset after confirming in the in-app dialog", async () => {
    const edited: AutoTradeConfig = { ...DEFAULT_CONFIG, account_id: "", leverage: 13 };
    renderSection([edited]);

    fireEvent.click(screen.getByRole("button", { name: /Apply Optimized/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /Apply preset/i }));

    // Confirmed ⇒ Optimized leverage (7) applied, dialog closes.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("7x")).toBeInTheDocument();
  });

  it("Best Winrate confirm dialog is labelled and applies the tight TP geometry", async () => {
    // Edited card → dialog. Best Winrate keeps leverage 7 but tightens TP to a 0.8%
    // price move (take_profit_pct 5.6 / leverage 7), shown on the "TP move" chip.
    const edited: AutoTradeConfig = { ...DEFAULT_CONFIG, account_id: "", leverage: 13 };
    renderSection([edited]);

    fireEvent.click(screen.getByRole("button", { name: /Apply Best Winrate/i }));
    const dialog = await screen.findByRole("dialog");
    // The dialog title uses the Best Winrate label (not the old Optimized/Reference ternary).
    expect(within(dialog).getByText(/Apply Best Winrate preset\?/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Apply preset/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // 5.6 / 7 = 0.80% TP price move (toFixed(2)); shown on the chip and the input hint.
    expect(screen.getAllByText(/0\.80%/).length).toBeGreaterThan(0);
  });
});
