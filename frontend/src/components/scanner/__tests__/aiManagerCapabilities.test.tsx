import { describe, it, expect } from "vitest";
import {
  AI_MANAGER_CAPABILITIES,
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
});

describe("allCapabilitiesOn", () => {
  it("returns every capability set to true", () => {
    const all = allCapabilitiesOn();
    for (const key of EXPECTED_KEYS) {
      expect(all[key]).toBe(true);
    }
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
});

