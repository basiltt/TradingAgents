import { describe, it, expect } from "vitest";
import {
  AI_MANAGER_CAPABILITIES,
  AI_CAPABILITY_KEYS,
  allCapabilitiesOn,
  type AICapabilityKey,
} from "../aiManagerCapabilities";

const EXPECTED_KEYS: AICapabilityKey[] = [
  "mtf", "orderbook", "sweep_defense", "correlation",
  "regime_enhanced", "event_driven", "trailing", "emergency_close",
];

describe("AI_MANAGER_CAPABILITIES metadata", () => {
  it("lists all 8 capabilities with title + description", () => {
    expect(AI_MANAGER_CAPABILITIES.map((c) => c.key)).toEqual(EXPECTED_KEYS);
    for (const cap of AI_MANAGER_CAPABILITIES) {
      expect(cap.title.length).toBeGreaterThan(0);
      expect(cap.description.length).toBeGreaterThan(0);
    }
  });

  it("metadata covers exactly the compile-time-checked key set", () => {
    // AI_CAPABILITY_KEYS is derived from a Record<keyof AIManagerCapabilities, true>,
    // so this fails if the metadata array drifts from the interface key set.
    expect(AI_MANAGER_CAPABILITIES.map((c) => c.key).sort()).toEqual(
      [...AI_CAPABILITY_KEYS].sort(),
    );
  });
});


describe("allCapabilitiesOn", () => {
  it("returns every capability set to true", () => {
    const all = allCapabilitiesOn();
    for (const key of EXPECTED_KEYS) {
      expect(all[key]).toBe(true);
    }
  });

  it("returns exactly the expected key set (catches metadata drift)", () => {
    // Derived from AI_MANAGER_CAPABILITIES — guards against a key being added to
    // the interface/metadata without being reflected here, or vice-versa.
    expect(Object.keys(allCapabilitiesOn()).sort()).toEqual(
      [...EXPECTED_KEYS].sort(),
    );
  });
});

import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { AICapabilityPanel } from "../AICapabilityPanel";

describe("AICapabilityPanel", () => {
  it("renders a toggle for each of the 8 capabilities", () => {
    render(<AICapabilityPanel value={allCapabilitiesOn()} onChange={vi.fn()} />);
    // NeuSwitch renders role="switch" (not checkbox).
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(8);
  });

  it("flips a single capability without touching the others", () => {
    const onChange = vi.fn();
    render(<AICapabilityPanel value={allCapabilitiesOn()} onChange={onChange} />);
    // Each row wraps its switch in a data-testid container (NeuSwitch does not
    // forward arbitrary props). Click the switch inside the mtf row.
    const mtfRow = screen.getByTestId("ai-cap-row-mtf");
    fireEvent.click(mtfRow.querySelector('[role="switch"]')!);
    expect(onChange).toHaveBeenCalledTimes(1);
    const payload = onChange.mock.calls[0][0];
    expect(payload.mtf).toBe(false);
    expect(payload.orderbook).toBe(true);
  });

  it("reset button restores all-on", () => {
    const onChange = vi.fn();
    const partial = { ...allCapabilitiesOn(), mtf: false, trailing: false };
    render(<AICapabilityPanel value={partial} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("ai-cap-reset"));
    expect(onChange).toHaveBeenCalledWith(allCapabilitiesOn());
  });

  it("shows no safety warning when all capabilities are on", () => {
    render(<AICapabilityPanel value={allCapabilitiesOn()} onChange={vi.fn()} />);
    expect(screen.queryByTestId("ai-cap-safety-warning")).toBeNull();
  });

  it("warns when emergency_close is turned off", () => {
    const value = { ...allCapabilitiesOn(), emergency_close: false };
    render(<AICapabilityPanel value={value} onChange={vi.fn()} />);
    const warning = screen.getByTestId("ai-cap-safety-warning");
    expect(warning.textContent).toContain("Emergency Close");
    // crash-protection-specific copy
    expect(warning.textContent).toContain("crash protection off");
  });

  it("warns when sweep_defense is turned off (with sweep-accurate copy)", () => {
    const value = { ...allCapabilitiesOn(), sweep_defense: false };
    render(<AICapabilityPanel value={value} onChange={vi.fn()} />);
    const warning = screen.getByTestId("ai-cap-safety-warning");
    expect(warning.textContent).toContain("Sweep");
    // sweep_defense off means the AI is MORE willing to close — copy reflects that
    expect(warning.textContent).toContain("stop-hunts");
  });

  it("exposes the safety warning as an alert for screen readers", () => {
    const value = { ...allCapabilitiesOn(), emergency_close: false };
    render(<AICapabilityPanel value={value} onChange={vi.fn()} />);
    expect(screen.getByTestId("ai-cap-safety-warning").getAttribute("role")).toBe(
      "alert",
    );
  });

  it("removes the warning after re-enabling the safety capability", () => {
    const { rerender } = render(
      <AICapabilityPanel
        value={{ ...allCapabilitiesOn(), emergency_close: false }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("ai-cap-safety-warning")).toBeTruthy();
    rerender(
      <AICapabilityPanel value={allCapabilitiesOn()} onChange={vi.fn()} />,
    );
    expect(screen.queryByTestId("ai-cap-safety-warning")).toBeNull();
  });

  it("normalizes a partial capability object so missing keys render ON", () => {
    // Only one key present — the other 7 must still render as ON (defined),
    // and flipping one must persist the full 8-key object.
    const onChange = vi.fn();
    const partial = { mtf: false } as unknown as Parameters<
      typeof AICapabilityPanel
    >[0]["value"];
    render(<AICapabilityPanel value={partial} onChange={onChange} />);
    // 8 switches still render
    expect(screen.getAllByRole("switch")).toHaveLength(8);
    // flipping orderbook emits a full object with all keys defined
    const row = screen.getByTestId("ai-cap-row-orderbook");
    fireEvent.click(row.querySelector('[role="switch"]')!);
    const payload = onChange.mock.calls[0][0];
    expect(Object.keys(payload).sort()).toEqual([...EXPECTED_KEYS].sort());
    expect(payload.mtf).toBe(false); // preserved
    expect(payload.orderbook).toBe(false); // flipped
    expect(payload.trailing).toBe(true); // normalized to on
  });
});


