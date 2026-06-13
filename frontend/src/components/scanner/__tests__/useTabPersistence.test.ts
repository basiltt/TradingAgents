import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTabPersistence } from "../form-tabs/useTabPersistence";

const KEY = "test_tab_key";
const ORDER = ["a", "b", "c"] as const;

describe("useTabPersistence", () => {
  beforeEach(() => localStorage.clear());

  it("falls back to the first tab when nothing is stored", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a");
  });

  it("uses an explicit fallback when provided and nothing is stored", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER, "b"));
    expect(result.current[0]).toBe("b");
  });

  it("restores a valid stored id on mount", () => {
    localStorage.setItem(KEY, "c");
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("c");
  });

  it("ignores a stored id that is not in the order (falls back)", () => {
    localStorage.setItem(KEY, "zzz");
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a");
  });

  it("saves to localStorage on setTab", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    act(() => result.current[1]("b"));
    expect(result.current[0]).toBe("b");
    expect(localStorage.getItem(KEY)).toBe("b");
  });

  it("does NOT write to localStorage on mount", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    renderHook(() => useTabPersistence(KEY, ORDER));
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("degrades gracefully when localStorage.getItem throws", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a"); // falls back, no throw
    getItem.mockRestore();
  });

  it("degrades gracefully when localStorage.setItem throws (still updates state)", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    // The write throws internally but is swallowed; state must still advance and the
    // call must not throw (private-mode / quota scenarios must never break a tab click).
    expect(() => act(() => result.current[1]("b"))).not.toThrow();
    expect(result.current[0]).toBe("b");
    setItem.mockRestore();
  });
});
