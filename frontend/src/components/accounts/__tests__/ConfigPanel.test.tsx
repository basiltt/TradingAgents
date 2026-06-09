import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import React from "react";

// AI-CONTEXT: This suite guards the ConfigPanel validate-and-block behavior added
// during hardening (previously out-of-range fields were silently dropped and the
// save appeared to succeed). NOTE: ConfigPanel is not currently mounted anywhere in
// the app (tracked as a dead-code decision); this test still protects the validation
// logic so it can't regress if/when the panel is wired into the UI.

const { toastError, patchConfig, fetchConfigFn } = vi.hoisted(() => ({
  toastError: vi.fn(),
  patchConfig: vi.fn().mockResolvedValue({ status: "ok" }),
  fetchConfigFn: vi.fn().mockResolvedValue({}),
}));

vi.mock("sonner", () => ({ toast: { error: toastError, success: vi.fn() } }));

vi.mock("@/api/client", () => ({
  aiManagerApi: {
    patchConfig: (...args: unknown[]) => patchConfig(...args),
    getConfig: (...args: unknown[]) => fetchConfigFn(...args),
  },
}));

import { ConfigPanel } from "../ConfigPanel";
import aiManagerReducer from "@/store/ai-manager-slice";

function renderPanel() {
  const store = configureStore({ reducer: { aiManager: aiManagerReducer } });
  return render(
    React.createElement(
      Provider,
      { store, children: React.createElement(ConfigPanel, { accountId: "acc-1" }) },
    ),
  );
}

describe("ConfigPanel validation", () => {
  beforeEach(() => {
    toastError.mockClear();
    patchConfig.mockClear();
  });

  it("blocks save and shows an error toast when a field is out of range", async () => {
    renderPanel();
    // Wait for the mount-time fetchConfig to settle so the Save button is enabled.
    const saveBtn = await screen.findByRole("button", { name: /save config/i });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());

    // Confidence valid range is 0.3–0.95; 0.99 is out of range (the spinner max
    // does not prevent typing/paste).
    const confidence = screen.getByDisplayValue("0.7");
    fireEvent.change(confidence, { target: { value: "0.99" } });

    fireEvent.click(saveBtn);

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    // The PATCH must NOT have been dispatched for an invalid form.
    expect(patchConfig).not.toHaveBeenCalled();
    // The toast names the offending field.
    const [msg] = toastError.mock.calls[0];
    expect(String(msg)).toMatch(/fix/i);
  });

  it("saves when all fields are within range", async () => {
    renderPanel();
    const saveBtn = await screen.findByRole("button", { name: /save config/i });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());
    fireEvent.click(saveBtn);
    await waitFor(() => expect(patchConfig).toHaveBeenCalled());
    expect(toastError).not.toHaveBeenCalled();
  });
});
