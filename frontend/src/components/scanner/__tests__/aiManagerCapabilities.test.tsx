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
