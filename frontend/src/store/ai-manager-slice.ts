import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import type { PayloadAction } from "@reduxjs/toolkit";
import { aiManagerApi } from "@/api/client";

export interface AIManagerStatus {
  enabled: boolean;
  state: string;
  last_analysis_at: string | null;
  circuit_breaker: { count: number; active: boolean };
  actions_today: number;
  budget_remaining: { actions: number; tokens: number };
  degradation_tier: number;
  kill_switch: boolean;
}

export interface AIManagerDecision {
  id: number;
  timestamp: string;
  action_taken: { action: string; symbol: string };
  confidence: number;
  reasoning: string;
  urgency: string;
  execution_result: Record<string, unknown> | null;
  outcome: Record<string, unknown> | null;
  outcome_label: string | null;
}

export interface AIManagerPerformance {
  period: string;
  total_decisions: number;
  successful: number;
  failed: number;
  total_pnl: number;
  win_rate: number;
}

interface AIManagerState {
  statusByAccount: Record<string, AIManagerStatus | null>;
  decisionsbyAccount: Record<string, AIManagerDecision[]>;
  decisionCursors: Record<string, string | null>;
  performanceByAccount: Record<string, AIManagerPerformance | null>;
  loading: Record<string, boolean>;
  error: string | null;
}

const initialState: AIManagerState = {
  statusByAccount: {},
  decisionsbyAccount: {},
  decisionCursors: {},
  performanceByAccount: {},
  loading: {},
  error: null,
};

export const enableAIManager = createAsyncThunk(
  "aiManager/enable",
  async (accountId: string) => {
    await aiManagerApi.enable(accountId);
    return { accountId };
  },
);

export const disableAIManager = createAsyncThunk(
  "aiManager/disable",
  async (accountId: string) => {
    await aiManagerApi.disable(accountId);
    return { accountId };
  },
);

export const fetchAIManagerStatus = createAsyncThunk(
  "aiManager/fetchStatus",
  async (accountId: string) => {
    try {
      const data = await aiManagerApi.getStatus(accountId);
      return { accountId, data: data as unknown as AIManagerStatus };
    } catch (e: unknown) {
      if (e && typeof e === "object" && "status" in e && (e as { status: number }).status === 404) {
        return { accountId, data: null };
      }
      throw e;
    }
  },
);

export const patchAIManagerConfig = createAsyncThunk(
  "aiManager/patchConfig",
  async ({ accountId, updates }: { accountId: string; updates: Record<string, unknown> }) => {
    await aiManagerApi.patchConfig(accountId, updates);
    return { accountId };
  },
);

export const pauseAIManager = createAsyncThunk(
  "aiManager/pause",
  async (accountId: string) => {
    await aiManagerApi.pause(accountId);
    return { accountId };
  },
);

export const resumeAIManager = createAsyncThunk(
  "aiManager/resume",
  async (accountId: string) => {
    await aiManagerApi.resume(accountId);
    return { accountId };
  },
);

export const killAIManager = createAsyncThunk(
  "aiManager/kill",
  async (accountId: string) => {
    await aiManagerApi.kill(accountId);
    return { accountId };
  },
);

export const resetKillSwitch = createAsyncThunk(
  "aiManager/resetKill",
  async (accountId: string) => {
    await aiManagerApi.resetKill(accountId);
    return { accountId };
  },
);

export const fetchDecisions = createAsyncThunk(
  "aiManager/fetchDecisions",
  async ({ accountId, limit = 50, cursor, append = false }: { accountId: string; limit?: number; cursor?: string | null; append?: boolean }) => {
    const result = await aiManagerApi.getDecisions(accountId, { limit, cursor: cursor || undefined });
    return { accountId, decisions: result.decisions as AIManagerDecision[], nextCursor: result.next_cursor, append };
  },
);

export const fetchPerformance = createAsyncThunk(
  "aiManager/fetchPerformance",
  async ({ accountId, period = "7d" }: { accountId: string; period?: string }) => {
    const data = await aiManagerApi.getPerformance(accountId, period);
    return { accountId, data: data as unknown as AIManagerPerformance };
  },
);

export const globalKill = createAsyncThunk(
  "aiManager/globalKill",
  async () => {
    await aiManagerApi.globalKill();
  },
);

