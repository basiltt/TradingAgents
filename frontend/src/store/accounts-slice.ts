/**
 * Redux slice for trading accounts dashboard state.
 *
 * Manages account list, dashboard cards, real-time WebSocket updates,
 * and filter/loading UI state. updateCardRealtime handles live equity/PnL
 * updates by matching account_id and merging partial data.
 */
import { createSlice } from "@reduxjs/toolkit";
import type { PayloadAction } from "@reduxjs/toolkit";
import type { DashboardCard, TradingAccount } from "@/api/client";

export type Direction = "up" | "down" | "neutral";

interface RealtimeEvent {
  account_id: string;
  type: string;
  data: Record<string, string>;
}

interface AccountsState {
  accounts: TradingAccount[];
  dashboard: DashboardCard[];
  status: "idle" | "loading" | "success" | "error";
  error: string | null;
  filterType: "all" | "demo" | "live";
  selectedAccountId: string | null;
  pollingIntervalMs: number;
  lastManualRefresh: Record<string, number>;
  directions: Record<string, Record<string, Direction>>;
  closeExecutionSeq: number;
}

const initialState: AccountsState = {
  accounts: [],
  dashboard: [],
  status: "idle",
  error: null,
  filterType: "all",
  selectedAccountId: null,
  pollingIntervalMs: 60000,
  lastManualRefresh: {},
  directions: {},
  closeExecutionSeq: 0,
};

/** Compare old/new numeric strings and return trend direction for UI arrows. */
function getDirection(oldVal: string | undefined, newVal: string): Direction {
  const o = parseFloat(oldVal || "0");
  const n = parseFloat(newVal);
  if (isNaN(o) || isNaN(n) || n === o) return "neutral";
  return n > o ? "up" : "down";
}

const accountsSlice = createSlice({
  name: "accounts",
  initialState,
  reducers: {
    /** Replace accounts list from API response. */
    setAccounts(state, action: PayloadAction<TradingAccount[]>) {
      state.accounts = action.payload;
      state.status = "success";
      state.error = null;
    },
    /** Replace dashboard cards from API response. */
    setDashboard(state, action: PayloadAction<DashboardCard[]>) {
      state.dashboard = action.payload;
      state.status = "success";
      state.error = null;
    },
    /** Set loading status. */
    setLoading(state) {
      state.status = "loading";
    },
    /** Set error status with message. */
    setError(state, action: PayloadAction<string>) {
      state.status = "error";
      state.error = action.payload;
    },
    /** Set dashboard filter (all/demo/live). */
    setFilterType(state, action: PayloadAction<"all" | "demo" | "live">) {
      state.filterType = action.payload;
    },
    /** Select an account by ID for detail view. */
    setSelectedAccount(state, action: PayloadAction<string | null>) {
      state.selectedAccountId = action.payload;
    },
    /** Configure polling interval in milliseconds. */
    setPollingInterval(state, action: PayloadAction<number>) {
      state.pollingIntervalMs = action.payload;
    },
    /** Record timestamp of last manual refresh for an account. */
    recordManualRefresh(state, action: PayloadAction<string>) {
      state.lastManualRefresh[action.payload] = Date.now();
    },
    /** Prepend a newly created account. */
    addAccount(state, action: PayloadAction<TradingAccount>) {
      state.accounts.unshift(action.payload);
    },
    /** Remove an account from both lists and direction cache. */
    removeAccount(state, action: PayloadAction<string>) {
      state.accounts = state.accounts.filter((a) => a.id !== action.payload);
      state.dashboard = state.dashboard.filter((d) => d.id !== action.payload);
      delete state.directions[action.payload];
    },
    /** Replace an account in the list after update. */
    updateAccountInList(state, action: PayloadAction<TradingAccount>) {
      const idx = state.accounts.findIndex((a) => a.id === action.payload.id);
      if (idx >= 0) state.accounts[idx] = action.payload;
    },
    /** Apply real-time wallet/position WebSocket event to a dashboard card. */
    updateCardRealtime(state, action: PayloadAction<RealtimeEvent>) {
      const { account_id, type, data } = action.payload;
      const idx = state.dashboard.findIndex((d) => d.id === account_id);
      if (idx < 0) return;

      const card = state.dashboard[idx];
      const dirs: Record<string, Direction> = state.directions[account_id] || {};

      if (type === "wallet_update") {
        if (data.totalEquity) {
          dirs.equity = getDirection(card.total_equity, data.totalEquity);
          card.total_equity = data.totalEquity;
        }
        if (data.totalPerpUPL) {
          dirs.pnl = getDirection(card.total_perp_upl, data.totalPerpUPL);
          card.total_perp_upl = data.totalPerpUPL;
        }
      } else if (type === "position_update") {
        if (data.unrealisedPnl) {
          dirs.pnl = getDirection(card.total_perp_upl, data.unrealisedPnl);
          card.total_perp_upl = data.unrealisedPnl;
        }
      }

      state.directions[account_id] = dirs;
    },
    /** Decrement position count after a close-all execution completes. */
    handleCloseExecution(state, action: PayloadAction<{ account_id: string; data: { closed: number } }>) {
      const { account_id, data } = action.payload;
      const idx = state.dashboard.findIndex((d) => d.id === account_id);
      if (idx < 0) return;
      const card = state.dashboard[idx];
      const closed = typeof data?.closed === "number" ? data.closed : 0;
      card.positions_count = Math.max(0, card.positions_count - closed);
      state.closeExecutionSeq += 1;
    },
  },
});

export const {
  setAccounts,
  setDashboard,
  setLoading,
  setError,
  setFilterType,
  setSelectedAccount,
  setPollingInterval,
  recordManualRefresh,
  addAccount,
  removeAccount,
  updateAccountInList,
  updateCardRealtime,
  handleCloseExecution,
} = accountsSlice.actions;

export default accountsSlice.reducer;
