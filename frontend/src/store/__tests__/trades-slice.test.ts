import { describe, it, expect } from "vitest";
import reducer, {
  setActiveTrades,
  addActiveTrade,
  updateActiveTrade,
  removeActiveTrade,
  setActiveTab,
  setFilters,
  setSortColumn,
  setSortDirection,
  setSelectedTradeId,
  setSelectedTrade,
  setCloseModalTradeId,
  startPendingAction,
  clearPendingAction,
  revertOptimisticUpdate,
  setPendingCloseAll,
  bulkRemoveActiveTrades,
  removeActiveTradesByAccount,
  updateUnrealizedPnl,
  setIsFetchingActiveTrades,
  setWsConnected,
  setLastUpdated,
} from "../trades-slice";
import type { Trade } from "@/components/trades/types";

function makeTrade(overrides: Partial<Trade> = {}): Trade {
  return {
    id: "t1",
    account_id: "acc1",
    symbol: "BTCUSD",
    side: "long",
    order_type: "market",
    qty: 1,
    filled_qty: null,
    remaining_qty: null,
    entry_price: 50000,
    avg_fill_price: null,
    exit_price: null,
    stop_loss_price: null,
    take_profit_price: null,
    leverage: 1,
    status: "open",
    realized_pnl: null,
    realized_pnl_pct: null,
    unrealized_pnl: null,
    fees: null,
    net_pnl: null,
    source: "manual",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    closed_at: null,
    version: 1,
    ...overrides,
  } as Trade;
}

const initialState = reducer(undefined, { type: "@@INIT" });

