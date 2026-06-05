import { describe, it, expect, beforeEach } from "vitest";
import {
  getBasket,
  addToBasket,
  removeFromBasket,
  clearBasket,
  isInBasket,
  MAX_BASKET,
} from "../comparisonBasket";

beforeEach(() => {
  clearBasket();
});

describe("comparisonBasket", () => {
  it("starts empty", () => {
    expect(getBasket()).toEqual([]);
  });

  it("adds ids and reports membership", () => {
    addToBasket("a");
    addToBasket("b");
    expect(getBasket()).toEqual(["a", "b"]);
    expect(isInBasket("a")).toBe(true);
    expect(isInBasket("z")).toBe(false);
  });

  it("does not add duplicates", () => {
    addToBasket("a");
    addToBasket("a");
    expect(getBasket()).toEqual(["a"]);
  });

  it("enforces the max basket size", () => {
    for (let i = 0; i < MAX_BASKET + 3; i++) addToBasket(`run-${i}`);
    expect(getBasket()).toHaveLength(MAX_BASKET);
  });

  it("removes ids", () => {
    addToBasket("a");
    addToBasket("b");
    removeFromBasket("a");
    expect(getBasket()).toEqual(["b"]);
  });

  it("clears the basket", () => {
    addToBasket("a");
    clearBasket();
    expect(getBasket()).toEqual([]);
  });

  it("survives corrupt storage gracefully", () => {
    sessionStorage.setItem("backtest_comparison_basket", "{not json");
    expect(getBasket()).toEqual([]);
  });

  it("returns empty for valid JSON that is not an array", () => {
    sessionStorage.setItem("backtest_comparison_basket", '{"a":1}');
    expect(getBasket()).toEqual([]);
  });

  it("filters out non-string elements", () => {
    sessionStorage.setItem("backtest_comparison_basket", '[1, "run-a", null, "run-b"]');
    expect(getBasket()).toEqual(["run-a", "run-b"]);
  });
});
