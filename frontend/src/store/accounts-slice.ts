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
};

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
    setAccounts(state, action: PayloadAction<TradingAccount[]>) {
      state.accounts = action.payload;
      state.status = "success";
      state.error = null;
    },
    setDashboard(state, action: PayloadAction<DashboardCard[]>) {
      state.dashboard = action.payload;
      state.status = "success";
      state.error = null;
    },
    setLoading(state) {
      state.status = "loading";
    },
    setError(state, action: PayloadAction<string>) {
      state.status = "error";
      state.error = action.payload;
    },
    setFilterType(state, action: PayloadAction<"all" | "demo" | "live">) {
      state.filterType = action.payload;
    },
    setSelectedAccount(state, action: PayloadAction<string | null>) {
      state.selectedAccountId = action.payload;
    },
    setPollingInterval(state, action: PayloadAction<number>) {
      state.pollingIntervalMs = action.payload;
    },
    recordManualRefresh(state, action: PayloadAction<string>) {
      state.lastManualRefresh[action.payload] = Date.now();
    },
    addAccount(state, action: PayloadAction<TradingAccount>) {
      state.accounts.unshift(action.payload);
    },
    removeAccount(state, action: PayloadAction<string>) {
      state.accounts = state.accounts.filter((a) => a.id !== action.payload);
      state.dashboard = state.dashboard.filter((d) => d.id !== action.payload);
      delete state.directions[action.payload];
    },
    updateAccountInList(state, action: PayloadAction<TradingAccount>) {
      const idx = state.accounts.findIndex((a) => a.id === action.payload.id);
      if (idx >= 0) state.accounts[idx] = action.payload;
    },
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
} = accountsSlice.actions;

export default accountsSlice.reducer;
