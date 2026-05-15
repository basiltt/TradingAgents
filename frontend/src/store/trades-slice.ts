import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Trade, TradeFilters } from "@/components/trades/types";

interface TradesState {
  activeTrades: Record<string, Trade>;
  activeTab: "active" | "history";
  filters: TradeFilters;
  sortColumn: string;
  sortDirection: "asc" | "desc";
  selectedTradeId: string | null;
  closeModalTradeId: string | null;
  pendingActions: Record<string, "closing" | "cancelling">;
  pendingCloseAll: Record<string, boolean>;
  optimisticSnapshots: Record<string, Trade>;
  isFetchingActiveTrades: boolean;
  wsConnected: boolean;
  lastUpdated: number | null;
}

const initialState: TradesState = {
  activeTrades: {},
  activeTab: "active",
  filters: {
    account_ids: [],
    status: [],
    symbol: "",
    side: "",
    from_date: "",
    to_date: "",
  },
  sortColumn: "created_at",
  sortDirection: "desc",
  selectedTradeId: null,
  closeModalTradeId: null,
  pendingActions: {},
  pendingCloseAll: {},
  optimisticSnapshots: {},
  isFetchingActiveTrades: false,
  wsConnected: false,
  lastUpdated: null,
};

const tradesSlice = createSlice({
  name: "trades",
  initialState,
  reducers: {
    setActiveTrades(state, action: PayloadAction<Trade[]>) {
      state.activeTrades = {};
      for (const t of action.payload) {
        state.activeTrades[t.id] = t;
      }
      state.lastUpdated = Date.now();
    },
    addActiveTrade(state, action: PayloadAction<Trade>) {
      state.activeTrades[action.payload.id] = action.payload;
      state.lastUpdated = Date.now();
    },
    updateActiveTrade(
      state,
      action: PayloadAction<{ trade_id: string; updates: Partial<Trade> }>,
    ) {
      const { trade_id, updates } = action.payload;
      const existing = state.activeTrades[trade_id];
      if (!existing) return;
      if (state.pendingActions[trade_id]) return;
      if (
        updates.version !== undefined &&
        existing.version !== undefined &&
        updates.version <= existing.version
      ) {
        return;
      }
      state.activeTrades[trade_id] = { ...existing, ...updates };
      state.lastUpdated = Date.now();
    },
    removeActiveTrade(state, action: PayloadAction<string>) {
      delete state.activeTrades[action.payload];
      delete state.optimisticSnapshots[action.payload];
      state.lastUpdated = Date.now();
    },
    setActiveTab(state, action: PayloadAction<"active" | "history">) {
      state.activeTab = action.payload;
    },
    setFilters(state, action: PayloadAction<Partial<TradeFilters>>) {
      state.filters = { ...state.filters, ...action.payload };
    },
    setSortColumn(state, action: PayloadAction<string>) {
      state.sortColumn = action.payload;
    },
    setSortDirection(state, action: PayloadAction<"asc" | "desc">) {
      state.sortDirection = action.payload;
    },
    setSelectedTradeId(state, action: PayloadAction<string | null>) {
      state.selectedTradeId = action.payload;
    },
    setCloseModalTradeId(state, action: PayloadAction<string | null>) {
      state.closeModalTradeId = action.payload;
    },
    startPendingAction(
      state,
      action: PayloadAction<{ trade_id: string; action: "closing" | "cancelling" }>,
    ) {
      const { trade_id, action: act } = action.payload;
      const trade = state.activeTrades[trade_id];
      if (trade) {
        state.optimisticSnapshots[trade_id] = { ...trade };
        state.activeTrades[trade_id] = { ...trade, status: act === "closing" ? "closing" : "cancelling" };
      }
      state.pendingActions[trade_id] = act;
    },
    clearPendingAction(state, action: PayloadAction<string>) {
      delete state.pendingActions[action.payload];
      delete state.optimisticSnapshots[action.payload];
    },
    revertOptimisticUpdate(state, action: PayloadAction<string>) {
      const snapshot = state.optimisticSnapshots[action.payload];
      if (snapshot) {
        state.activeTrades[action.payload] = snapshot;
      }
      delete state.optimisticSnapshots[action.payload];
      delete state.pendingActions[action.payload];
    },
    setPendingCloseAll(
      state,
      action: PayloadAction<{ account_id: string; pending: boolean }>,
    ) {
      if (action.payload.pending) {
        state.pendingCloseAll[action.payload.account_id] = true;
      } else {
        delete state.pendingCloseAll[action.payload.account_id];
      }
    },
    bulkRemoveActiveTrades(state, action: PayloadAction<string[]>) {
      for (const id of action.payload) {
        delete state.activeTrades[id];
        delete state.optimisticSnapshots[id];
      }
      state.lastUpdated = Date.now();
    },
    setIsFetchingActiveTrades(state, action: PayloadAction<boolean>) {
      state.isFetchingActiveTrades = action.payload;
    },
    setWsConnected(state, action: PayloadAction<boolean>) {
      state.wsConnected = action.payload;
    },
    setLastUpdated(state, action: PayloadAction<number>) {
      state.lastUpdated = action.payload;
    },
  },
});

export const {
  setActiveTrades,
  addActiveTrade,
  updateActiveTrade,
  removeActiveTrade,
  setActiveTab,
  setFilters,
  setSortColumn,
  setSortDirection,
  setSelectedTradeId,
  setCloseModalTradeId,
  startPendingAction,
  clearPendingAction,
  revertOptimisticUpdate,
  setPendingCloseAll,
  bulkRemoveActiveTrades,
  setIsFetchingActiveTrades,
  setWsConnected,
  setLastUpdated,
} = tradesSlice.actions;

export default tradesSlice.reducer;
