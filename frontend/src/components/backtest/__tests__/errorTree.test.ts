import { describe, it, expect } from "vitest";
import { errorMessageAt, hasErrorAt, collectErrors } from "../config-form/errorTree";

// A shape mirroring react-hook-form's nested `errors` object: leaf fields carry a
// { message }, intermediate nodes nest, and RHF attaches ref/types metadata.
const errors = {
  leverage: { message: "Too high", ref: {}, type: "max" },
  scan_source: {
    schedule_id: { message: "Select a schedule" },
  },
  ref: { name: "noise" },
};

describe("errorTree", () => {
  describe("errorMessageAt", () => {
    it("returns a leaf message by path", () => {
      expect(errorMessageAt(errors, "leverage")).toBe("Too high");
    });
    it("returns a nested leaf message by dotted path", () => {
      expect(errorMessageAt(errors, "scan_source.schedule_id")).toBe("Select a schedule");
    });
    it("returns undefined for a clean field", () => {
      expect(errorMessageAt(errors, "capital_pct")).toBeUndefined();
    });
    it("returns undefined for a subtree (no message at that exact node)", () => {
      expect(errorMessageAt(errors, "scan_source")).toBeUndefined();
    });
  });

  describe("hasErrorAt", () => {
    it("is true for a leaf field with a message", () => {
      expect(hasErrorAt(errors, "leverage")).toBe(true);
    });
    it("is true for a subtree containing a nested message", () => {
      expect(hasErrorAt(errors, "scan_source")).toBe(true);
    });
    it("is false for a clean field", () => {
      expect(hasErrorAt(errors, "capital_pct")).toBe(false);
    });
    it("does not treat ref/types metadata as errors", () => {
      expect(hasErrorAt({ ref: { name: "x" }, types: {} }, "ref")).toBe(false);
    });
  });

  describe("collectErrors", () => {
    it("flattens every leaf to a dotted path + message, skipping metadata", () => {
      const flat = collectErrors(errors).sort((a, b) => a.path.localeCompare(b.path));
      expect(flat).toEqual([
        { path: "leverage", message: "Too high" },
        { path: "scan_source.schedule_id", message: "Select a schedule" },
      ]);
    });
  });
});
