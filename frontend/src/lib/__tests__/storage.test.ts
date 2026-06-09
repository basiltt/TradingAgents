import { describe, it, expect, beforeEach } from "vitest";
import { readJson, writeJson } from "../storage";

// AI-CONTEXT: The throw-on-quota / throw-on-denied catch branches are intentionally
// NOT unit-tested here. happy-dom's localStorage methods are non-writable instance
// properties (not on Storage.prototype), so they cannot be reliably stubbed to throw
// without corrupting the shared instance for subsequent tests. The catch branches are
// trivial `try { … } catch { return fallback/false }` swallows; the malformed-JSON
// test below exercises the readJson catch path genuinely (JSON.parse throws on its
// own), and the write/read round-trip proves the happy path end to end.

describe("readJson", () => {
  beforeEach(() => localStorage.clear());

  it("returns the parsed value for valid stored JSON", () => {
    localStorage.setItem("k", JSON.stringify({ a: 1 }));
    expect(readJson("k", null)).toEqual({ a: 1 });
  });

  it("returns the fallback when the key is absent", () => {
    expect(readJson("missing", [])).toEqual([]);
  });

  it("returns the fallback for malformed JSON instead of throwing (exercises catch)", () => {
    localStorage.setItem("bad", "{not json");
    expect(readJson("bad", "fallback")).toBe("fallback");
  });

  it("returns the typed fallback for an empty store", () => {
    expect(readJson<number[]>("empty", [1])).toEqual([1]);
  });
});

describe("writeJson", () => {
  beforeEach(() => localStorage.clear());

  it("writes serialized JSON and returns true", () => {
    expect(writeJson("k", { a: 1 })).toBe(true);
    expect(localStorage.getItem("k")).toBe(JSON.stringify({ a: 1 }));
  });

  it("round-trips with readJson", () => {
    writeJson("rt", [1, 2, 3]);
    expect(readJson<number[]>("rt", [])).toEqual([1, 2, 3]);
  });

  it("overwrites an existing key", () => {
    writeJson("k", { v: 1 });
    writeJson("k", { v: 2 });
    expect(readJson("k", null)).toEqual({ v: 2 });
  });
});
