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
      const { runId, status, progress, currentAgent } = action.payload;
      const run = state.activeRuns[runId];
      if (run) {
        run.status = status;
        if (progress !== undefined) run.progress = progress;
        if (currentAgent !== undefined) run.currentAgent = currentAgent;
      } else {
        state.activeRuns[runId] = { runId, ticker: "", status, progress: progress ?? 0, currentAgent };
      }
    },
    removeActiveRun(state, action: PayloadAction<string>) {
      delete state.activeRuns[action.payload];
    },
  },
});

export const { setActiveRun, updateRunStatus, removeActiveRun } = analysisSlice.actions;
