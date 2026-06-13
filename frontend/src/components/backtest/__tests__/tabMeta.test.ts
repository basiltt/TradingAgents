import { describe, it, expect } from "vitest";
import { TAB_ORDER, TAB_LABELS, FIELD_PATHS_BY_TAB } from "../config-form/tabMeta";
import { buildDefaults } from "../configSchema";

describe("tabMeta", () => {
  it("orders the four lifecycle tabs", () => {
    expect(TAB_ORDER).toEqual(["setup", "strategy", "risk", "filters"]);
  });

  it("labels every tab", () => {
    for (const id of TAB_ORDER) expect(TAB_LABELS[id]).toBeTruthy();
  });

  it("assigns every top-level schema field to exactly one tab", () => {
    // scan_source.* is represented by the single top-level key "scan_source".
    const schemaKeys = Object.keys(buildDefaults()).sort();
    const mapped = TAB_ORDER.flatMap((id) => FIELD_PATHS_BY_TAB[id]);
    // No duplicates across tabs.
    expect(new Set(mapped).size).toBe(mapped.length);
    // Union equals the full schema key set (no orphans, no extras).
    expect([...new Set(mapped)].sort()).toEqual(schemaKeys);
  });
});
