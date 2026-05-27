/**
 * @module analysis-slice
 *
 * Redux slice that manages the lifecycle of TradingAgents analysis runs in the
 * frontend. Responsibilities:
 *
 * - Tracks every in-flight run via the `activeRuns` map (keyed by `runId`).
 * - Accepts real-time progress updates pushed from the backend (via WebSocket or
 *   SSE) and merges them into the existing run record.
 * - Removes completed / cancelled runs from the map so the UI can react
 *   accordingly.
 *
 * This slice intentionally contains no async thunks; side-effects such as
 * polling or socket subscriptions live in the component layer and dispatch
 * these plain actions directly.
 */

import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

/**
 * Snapshot of a single analysis run that is currently active (queued, running,
 * or recently finished but not yet acknowledged by the UI).
 */
export interface ActiveRun {
  /** Unique identifier for the run, assigned by the backend on creation. */
  runId: string;

  /** Stock ticker symbol being analysed (e.g. "AAPL", "TSLA"). */
  ticker: string;

  /**
   * Human-readable status string sourced directly from the backend event
   * stream.  Common values: "queued", "running", "completed", "failed".
   * The slice does not validate or normalise this value.
   */
  status: string;

  /**
   * Completion percentage in the range [0, 100].  Updated incrementally as
   * the backend emits agent-progress events.
   */
  progress: number;

  /**
   * Name of the agent that is currently executing within the run pipeline.
   * Optional because it is only present while an agent is actively running.
   */
  currentAgent?: string;
}

/**
 * Shape of the Redux state owned by this slice.
 *
 * @internal — consumers should rely on typed selectors rather than accessing
 * `state.analysis` directly.
 */
interface AnalysisState {
  /**
   * Map of `runId → ActiveRun` for every run that is currently being tracked.
   * Using a Record (dictionary) instead of an array provides O(1) look-ups by
   * `runId`, which is the dominant access pattern for real-time updates.
   *
   * AI-CONTEXT: The map is intentionally sparse; completed runs are removed via
   * `removeActiveRun` rather than kept with a terminal status, so any key
   * present here represents a run the UI should still render as active.
   */
  activeRuns: Record<string, ActiveRun>;
}

const initialState: AnalysisState = {
  activeRuns: {},
};

export const analysisSlice = createSlice({
  name: "analysis",
  initialState,
  reducers: {
    /**
     * Inserts or fully replaces an `ActiveRun` record in the store.
     *
     * Use this action when the backend confirms a new run has been created and
     * you have a complete `ActiveRun` object available.  Prefer
     * `updateRunStatus` for incremental field-level updates on an existing run.
     *
     * @param action - Payload is the full `ActiveRun` object to upsert.
     *
     * @example
     * dispatch(setActiveRun({ runId: "abc123", ticker: "AAPL", status: "queued", progress: 0 }));
     */
    setActiveRun(state, action: PayloadAction<ActiveRun>) {
      state.activeRuns[action.payload.runId] = action.payload;
    },

    /**
     * Merges a partial status update into an existing run.  If the run is not
     * yet present in the store (e.g. the status event arrived before the
     * creation acknowledgement), a minimal placeholder record is created so
     * updates are never silently dropped.
     *
     * @param action.payload.runId       - Target run identifier.
     * @param action.payload.status      - New status string.
     * @param action.payload.progress    - Optional updated progress value (0–100).
     * @param action.payload.currentAgent - Optional name of the currently active agent.
     *
     * AI-CONTEXT: The fallback branch (`else`) handles an out-of-order delivery
     * scenario — the progress event can arrive over a WebSocket before the HTTP
     * response that contains the full `ActiveRun` shape.  The placeholder uses
     * an empty string for `ticker` which will be overwritten once `setActiveRun`
     * is dispatched with the full record.
     *
     * @example
     * dispatch(updateRunStatus({ runId: "abc123", status: "running", progress: 42, currentAgent: "FundamentalsAgent" }));
     */
    updateRunStatus(
      state,
      action: PayloadAction<{ runId: string; status: string; progress?: number; currentAgent?: string }>,
    ) {
      const { runId, status, progress, currentAgent } = action.payload;
      const run = state.activeRuns[runId];
      if (run) {
        // AI-CONTEXT: Only overwrite optional fields when they are explicitly
        // provided; `undefined` means "no change", not "clear the field".
        run.status = status;
        if (progress !== undefined) run.progress = progress;
        if (currentAgent !== undefined) run.currentAgent = currentAgent;
      } else {
        state.activeRuns[runId] = { runId, ticker: "", status, progress: progress ?? 0, currentAgent };
      }
    },

    /**
     * Removes a run from the active-runs map.
     *
     * Dispatch this action after a run reaches a terminal state ("completed" or
     * "failed") and the UI has finished presenting any completion feedback.
     * After removal the run will no longer appear in any selector that reads
     * from `activeRuns`.
     *
     * @param action - Payload is the `runId` string of the run to remove.
     *
     * @example
     * dispatch(removeActiveRun("abc123"));
     */
    removeActiveRun(state, action: PayloadAction<string>) {
      delete state.activeRuns[action.payload];
    },
  },
});

/**
 * Exported action creators for the analysis slice.
 *
 * - `setActiveRun`    — upsert a complete run record.
 * - `updateRunStatus` — merge a partial status/progress update into a run.
 * - `removeActiveRun` — delete a run from the active-runs map by its ID.
 */
export const { setActiveRun, updateRunStatus, removeActiveRun } = analysisSlice.actions;