describe("trades-slice", () => {
  describe("initial state", () => {
    it("has correct defaults", () => {
      expect(initialState.activeTrades).toEqual({});
      expect(initialState.activeTab).toBe("active");
      expect(initialState.wsConnected).toBe(false);
      expect(initialState.isFetchingActiveTrades).toBe(false);
      expect(initialState.selectedTradeId).toBeNull();
      expect(initialState.selectedTrade).toBeNull();
      expect(initialState.lastUpdated).toBeNull();
      expect(initialState.pendingActions).toEqual({});
      expect(initialState.optimisticSnapshots).toEqual({});
      expect(initialState.sortColumn).toBe("created_at");
      expect(initialState.sortDirection).toBe("desc");
    });
  });

  describe("setActiveTrades", () => {
    it("sets trades from array, keyed by id", () => {
      const t1 = makeTrade({ id: "a" });
      const t2 = makeTrade({ id: "b" });
      const state = reducer(initialState, setActiveTrades([t1, t2]));
      expect(Object.keys(state.activeTrades)).toEqual(["a", "b"]);
      expect(state.activeTrades["a"].id).toBe("a");
    });

    it("preserves trades with pending actions", () => {
      const t = makeTrade({ id: "t1", status: "open" });
      let state = reducer(initialState, setActiveTrades([t]));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      // Now set active trades with a server version that has status "open" still
      const serverTrade = makeTrade({ id: "t1", status: "open" });
      state = reducer(state, setActiveTrades([serverTrade]));
      // Should keep the optimistic (closing) version
      expect(state.activeTrades["t1"].status).toBe("closing");
    });

    it("retains pending-action trades even if server omits them", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, setActiveTrades([t]));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      // Server returns empty array
      state = reducer(state, setActiveTrades([]));
      expect(state.activeTrades["t1"]).toBeDefined();
    });

    it("expires stale pending actions beyond TTL", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, setActiveTrades([t]));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      // Create a mutable copy with expired startedAt
      const mutableState = JSON.parse(JSON.stringify(state));
      mutableState.pendingActions["t1"].startedAt = Date.now() - 120_000;
      state = reducer(mutableState, setActiveTrades([]));
      // Expired, so trade should be gone
      expect(state.activeTrades["t1"]).toBeUndefined();
      expect(state.pendingActions["t1"]).toBeUndefined();
    });
  });

  describe("addActiveTrade", () => {
    it("adds a trade", () => {
      const t = makeTrade({ id: "x" });
      const state = reducer(initialState, addActiveTrade(t));
      expect(state.activeTrades["x"]).toEqual(t);
    });

    it("rejects stale version", () => {
      const t = makeTrade({ id: "x", version: 5 });
      let state = reducer(initialState, addActiveTrade(t));
      const stale = makeTrade({ id: "x", version: 3 });
      state = reducer(state, addActiveTrade(stale));
      expect(state.activeTrades["x"].version).toBe(5);
    });

    it("accepts newer version", () => {
      const t = makeTrade({ id: "x", version: 1 });
      let state = reducer(initialState, addActiveTrade(t));
      const newer = makeTrade({ id: "x", version: 2, entry_price: 99999 });
      state = reducer(state, addActiveTrade(newer));
      expect(state.activeTrades["x"].version).toBe(2);
      expect(state.activeTrades["x"].entry_price).toBe(99999);
    });
  });

  describe("updateActiveTrade", () => {
    it("updates an existing trade", () => {
      const t = makeTrade({ id: "t1", version: 1 });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, updateActiveTrade({ trade_id: "t1", updates: { status: "closed", version: 2 } }));
      expect(state.activeTrades["t1"].status).toBe("closed");
    });

    it("ignores update for non-existent trade", () => {
      const state = reducer(initialState, updateActiveTrade({ trade_id: "nope", updates: { status: "closed" } }));
      expect(state.activeTrades["nope"]).toBeUndefined();
    });

    it("ignores update with stale version", () => {
      const t = makeTrade({ id: "t1", version: 5 });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, updateActiveTrade({ trade_id: "t1", updates: { status: "closed", version: 3 } }));
      expect(state.activeTrades["t1"].status).toBe("open");
    });

    it("skips update if trade has pending action", () => {
      const t = makeTrade({ id: "t1", version: 1 });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      state = reducer(state, updateActiveTrade({ trade_id: "t1", updates: { status: "open", version: 2 } }));
      expect(state.activeTrades["t1"].status).toBe("closing");
    });
  });

  describe("removeActiveTrade", () => {
    it("removes a trade and clears selection if selected", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, setSelectedTradeId("t1"));
      state = reducer(state, removeActiveTrade("t1"));
      expect(state.activeTrades["t1"]).toBeUndefined();
      expect(state.selectedTradeId).toBeNull();
    });

    it("clears close modal if removed trade was in modal", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, setCloseModalTradeId("t1"));
      state = reducer(state, removeActiveTrade("t1"));
      expect(state.closeModalTradeId).toBeNull();
    });
  });

  describe("removeActiveTradesByAccount", () => {
    it("removes all trades for a given account", () => {
      const t1 = makeTrade({ id: "a", account_id: "acc1" });
      const t2 = makeTrade({ id: "b", account_id: "acc1" });
      const t3 = makeTrade({ id: "c", account_id: "acc2" });
      let state = reducer(initialState, setActiveTrades([t1, t2, t3]));
      state = reducer(state, removeActiveTradesByAccount("acc1"));
      expect(state.activeTrades["a"]).toBeUndefined();
      expect(state.activeTrades["b"]).toBeUndefined();
      expect(state.activeTrades["c"]).toBeDefined();
    });
  });

  describe("bulkRemoveActiveTrades", () => {
    it("removes multiple trades by id", () => {
      const t1 = makeTrade({ id: "a" });
      const t2 = makeTrade({ id: "b" });
      const t3 = makeTrade({ id: "c" });
      let state = reducer(initialState, setActiveTrades([t1, t2, t3]));
      state = reducer(state, bulkRemoveActiveTrades(["a", "c"]));
      expect(Object.keys(state.activeTrades)).toEqual(["b"]);
    });
  });

  describe("updateUnrealizedPnl", () => {
    const payload = (over = {}) => ({
      account_id: "acc1",
      symbol: "BTCUSD",
      side: "long",
      unrealized_pnl: 100,
      ...over,
    });

    it("distributes pnl pro-rata by qty across matching trades", () => {
      const t1 = makeTrade({ id: "a", qty: 3 });
      const t2 = makeTrade({ id: "b", qty: 1 });
      let state = reducer(initialState, setActiveTrades([t1, t2]));
      state = reducer(state, updateUnrealizedPnl(payload()));
      // total qty 4 → 100 split 75/25
      expect(state.activeTrades["a"].unrealized_pnl).toBeCloseTo(75);
      expect(state.activeTrades["b"].unrealized_pnl).toBeCloseTo(25);
    });

    it("treats a non-numeric qty as 0 so it doesn't poison the whole distribution", () => {
      // BUG GUARD: previously a NaN qty made totalQty NaN, forcing an equal split for
      // ALL trades. Now the bad qty counts as 0 and the valid one keeps the full pnl.
      const good = makeTrade({ id: "good", qty: 2 });
      const bad = makeTrade({ id: "bad", qty: "abc" as unknown as number });
      let state = reducer(initialState, setActiveTrades([good, bad]));
      state = reducer(state, updateUnrealizedPnl(payload()));
      expect(state.activeTrades["good"].unrealized_pnl).toBeCloseTo(100); // 2/2 of total
      expect(state.activeTrades["bad"].unrealized_pnl).toBeCloseTo(0);    // 0/2 of total
    });

    it("falls back to an equal split when all qtys are zero", () => {
      const t1 = makeTrade({ id: "a", qty: 0 });
      const t2 = makeTrade({ id: "b", qty: 0 });
      let state = reducer(initialState, setActiveTrades([t1, t2]));
      state = reducer(state, updateUnrealizedPnl(payload()));
      expect(state.activeTrades["a"].unrealized_pnl).toBeCloseTo(50);
      expect(state.activeTrades["b"].unrealized_pnl).toBeCloseTo(50);
    });

    it("is a no-op when no trades match", () => {
      const t1 = makeTrade({ id: "a", qty: 1 });
      let state = reducer(initialState, setActiveTrades([t1]));
      state = reducer(state, updateUnrealizedPnl(payload({ symbol: "ETHUSD" })));
      expect(state.activeTrades["a"].unrealized_pnl).toBeNull();
    });
  });

  describe("pending actions & optimistic updates", () => {
    it("startPendingAction sets optimistic status and snapshot", () => {
      const t = makeTrade({ id: "t1", status: "open" });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      expect(state.activeTrades["t1"].status).toBe("closing");
      expect(state.optimisticSnapshots["t1"].status).toBe("open");
      expect(state.pendingActions["t1"].action).toBe("closing");
    });

    it("clearPendingAction removes pending and snapshot", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "closing" }));
      state = reducer(state, clearPendingAction("t1"));
      expect(state.pendingActions["t1"]).toBeUndefined();
      expect(state.optimisticSnapshots["t1"]).toBeUndefined();
    });

    it("revertOptimisticUpdate restores snapshot", () => {
      const t = makeTrade({ id: "t1", status: "open" });
      let state = reducer(initialState, addActiveTrade(t));
      state = reducer(state, startPendingAction({ trade_id: "t1", action: "cancelling" }));
      expect(state.activeTrades["t1"].status).toBe("cancelling");
      state = reducer(state, revertOptimisticUpdate("t1"));
      expect(state.activeTrades["t1"].status).toBe("open");
      expect(state.pendingActions["t1"]).toBeUndefined();
    });
  });

  describe("setWsConnected", () => {
    it("sets wsConnected flag", () => {
      const state = reducer(initialState, setWsConnected(true));
      expect(state.wsConnected).toBe(true);
      const state2 = reducer(state, setWsConnected(false));
      expect(state2.wsConnected).toBe(false);
    });
  });

  describe("setIsFetchingActiveTrades", () => {
    it("sets fetching flag", () => {
      const state = reducer(initialState, setIsFetchingActiveTrades(true));
      expect(state.isFetchingActiveTrades).toBe(true);
    });
  });

  describe("UI state reducers", () => {
    it("setActiveTab", () => {
      const state = reducer(initialState, setActiveTab("history"));
      expect(state.activeTab).toBe("history");
    });

    it("setFilters merges partial filters", () => {
      const state = reducer(initialState, setFilters({ symbol: "ETHUSD" }));
      expect(state.filters.symbol).toBe("ETHUSD");
      expect(state.filters.side).toBe(""); // unchanged
    });

    it("setSortColumn / setSortDirection", () => {
      let state = reducer(initialState, setSortColumn("symbol"));
      expect(state.sortColumn).toBe("symbol");
      state = reducer(state, setSortDirection("asc"));
      expect(state.sortDirection).toBe("asc");
    });

    it("setSelectedTrade sets both trade and id", () => {
      const t = makeTrade({ id: "t1" });
      const state = reducer(initialState, setSelectedTrade(t));
      expect(state.selectedTrade).toEqual(t);
      expect(state.selectedTradeId).toBe("t1");
    });

    it("setSelectedTrade(null) clears both", () => {
      const t = makeTrade({ id: "t1" });
      let state = reducer(initialState, setSelectedTrade(t));
      state = reducer(state, setSelectedTrade(null));
      expect(state.selectedTrade).toBeNull();
      expect(state.selectedTradeId).toBeNull();
    });

    it("setPendingCloseAll toggles", () => {
      let state = reducer(initialState, setPendingCloseAll({ account_id: "acc1", pending: true }));
      expect(state.pendingCloseAll["acc1"]).toBe(true);
      state = reducer(state, setPendingCloseAll({ account_id: "acc1", pending: false }));
      expect(state.pendingCloseAll["acc1"]).toBeUndefined();
    });

    it("setLastUpdated", () => {
      const state = reducer(initialState, setLastUpdated(123456));
      expect(state.lastUpdated).toBe(123456);
    });
  });

  describe("updateUnrealizedPnl", () => {
    it("updates matching trades by account/symbol/side", () => {
      const t1 = makeTrade({ id: "a", account_id: "acc1", symbol: "BTCUSD", side: "long" });
      const t2 = makeTrade({ id: "b", account_id: "acc1", symbol: "BTCUSD", side: "short" });
      let state = reducer(initialState, setActiveTrades([t1, t2]));
      state = reducer(state, updateUnrealizedPnl({ account_id: "acc1", symbol: "BTCUSD", side: "long", unrealized_pnl: 500 }));
      expect(state.activeTrades["a"].unrealized_pnl).toBe(500);
      expect(state.activeTrades["b"].unrealized_pnl).toBeNull();
    });
  });
});
