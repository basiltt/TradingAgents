import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { DashboardCard, TradingAccount } from "@/api/client";

interface AccountsState {
  accounts: TradingAccount[];
  dashboard: DashboardCard[];
  status: "idle" | "loading" | "success" | "error";
  error: string | null;
  filterType: "all" | "demo" | "live";
  selectedAccountId: string | null;
  pollingIntervalMs: number;
  lastManualRefresh: Record<string, number>;
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
};

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
    },
    updateAccountInList(state, action: PayloadAction<TradingAccount>) {
      const idx = state.accounts.findIndex((a) => a.id === action.payload.id);
      if (idx >= 0) state.accounts[idx] = action.payload;
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
} = accountsSlice.actions;

export default accountsSlice.reducer;
