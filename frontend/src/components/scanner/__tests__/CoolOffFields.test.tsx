import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { CoolOffFields } from "../CoolOffFields";
import type { AutoTradeConfig } from "@/api/client";

function baseConfig(overrides: Partial<AutoTradeConfig> = {}): AutoTradeConfig {
  return {
    account_id: "acct-1",
    cooloff_on_success_enabled: false,
    cooloff_on_success_minutes: null,
    cooloff_on_failure_enabled: false,
    cooloff_on_failure_minutes: null,
    cooloff_on_double_success_enabled: false,
    cooloff_on_double_success_minutes: null,
    cooloff_on_double_failure_enabled: false,
    cooloff_on_double_failure_minutes: null,
    ...overrides,
  } as AutoTradeConfig;
}

/**
 * Host that owns config state and merges partial onChange patches — mirrors how
 * AutoTradeSection drives CoolOffFields, so unit conversion and enable/default
 * behavior are exercised through a real controlled-component round trip.
 */
function Harness({
  initial,
  onChangeSpy,
}: {
  initial?: Partial<AutoTradeConfig>;
  onChangeSpy?: (patch: Partial<AutoTradeConfig>) => void;
}) {
  const [config, setConfig] = useState<AutoTradeConfig>(baseConfig(initial));
  return (
    <CoolOffFields
      config={config}
      onChange={(patch) => {
        onChangeSpy?.(patch);
        setConfig((c) => ({ ...c, ...patch }));
      }}
    />
  );
}

