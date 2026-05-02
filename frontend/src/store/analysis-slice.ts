import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export interface ActiveRun {
  runId: string;
  ticker: string;
  status: string;
  progress: number;
  currentAgent?: string;
}

interface AnalysisState {
  activeRuns: Record<string, ActiveRun>;
}

const initialState: AnalysisState = {
  activeRuns: {},
};

export const analysisSlice = createSlice({
  name: "analysis",
  initialState,
  reducers: {
    setActiveRun(state, action: PayloadAction<ActiveRun>) {
      state.activeRuns[action.payload.runId] = action.payload;
    },
    updateRunStatus(
      state,
      action: PayloadAction<{ runId: string; status: string; progress?: number; currentAgent?: string }>,
    ) {
      const run = state.activeRuns[action.payload.runId];
      if (run) {
        run.status = action.payload.status;
        if (action.payload.progress !== undefined) run.progress = action.payload.progress;
        if (action.payload.currentAgent !== undefined) run.currentAgent = action.payload.currentAgent;
      }
    },
    removeActiveRun(state, action: PayloadAction<string>) {
      delete state.activeRuns[action.payload];
    },
  },
});

export const { setActiveRun, updateRunStatus, removeActiveRun } = analysisSlice.actions;
