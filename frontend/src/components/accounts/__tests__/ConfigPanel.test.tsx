import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import React from "react";

// AI-CONTEXT: This suite guards the ConfigPanel validate-and-block behavior and the
// persisted capability toggles. ConfigPanel is mounted in AIMonitorPanel (the account
// "AI Monitor" tab), so this protects the validation logic and the capability PATCH
// payload from regressing.

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

  it("persists capability toggles in the PATCH payload", async () => {
    renderPanel();
    const saveBtn = await screen.findByRole("button", { name: /save config/i });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());

    // Default-on; turn emergency_close OFF.
    const emergency = screen.getByTestId("account-cap-emergency_close_enabled") as HTMLInputElement;
    expect(emergency.checked).toBe(true);
    fireEvent.click(emergency);
    expect(emergency.checked).toBe(false);

    fireEvent.click(saveBtn);
    await waitFor(() => expect(patchConfig).toHaveBeenCalled());
    // aiManagerApi.patchConfig is called as (accountId, updates)
    const updates = patchConfig.mock.calls[0][1] as Record<string, unknown>;
    expect(updates.emergency_close_enabled).toBe(false);
    expect(updates.mtf_enabled).toBe(true); // untouched stays on
  });

  it("shows a crash-protection warning when emergency_close is disabled", async () => {
    renderPanel();
    await screen.findByRole("button", { name: /save config/i });
    fireEvent.click(screen.getByTestId("account-cap-emergency_close_enabled"));
    expect(screen.getByText(/crash protection reduced/i)).toBeTruthy();
  });
});
