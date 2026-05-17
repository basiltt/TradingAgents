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

/** Tracks an in-flight mutation so server refreshes don't overwrite optimistic UI. */
interface PendingAction {
  action: "closing" | "cancelling";
  startedAt: number;
}

/** Auto-expire stale pending actions after 60s. */
const PENDING_ACTION_TTL_MS = 60_000;

interface TradesState {
  activeTrades: Record<string, Trade>;
  activeTab: "active" | "history";
  filters: TradeFilters;
  sortColumn: string;
  sortDirection: "asc" | "desc";
  selectedTradeId: string | null;
  selectedTrade: Trade | null;
  /** Trade ID for the close-confirmation modal, null when closed. */
  closeModalTradeId: string | null;
  /** In-flight close/cancel actions keyed by trade ID. */
  pendingActions: Record<string, PendingAction>;
  /** Per-account close-all in progress flags. */
  pendingCloseAll: Record<string, boolean>;
  /** Pre-mutation trade snapshots for rollback on failure. */
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
    /** Merge server trades with pending-action trades; expire stale pending actions. */
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
    /** Add or replace a trade, skipping if incoming version is stale. */
    addActiveTrade(state, action: PayloadAction<Trade>) {
      const existing = state.activeTrades[action.payload.id];
      if (existing && existing.version !== undefined && action.payload.version !== undefined && action.payload.version <= existing.version) {
        return;
      }
      state.activeTrades[action.payload.id] = action.payload;
      state.lastUpdated = Date.now();
    },
    /** Partially update a trade; skipped if a pending action guards it or version is stale. */
    updateActiveTrade(
      state,
      action: PayloadAction<{ trade_id: string; updates: Partial<Trade>; accumulatePnl?: number }>,
    ) {
      const { trade_id, updates, accumulatePnl } = action.payload;
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
      const merged = { ...existing, ...updates };
      if (accumulatePnl !== undefined) {
        merged.realized_pnl = (existing.realized_pnl ?? 0) + accumulatePnl;
      }
      state.activeTrades[trade_id] = merged;
      state.lastUpdated = Date.now();
    },
    /** Remove a trade and clean up related selection/modal/snapshot state. */
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
    /** Switch between active and history tabs. */
    setActiveTab(state, action: PayloadAction<"active" | "history">) {
      state.activeTab = action.payload;
    },
    /** Merge partial filter updates into current filters. */
    setFilters(state, action: PayloadAction<Partial<TradeFilters>>) {
      state.filters = { ...state.filters, ...action.payload };
    },
    /** Set the column used for trade list sorting. */
    setSortColumn(state, action: PayloadAction<string>) {
      state.sortColumn = action.payload;
    },
    /** Set sort direction (asc/desc). */
    setSortDirection(state, action: PayloadAction<"asc" | "desc">) {
      state.sortDirection = action.payload;
    },
    /** Select a trade by ID; clears detail when null. */
    setSelectedTradeId(state, action: PayloadAction<string | null>) {
      state.selectedTradeId = action.payload;
      if (!action.payload) state.selectedTrade = null;
    },
    /** Set the selected trade object and sync selectedTradeId. */
    setSelectedTrade(state, action: PayloadAction<Trade | null>) {
      state.selectedTrade = action.payload;
      state.selectedTradeId = action.payload?.id ?? null;
    },
    /** Set or clear the trade ID shown in the close-confirmation modal. */
    setCloseModalTradeId(state, action: PayloadAction<string | null>) {
      state.closeModalTradeId = action.payload;
    },
    /** Snapshot current trade state and apply optimistic status change. */
    startPendingAction(
      state,
      action: PayloadAction<{ trade_id: string; action: "closing" | "cancelling" }>,
    ) {
      const { trade_id, action: mutationType } = action.payload;
      const trade = state.activeTrades[trade_id];
      if (trade) {
        state.optimisticSnapshots[trade_id] = { ...trade };
        state.activeTrades[trade_id] = { ...trade, status: mutationType === "closing" ? "closing" : "cancelling" };
      }
      state.pendingActions[trade_id] = { action: mutationType, startedAt: Date.now() };
    },
    /** Clear pending action and snapshot after successful mutation. */
    clearPendingAction(state, action: PayloadAction<string>) {
      delete state.pendingActions[action.payload];
      delete state.optimisticSnapshots[action.payload];
    },
    /** Restore pre-mutation snapshot on mutation failure and clear pending state. */
    revertOptimisticUpdate(state, action: PayloadAction<string>) {
      const snapshot = state.optimisticSnapshots[action.payload];
      if (snapshot) {
        state.activeTrades[action.payload] = snapshot;
      }
      delete state.optimisticSnapshots[action.payload];
      delete state.pendingActions[action.payload];
    },
    /** Set or clear the close-all-in-progress flag for an account. */
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
    /** Remove multiple trades by ID array (e.g., after close-all completes). */
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
    /** Remove all trades belonging to a specific account. */
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
    /** Update unrealized PnL for all trades matching account/symbol/side from position data, distributed pro-rata by qty. */
    updateUnrealizedPnl(state, action: PayloadAction<{ account_id: string; symbol: string; side: string; unrealized_pnl: number }>) {
      const { account_id, symbol, side, unrealized_pnl } = action.payload;
      const matchIds: string[] = [];
      let totalQty = 0;
      for (const [id, trade] of Object.entries(state.activeTrades)) {
        if (trade.account_id === account_id && trade.symbol === symbol && trade.side === side) {
          matchIds.push(id);
          totalQty += parseFloat(String(trade.qty ?? 0));
        }
      }
      if (matchIds.length === 0) return;
      for (const id of matchIds) {
        const trade = state.activeTrades[id];
        const newPnl = totalQty > 0
          ? unrealized_pnl * (parseFloat(String(trade.qty ?? 0)) / totalQty)
          : unrealized_pnl / matchIds.length;
        if (Math.abs((trade.unrealized_pnl ?? 0) - newPnl) > 0.0001) {
          trade.unrealized_pnl = newPnl;
        }
      }
    },
    /** Set loading state for active trades fetch. */
    setIsFetchingActiveTrades(state, action: PayloadAction<boolean>) {
      state.isFetchingActiveTrades = action.payload;
    },
    /** Track WebSocket connection status. */
    setWsConnected(state, action: PayloadAction<boolean>) {
      state.wsConnected = action.payload;
    },
    /** Record timestamp of last data update. */
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
