/**
 * Redux slice for active trade management with optimistic updates.
 *
 * Trades are keyed by ID in a Record for O(1) lookup. Optimistic updates
 * (closing/cancelling) snapshot the pre-mutation state so it can be reverted
 * on failure. Pending actions have a TTL to auto-expire stale operations.
 *
 * AI-CONTEXT: setActiveTrades merges server data with pending-action trades
 * to prevent optimistic UI from being overwritten by stale server responses.
 */
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Trade, TradeFilters } from "@/components/trades/types";

interface PendingAction {
  action: "closing" | "cancelling";
  startedAt: number;
}

const PENDING_ACTION_TTL_MS = 60_000;

interface TradesState {
  activeTrades: Record<string, Trade>;
  activeTab: "active" | "history";
  filters: TradeFilters;
  sortColumn: string;
  sortDirection: "asc" | "desc";
  selectedTradeId: string | null;
  selectedTrade: Trade | null;
  closeModalTradeId: string | null;
  pendingActions: Record<string, PendingAction>;
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
  selectedTrade: null,
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
      const now = Date.now();
      // Expire stale pending actions
      for (const [id, pa] of Object.entries(state.pendingActions)) {
        if (now - pa.startedAt > PENDING_ACTION_TTL_MS) {
          delete state.pendingActions[id];
          delete state.optimisticSnapshots[id];
        }
      }
      const next: Record<string, Trade> = {};
      for (const t of action.payload) {
        if (state.pendingActions[t.id]) {
          next[t.id] = state.activeTrades[t.id] ?? t;
        } else {
          next[t.id] = t;
        }
      }
      for (const id of Object.keys(state.pendingActions)) {
        if (!next[id] && state.activeTrades[id]) {
          next[id] = state.activeTrades[id];
        }
      }
      state.activeTrades = next;
      state.lastUpdated = now;
    },
    addActiveTrade(state, action: PayloadAction<Trade>) {
      const existing = state.activeTrades[action.payload.id];
      if (existing && existing.version !== undefined && action.payload.version !== undefined && action.payload.version <= existing.version) {
        return;
      }
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
      if (state.selectedTradeId === action.payload) {
        state.selectedTradeId = null;
        state.selectedTrade = null;
      }
      if (state.closeModalTradeId === action.payload) state.closeModalTradeId = null;
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
      if (!action.payload) state.selectedTrade = null;
    },
    setSelectedTrade(state, action: PayloadAction<Trade | null>) {
      state.selectedTrade = action.payload;
      state.selectedTradeId = action.payload?.id ?? null;
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
      state.pendingActions[trade_id] = { action: act, startedAt: Date.now() };
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
      const ids = new Set(action.payload);
      for (const id of ids) {
        delete state.activeTrades[id];
        delete state.optimisticSnapshots[id];
      }
      if (state.selectedTradeId && ids.has(state.selectedTradeId)) {
        state.selectedTradeId = null;
        state.selectedTrade = null;
      }
      if (state.closeModalTradeId && ids.has(state.closeModalTradeId)) state.closeModalTradeId = null;
      state.lastUpdated = Date.now();
    },
    removeActiveTradesByAccount(state, action: PayloadAction<string>) {
      const accountId = action.payload;
      const idsToRemove: string[] = [];
      for (const [id, trade] of Object.entries(state.activeTrades)) {
        if (trade.account_id === accountId) idsToRemove.push(id);
      }
      for (const id of idsToRemove) {
        delete state.activeTrades[id];
        delete state.optimisticSnapshots[id];
      }
      if (state.selectedTradeId && idsToRemove.includes(state.selectedTradeId)) {
        state.selectedTradeId = null;
        state.selectedTrade = null;
      }
      if (state.closeModalTradeId && idsToRemove.includes(state.closeModalTradeId)) state.closeModalTradeId = null;
      state.lastUpdated = Date.now();
    },
    updateUnrealizedPnl(state, action: PayloadAction<{ account_id: string; symbol: string; side: string; unrealized_pnl: number }>) {
      const { account_id, symbol, side, unrealized_pnl } = action.payload;
      for (const trade of Object.values(state.activeTrades)) {
        if (trade.account_id === account_id && trade.symbol === symbol && trade.side === side) {
          trade.unrealized_pnl = unrealized_pnl;
        }
      }
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
} = tradesSlice.actions;

export default tradesSlice.reducer;
