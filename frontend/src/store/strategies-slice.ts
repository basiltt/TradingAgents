/**
 * Redux slice managing trading strategies — list, filters, and CRUD operations.
 *
 * Strategies are prepended on creation (newest first) and filtered client-side
 * by status, category, and search query.
 *
 * @module store/strategies-slice
 */
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
    /** Transitions to loading state, clearing any prior error. */
    setLoading(state) {
      state.status = "loading";
      state.error = null;
    },
    /** Replaces the full strategy list from an API response. */
    setStrategies(state, action: PayloadAction<Strategy[]>) {
      state.strategies = action.payload;
      state.status = "success";
      state.error = null;
    },
    /** Records a fetch/mutation error message. */
    setError(state, action: PayloadAction<string>) {
      state.status = "error";
      state.error = action.payload;
    },
    /** Sets the active status filter for client-side list filtering. */
    setFilterStatus(state, action: PayloadAction<StrategyStatus | "all">) {
      state.filterStatus = action.payload;
    },
    /** Sets the active category filter for client-side list filtering. */
    setFilterCategory(state, action: PayloadAction<StrategyCategory | "all">) {
      state.filterCategory = action.payload;
    },
    /** Sets the search query string for client-side name/description filtering. */
    setSearchQuery(state, action: PayloadAction<string>) {
      state.searchQuery = action.payload;
    },
    /** Prepends a newly created strategy to the list (newest first). */
    addStrategy(state, action: PayloadAction<Strategy>) {
      state.strategies.unshift(action.payload);
    },
    /** Replaces a strategy in-place by ID match. */
    updateStrategy(state, action: PayloadAction<Strategy>) {
      const idx = state.strategies.findIndex((s) => s.id === action.payload.id);
      if (idx >= 0) state.strategies[idx] = action.payload;
    },
    /** Removes a strategy by ID. */
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
