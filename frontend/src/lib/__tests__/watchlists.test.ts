import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadWatchlists, createWatchlist, deleteWatchlist, renameWatchlist, addTicker, removeTicker } from "../watchlists";

describe("watchlists", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("crypto", { randomUUID: () => "test-uuid-1" });
  });

  it("loadWatchlists returns empty array when no data", () => {
    expect(loadWatchlists()).toEqual([]);
  });

  it("loadWatchlists returns empty array on corrupt JSON", () => {
    localStorage.setItem("tradingagents_watchlists", "not-json");
    expect(loadWatchlists()).toEqual([]);
  });

  it("createWatchlist adds a new watchlist", () => {
    const result = createWatchlist("My List");
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ id: "test-uuid-1", name: "My List", tickers: [] });
    expect(loadWatchlists()).toHaveLength(1);
  });

  it("deleteWatchlist removes by id", () => {
    createWatchlist("First");
    vi.stubGlobal("crypto", { randomUUID: () => "test-uuid-2" });
    createWatchlist("Second");
    const result = deleteWatchlist("test-uuid-1");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("test-uuid-2");
  });

  it("renameWatchlist changes name", () => {
    createWatchlist("Old Name");
    const result = renameWatchlist("test-uuid-1", "New Name");
    expect(result[0].name).toBe("New Name");
  });

  it("addTicker adds ticker to watchlist", () => {
    createWatchlist("List");
    const result = addTicker("test-uuid-1", "BTCUSDT");
    expect(result[0].tickers).toEqual(["BTCUSDT"]);
  });

  it("addTicker does not add duplicate", () => {
    createWatchlist("List");
    addTicker("test-uuid-1", "BTCUSDT");
    const result = addTicker("test-uuid-1", "BTCUSDT");
    expect(result[0].tickers).toEqual(["BTCUSDT"]);
  });

  it("addTicker caps at 10 tickers", () => {
    createWatchlist("List");
    for (let i = 0; i < 10; i++) {
      addTicker("test-uuid-1", `T${i}`);
    }
    const result = addTicker("test-uuid-1", "T10");
    expect(result[0].tickers).toHaveLength(10);
    expect(result[0].tickers).not.toContain("T10");
  });

  it("removeTicker removes from watchlist", () => {
    createWatchlist("List");
    addTicker("test-uuid-1", "BTCUSDT");
    addTicker("test-uuid-1", "ETHUSDT");
    const result = removeTicker("test-uuid-1", "BTCUSDT");
    expect(result[0].tickers).toEqual(["ETHUSDT"]);
  });
});