describe("CoolOffFields", () => {
  it("renders all four tiers grouped into Single trade and Win/loss streak", () => {
    render(<Harness />);
    expect(screen.getByText("Single trade")).toBeInTheDocument();
    expect(screen.getByText("Win / loss streak")).toBeInTheDocument();
    expect(screen.getByText("After a win")).toBeInTheDocument();
    expect(screen.getByText("After a loss")).toBeInTheDocument();
    expect(screen.getByText("After 2 wins in a row")).toBeInTheDocument();
    expect(screen.getByText("After 2 losses in a row")).toBeInTheDocument();
  });

  it("hides the duration input until a tier is enabled", () => {
    render(<Harness />);
    expect(screen.queryByLabelText("After a win duration")).not.toBeInTheDocument();
  });

  it("enabling a tier applies the default duration and reveals the input", () => {
    const spy = vi.fn();
    render(<Harness onChangeSpy={spy} />);
    fireEvent.click(screen.getByRole("switch", { name: "After a win" }));
    // success default is 30 minutes
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        cooloff_on_success_enabled: true,
        cooloff_on_success_minutes: 30,
      }),
    );
    expect(screen.getByLabelText("After a win duration")).toBeInTheDocument();
  });

  it.each([
    ["After a win", "cooloff_on_success_enabled", "cooloff_on_success_minutes", 30],
    ["After a loss", "cooloff_on_failure_enabled", "cooloff_on_failure_minutes", 60],
    ["After 2 wins in a row", "cooloff_on_double_success_enabled", "cooloff_on_double_success_minutes", 60],
    ["After 2 losses in a row", "cooloff_on_double_failure_enabled", "cooloff_on_double_failure_minutes", 120],
  ])("applies the correct default for tier '%s'", (label, enabledKey, minutesKey, def) => {
    const spy = vi.fn();
    render(<Harness onChangeSpy={spy} />);
    fireEvent.click(screen.getByRole("switch", { name: label }));
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ [enabledKey]: true, [minutesKey]: def }),
    );
  });

  it("preserves an existing duration when re-enabling rather than clobbering it", () => {
    const spy = vi.fn();
    // start disabled but with a stored 45m value
    render(<Harness initial={{ cooloff_on_failure_minutes: 45 }} onChangeSpy={spy} />);
    fireEvent.click(screen.getByRole("switch", { name: "After a loss" }));
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        cooloff_on_failure_enabled: true,
        cooloff_on_failure_minutes: 45, // preserved, not reset to default 60
      }),
    );
  });

  it("nulls an out-of-range duration when the tier is disabled (backend field-constraint safety)", () => {
    const spy = vi.fn();
    // Enabled with an over-max value (e.g. typed then toggling off).
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 99999 }}
        onChangeSpy={spy}
      />,
    );
    // Toggle the tier OFF.
    fireEvent.click(screen.getByRole("switch", { name: "After a loss" }));
    // The out-of-range value must be cleared (not preserved) so the disabled tier
    // can't 422 the backend on submit.
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        cooloff_on_failure_enabled: false,
        cooloff_on_failure_minutes: null,
      }),
    );
  });

  it("keeps an IN-RANGE duration when the tier is disabled (preserved for re-enable)", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 60 }}
        onChangeSpy={spy}
      />,
    );
    fireEvent.click(screen.getByRole("switch", { name: "After a loss" }));
    // A valid value survives the disable so re-enabling restores it (only OUT-of-range
    // values are nulled — the other arm of the disable ternary).
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        cooloff_on_failure_enabled: false,
        cooloff_on_failure_minutes: 60,
      }),
    );
  });

  it("converts an hours entry to canonical minutes (2 hr → 120 min)", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_success_enabled: true, cooloff_on_success_minutes: 120 }}
        onChangeSpy={spy}
      />,
    );
    // stored 120 (clean multiple of 60) initializes the unit selector to Hr.
    const input = screen.getByLabelText("After a win duration") as HTMLInputElement;
    expect(input.value).toBe("2");
    fireEvent.change(input, { target: { value: "3" } });
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_success_minutes: 180 });
  });

  it("stores an over-max minutes entry as-typed (no silent clamp; gate flags it)", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 5 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a loss duration");
    fireEvent.change(input, { target: { value: "999999" } });
    // Stored verbatim (rounded), not snapped to 43200 — the inline error + Launch/Save
    // gate reject it transparently rather than silently changing the user's intent.
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_failure_minutes: 999999 });
  });

  it("converts hours to minutes without clamping (800 hr → 48000 min, flagged invalid)", () => {
    const spy = vi.fn();
    render(
      <Harness
        // 120 min → initializes to Hr (clean multiple of 60)
        initial={{ cooloff_on_success_enabled: true, cooloff_on_success_minutes: 120 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a win duration");
    fireEvent.change(input, { target: { value: "800" } }); // 800 hr = 48000 min > max
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_success_minutes: 48000 });
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("emits null for a zero or negative entry", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 60 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a loss duration");
    fireEvent.change(input, { target: { value: "0" } });
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_failure_minutes: null });
  });

  it("emits null and shows an inline error + aria-invalid when the duration is cleared", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 60 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a loss duration");
    fireEvent.change(input, { target: { value: "" } });
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_failure_minutes: null });
    expect(screen.getByText(/Enter 1–43200m/)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("flags aria-invalid when a stored value exceeds the maximum (import/localStorage path)", () => {
    // The input clamps live typing, but a value can arrive >43200 from an imported
    // config; the field must then show invalid (parity with validateCooloff).
    render(
      <Harness initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 99999 }} />,
    );
    const input = screen.getByLabelText("After a loss duration");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("switching the unit to Hr re-displays the stored minutes in hours", () => {
    render(
      <Harness initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 90 }} />,
    );
    const input = screen.getByLabelText("After a loss duration") as HTMLInputElement;
    // 90 is not a clean multiple-of-60 boundary the initializer treats as Hr → starts in Min.
    expect(input.value).toBe("90");
    // Flip to Hr. The unit selector is a group of aria-pressed toggle buttons (only
    // the failure tier is enabled here → one "Hr" button).
    const hrButtons = screen.getAllByRole("button", { name: "Hr" });
    fireEvent.click(hrButtons[0]);
    expect((screen.getByLabelText("After a loss duration") as HTMLInputElement).value).toBe("1.5");
  });

  it("exposes the active unit via aria-pressed on the Min/Hr toggle", () => {
    render(
      <Harness initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 90 }} />,
    );
    const minBtn = screen.getByRole("button", { name: "Min" });
    const hrBtn = screen.getByRole("button", { name: "Hr" });
    expect(minBtn).toHaveAttribute("aria-pressed", "true");
    expect(hrBtn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(hrBtn);
    expect(screen.getByRole("button", { name: "Hr" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps an over-max typed value visible and flags it invalid (no silent clamp)", () => {
    const spy = vi.fn();
    render(
      <Harness
        // 45 min is not a clean hour multiple → initializes in Min mode.
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 45 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a loss duration");
    fireEvent.change(input, { target: { value: "99999" } });
    // Stored as-typed (rounded), NOT clamped — the gate/inline error handles it.
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_failure_minutes: 99999 });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Enter 1–43200m/)).toBeInTheDocument();
  });

  it("keeps an in-progress decimal draft visible without snapping, then reconciles on blur", () => {
    const spy = vi.fn();
    render(
      <Harness
        initial={{ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 30 }}
        onChangeSpy={spy}
      />,
    );
    const input = screen.getByLabelText("After a loss duration") as HTMLInputElement;
    // Type a fractional minutes value: the draft text is shown verbatim (no snap to
    // the rounded canonical value mid-edit), while onChange stores the rounded minutes.
    fireEvent.change(input, { target: { value: "1.5" } });
    expect(input.value).toBe("1.5");
    expect(spy).toHaveBeenLastCalledWith({ cooloff_on_failure_minutes: 2 }); // round(1.5)
    // On blur the draft clears and the field reconciles to the canonical stored value.
    fireEvent.blur(input);
    expect((screen.getByLabelText("After a loss duration") as HTMLInputElement).value).toBe("2");
  });
});
