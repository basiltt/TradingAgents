import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Strategy, StrategyStatus, StrategyCategory } from "@/api/client";

interface StrategiesState {
  strategies: Strategy[];
  status: "idle" | "loading" | "success" | "error";
  error: string | null;
  filterStatus: StrategyStatus | "all";
  filterCategory: StrategyCategory | "all";
  searchQuery: string;
}

const initialState: StrategiesState = {
  strategies: [],
  status: "idle",
  error: null,
  filterStatus: "all",
  filterCategory: "all",
  searchQuery: "",
};

const strategiesSlice = createSlice({
  name: "strategies",
  initialState,
  reducers: {
    setLoading(state) {
      state.status = "loading";
      state.error = null;
    },
    setStrategies(state, action: PayloadAction<Strategy[]>) {
      state.strategies = action.payload;
      state.status = "success";
      state.error = null;
    },
    setError(state, action: PayloadAction<string>) {
      state.status = "error";
      state.error = action.payload;
    },
    setFilterStatus(state, action: PayloadAction<StrategyStatus | "all">) {
      state.filterStatus = action.payload;
    },
    setFilterCategory(state, action: PayloadAction<StrategyCategory | "all">) {
      state.filterCategory = action.payload;
    },
    setSearchQuery(state, action: PayloadAction<string>) {
      state.searchQuery = action.payload;
    },
    addStrategy(state, action: PayloadAction<Strategy>) {
      state.strategies.unshift(action.payload);
    },
    updateStrategy(state, action: PayloadAction<Strategy>) {
      const idx = state.strategies.findIndex((s) => s.id === action.payload.id);
      if (idx >= 0) state.strategies[idx] = action.payload;
    },
    removeStrategy(state, action: PayloadAction<string>) {
      state.strategies = state.strategies.filter((s) => s.id !== action.payload);
    },
  },
});

export const {
  setLoading,
  setStrategies,
  setError,
  setFilterStatus,
  setFilterCategory,
  setSearchQuery,
  addStrategy,
  updateStrategy,
  removeStrategy,
} = strategiesSlice.actions;

export default strategiesSlice.reducer;
