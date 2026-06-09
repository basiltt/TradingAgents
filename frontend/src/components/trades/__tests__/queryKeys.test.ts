import { describe, it, expect } from "vitest";
import { tradeQueryKeys } from "../queryKeys";

describe("tradeQueryKeys", () => {
  it("exposes the domain root key", () => {
    expect(tradeQueryKeys.all).toEqual(["trades"]);
  });

  it("history() returns the invalidation prefix", () => {
    expect(tradeQueryKeys.history()).toEqual(["trades", "history"]);
  });

  it("historyList() appends the filters for a full query key", () => {
    const filters = { symbol: "BTC" };
    expect(tradeQueryKeys.historyList(filters)).toEqual(["trades", "history", filters]);
  });

  it("stats() returns the invalidation prefix", () => {
    expect(tradeQueryKeys.stats()).toEqual(["trades", "stats"]);
  });

  it("statsFor() sorts account ids so key identity is order-independent", () => {
    expect(tradeQueryKeys.statsFor(["b", "a", "c"])).toEqual(["trades", "stats", ["a", "b", "c"]]);
    // Same set in a different order produces an equal key (stable cache identity).
    expect(tradeQueryKeys.statsFor(["c", "a", "b"])).toEqual(tradeQueryKeys.statsFor(["a", "b", "c"]));
  });

  it("statsFor() does not mutate the caller's array", () => {
    const ids = ["b", "a"];
    tradeQueryKeys.statsFor(ids);
    expect(ids).toEqual(["b", "a"]); // original order preserved
  });

  it("active() returns the active-trades prefix", () => {
    expect(tradeQueryKeys.active()).toEqual(["trades", "active"]);
  });

  it("events() embeds the trade id", () => {
    expect(tradeQueryKeys.events("t-42")).toEqual(["trades", "events", "t-42"]);
  });

  it("history() prefix is a prefix of historyList() (TanStack invalidation contract)", () => {
    const prefix = tradeQueryKeys.history();
    const full = tradeQueryKeys.historyList({ x: 1 });
    expect(full.slice(0, prefix.length)).toEqual(prefix);
  });
});
