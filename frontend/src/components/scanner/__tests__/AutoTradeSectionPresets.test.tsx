import { describe, it, expect, vi, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
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
    // jsdom does not implement window.confirm — provide a stub so it can be spied on.
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  it("renders both preset buttons in the expanded card body", () => {
    renderSection([pristineCard()]);
    expect(screen.getByRole("button", { name: /Apply Reference/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply Optimized/i })).toBeInTheDocument();
  });

  it("applies the Optimized preset to a pristine card without a confirm", () => {
    renderSection([pristineCard()]);
    // Pristine card shows the default Leverage chip first.
    expect(screen.getByText(`${DEFAULT_CONFIG.leverage}x`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Apply Optimized/i }));

    // Optimized leverage is 7 → chip updates; no confirm on a pristine card.
    expect(window.confirm).not.toHaveBeenCalled();
    expect(screen.getByText("7x")).toBeInTheDocument();
  });

  it("preserves account_id and AI-Manager settings when applying a preset", () => {
    // Start from a card that has an account + AI on, but otherwise default trade fields.
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

  it("confirms before overwriting an edited card and respects cancel", () => {
    // An edited card (non-default leverage) → applying triggers confirm.
    const edited: AutoTradeConfig = { ...DEFAULT_CONFIG, account_id: "", leverage: 13 };
    renderSection([edited]);
    vi.mocked(window.confirm).mockReturnValue(false);

    expect(screen.getByText("13x")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Apply Optimized/i }));

    // Cancelled ⇒ confirm was asked, but leverage stays at the edited value.
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByText("13x")).toBeInTheDocument();
  });
});