const aiManagerSlice = createSlice({
  name: "aiManager",
  initialState,
  reducers: {
    onStateChange(state, action: PayloadAction<{ account_id: string; state: string; enabled: boolean }>) {
      const { account_id, state: fsmState, enabled } = action.payload;
      const existing = state.statusByAccount[account_id];
      if (existing) {
        existing.state = fsmState;
        existing.enabled = enabled;
      }
    },
    onExecution(state, action: PayloadAction<{ account_id: string; action: string; symbol: string; pnl: number }>) {
      const { account_id } = action.payload;
      const existing = state.statusByAccount[account_id];
      if (existing) {
        existing.actions_today += 1;
        existing.budget_remaining.actions -= 1;
      }
    },
    clearError(state) {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    const setLoading = (key: string) => (state: AIManagerState) => {
      state.loading[key] = true;
      state.error = null;
    };
    const clearLoading = (key: string) => (state: AIManagerState) => {
      state.loading[key] = false;
    };
    const setError = (key: string) => (state: AIManagerState, action: { error: { message?: string } }) => {
      state.loading[key] = false;
      state.error = action.error.message || "Unknown error";
    };

    builder
      .addCase(fetchAIManagerStatus.pending, setLoading("status"))
      .addCase(fetchAIManagerStatus.fulfilled, (state, action) => {
        state.loading["status"] = false;
        state.statusByAccount[action.payload.accountId] = action.payload.data;
      })
      .addCase(fetchAIManagerStatus.rejected, setError("status"))

      .addCase(enableAIManager.pending, setLoading("enable"))
      .addCase(enableAIManager.fulfilled, (state, action) => {
        state.loading["enable"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.enabled = true;
      })
      .addCase(enableAIManager.rejected, setError("enable"))

      .addCase(disableAIManager.pending, setLoading("disable"))
      .addCase(disableAIManager.fulfilled, (state, action) => {
        state.loading["disable"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.enabled = false;
      })
      .addCase(disableAIManager.rejected, setError("disable"))

      .addCase(pauseAIManager.pending, setLoading("pause"))
      .addCase(pauseAIManager.fulfilled, (state, action) => {
        state.loading["pause"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.state = "paused";
      })
      .addCase(pauseAIManager.rejected, setError("pause"))

      .addCase(resumeAIManager.pending, setLoading("resume"))
      .addCase(resumeAIManager.fulfilled, (state, action) => {
        state.loading["resume"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.state = "monitoring";
      })
      .addCase(resumeAIManager.rejected, setError("resume"))

      .addCase(killAIManager.pending, setLoading("kill"))
      .addCase(killAIManager.fulfilled, (state, action) => {
        state.loading["kill"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.kill_switch = true;
      })
      .addCase(killAIManager.rejected, setError("kill"))

      .addCase(resetKillSwitch.pending, setLoading("resetKill"))
      .addCase(resetKillSwitch.fulfilled, (state, action) => {
        state.loading["resetKill"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.kill_switch = false;
      })
      .addCase(resetKillSwitch.rejected, setError("resetKill"))

      .addCase(patchAIManagerConfig.pending, setLoading("config"))
      .addCase(patchAIManagerConfig.fulfilled, clearLoading("config"))
      .addCase(patchAIManagerConfig.rejected, setError("config"))

      .addCase(fetchDecisions.pending, setLoading("decisions"))
      .addCase(fetchDecisions.fulfilled, (state, action) => {
        state.loading["decisions"] = false;
        const { accountId, decisions, nextCursor, append } = action.payload;
        if (append) {
          state.decisionsbyAccount[accountId] = [...(state.decisionsbyAccount[accountId] || []), ...decisions];
        } else {
          state.decisionsbyAccount[accountId] = decisions;
        }
        state.decisionCursors[accountId] = nextCursor;
      })
      .addCase(fetchDecisions.rejected, setError("decisions"))

      .addCase(fetchPerformance.pending, setLoading("performance"))
      .addCase(fetchPerformance.fulfilled, (state, action) => {
        state.loading["performance"] = false;
        state.performanceByAccount[action.payload.accountId] = action.payload.data;
      })
      .addCase(fetchPerformance.rejected, setError("performance"))

      .addCase(globalKill.pending, setLoading("globalKill"))
      .addCase(globalKill.fulfilled, (state) => {
        state.loading["globalKill"] = false;
        for (const s of Object.values(state.statusByAccount)) {
          if (s) s.kill_switch = true;
        }
      })
      .addCase(globalKill.rejected, setError("globalKill"));
  },
});

export const { onStateChange, onExecution, clearError } = aiManagerSlice.actions;
export default aiManagerSlice.reducer;
