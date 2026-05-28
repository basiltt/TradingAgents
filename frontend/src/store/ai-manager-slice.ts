/**
 * Redux slice managing AI trading manager state per brokerage account.
 *
 * Stores status, config, decisions, performance metrics, and logs for each
 * account's autonomous trading agent. Real-time WebSocket events update
 * state via `onStateChange` and `onExecution` reducers.
 *
 * @module store/ai-manager-slice
 */
import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import type { PayloadAction } from "@reduxjs/toolkit";
import { aiManagerApi } from "@/api/client";

/** Runtime status snapshot of an AI manager instance for one account. */
export interface AIManagerStatus {
  enabled: boolean;
  state: string;
  last_analysis_at: string | null;
  circuit_breaker: { count: number; active: boolean };
  actions_today: number;
  budget_remaining: { actions: number; tokens: number };
  degradation_tier: number;
  kill_switch: boolean;
  emergency_ref_equity?: number | null;
  emergency_cooldown_until?: string | null;
  emergency_closed_symbols?: Record<string, string> | null;
  // Runtime telemetry
  daily_pnl?: {
    equity_at_start: number | null;
    realized_profit: number;
    realized_loss: number;
    net_pnl: number;
    loss_pct_used: number | null;
    profit_target_progress: number | null;
  } | null;
  token_budget?: { used: number; max: number; pct: number } | null;
  live_positions?: Array<{
    symbol: string;
    side: string;
    size: string;
    entry_price: string;
    current_upnl: number;
    peak_pnl: number;
    drawdown_from_peak: number;
    age_s: number | null;
  }> | null;
  current_equity?: number | null;
}

/** A single trading decision made by the AI manager, including outcome tracking. */
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

/** Aggregated win/loss performance metrics over a configurable time period. */
export interface AIManagerPerformance {
  period: string;
  total_decisions: number;
  wins: number;
  losses: number;
  win_rate: number;
  gross_profit: number;
  gross_loss: number;
  net_pnl: number;
  profit_factor: number;
}

/** Structured log entry from the AI manager's runtime logging system. */
export interface AIManagerLog {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  message: string;
  details: Record<string, unknown> | null;
}

// --- Dashboard Enhancement Types ---

export interface LLMCallEntry {
  id: number; call_id: string; evaluation_cycle_id: string;
  node_name: string; timestamp: string; model: string;
  input_tokens: number; output_tokens: number; latency_ms: number;
  success: boolean; urgency_tier: string; action_returned: string | null;
  confidence: number | null; reasoning_preview: string | null; attempt_number: number;
}

export interface CapabilityStatus {
  capability_key: string; display_name: string; enabled: boolean;
  status: "healthy" | "degraded" | "failed" | "disabled";
  last_triggered_at: string | null; trigger_count_session: number;
  next_trigger_condition: string; countdown_seconds: number | null; armed: boolean;
}

export interface MarketInsight {
  day_score: number | null; day_score_label: "good" | "neutral" | "caution" | "danger" | null;
  day_score_justification: string | null;
  latest_commentary: { id: number; generated_at: string; summary_text: string; regime_label: string; commentary_type: "template" | "llm"; } | null;
  regime: Record<string, unknown> | null; session: string | null;
  correlation_heat: number | null;
  active_sweeps: Array<{ symbol: string; confidence: number; direction: string }>;
  positions_health: Array<{ symbol: string; health_score: number; concern: string | null }>;
}

export interface AttentionItem {
  id: string; severity: "critical" | "warning" | "info";
  title: string; description: string; timestamp: string; source: string; dismissed: boolean;
}

interface AIManagerState {
  statusByAccount: Record<string, AIManagerStatus | null>;
  configByAccount: Record<string, Record<string, unknown> | null>;
  decisionsByAccount: Record<string, AIManagerDecision[]>;
  decisionCursors: Record<string, string | null>;
  performanceByAccount: Record<string, AIManagerPerformance | null>;
  logsByAccount: Record<string, AIManagerLog[]>;
  logCursors: Record<string, number | null>;
  loading: Record<string, boolean>;
  error: string | null;
  // Dashboard enhancement
  llmCallsByAccount: Record<string, LLMCallEntry[]>;
  llmCallCursors: Record<string, string | null>;
  inFlightCalls: Record<string, string[]>;
  capabilitiesByAccount: Record<string, CapabilityStatus[]>;
  insightsByAccount: Record<string, MarketInsight | null>;
  attentionByAccount: Record<string, AttentionItem[]>;
}

const AI_MGR_STATE = { SLEEPING: "sleeping", PAUSED: "paused", MONITORING: "monitoring" } as const;

// AI-CONTEXT: Cap collections to prevent unbounded memory growth in long-running sessions.
// Decisions arrive via polling; logs via polling with cursor. Both append-only.
const MAX_DECISIONS = 500;
const MAX_LOGS = 1000;

function isHttpError(e: unknown, status: number): boolean {
  return !!e && typeof e === "object" && "status" in e && (e as { status: number }).status === status;
}

/**
 * Creates a default AIManagerStatus with sensible zero-state values.
 * Used when a WebSocket event references an account before the full status fetch completes.
 */
function createDefaultStatus(overrides?: Partial<AIManagerStatus>): AIManagerStatus {
  return {
    enabled: true,
    state: AI_MGR_STATE.SLEEPING,
    last_analysis_at: null,
    circuit_breaker: { count: 0, active: false },
    actions_today: 0,
    budget_remaining: { actions: 30, tokens: 100000 },
    degradation_tier: 0,
    kill_switch: false,
    ...overrides,
  } as AIManagerStatus;
}

const initialState: AIManagerState = {
  statusByAccount: {},
  configByAccount: {},
  decisionsByAccount: {},
  decisionCursors: {},
  performanceByAccount: {},
  logsByAccount: {},
  logCursors: {},
  loading: {},
  error: null,
  // Dashboard enhancement
  llmCallsByAccount: {},
  llmCallCursors: {},
  inFlightCalls: {},
  capabilitiesByAccount: {},
  insightsByAccount: {},
  attentionByAccount: {},
};

/** Enables the AI manager for the given account via the backend API. */
export const enableAIManager = createAsyncThunk(
  "aiManager/enable",
  async (accountId: string) => {
    await aiManagerApi.enable(accountId);
    return { accountId };
  },
);

/** Disables the AI manager, halting all autonomous trading for the account. */
export const disableAIManager = createAsyncThunk(
  "aiManager/disable",
  async (accountId: string) => {
    await aiManagerApi.disable(accountId);
    return { accountId };
  },
);

/** Fetches the current AI manager status for an account. Returns null on 404 (not configured). */
export const fetchAIManagerStatus = createAsyncThunk(
  "aiManager/fetchStatus",
  async (accountId: string) => {
    try {
      const data = await aiManagerApi.getStatus(accountId);
      return { accountId, data: data as unknown as AIManagerStatus };
    } catch (e: unknown) {
      if (isHttpError(e, 404)) {
        return { accountId, data: null };
      }
      throw e;
    }
  },
);

/** Patches AI manager configuration (risk params, schedule, etc.) for an account. */
export const patchAIManagerConfig = createAsyncThunk(
  "aiManager/patchConfig",
  async ({ accountId, updates }: { accountId: string; updates: Record<string, unknown> }) => {
    await aiManagerApi.patchConfig(accountId, updates);
    return { accountId };
  },
);

/** Fetches the full AI manager configuration for an account. Returns null on 404. */
export const fetchConfig = createAsyncThunk(
  "aiManager/fetchConfig",
  async (accountId: string) => {
    try {
      const data = await aiManagerApi.getConfig(accountId);
      return { accountId, data };
    } catch (e: unknown) {
      if (isHttpError(e, 404)) {
        return { accountId, data: null };
      }
      throw e;
    }
  },
);

/** Pauses the AI manager — it stops analyzing but retains state for resume. */
export const pauseAIManager = createAsyncThunk(
  "aiManager/pause",
  async (accountId: string) => {
    await aiManagerApi.pause(accountId);
    return { accountId };
  },
);

/** Resumes a paused AI manager, transitioning back to monitoring state. */
export const resumeAIManager = createAsyncThunk(
  "aiManager/resume",
  async (accountId: string) => {
    await aiManagerApi.resume(accountId);
    return { accountId };
  },
);

/** Activates the kill switch for a single account — immediately halts all trading. */
export const killAIManager = createAsyncThunk(
  "aiManager/kill",
  async (accountId: string) => {
    await aiManagerApi.kill(accountId);
    return { accountId };
  },
);

/** Resets the kill switch, allowing the AI manager to resume normal operations. */
export const resetKillSwitch = createAsyncThunk(
  "aiManager/resetKill",
  async (accountId: string) => {
    await aiManagerApi.resetKill(accountId);
    return { accountId };
  },
);

/** Fetches paginated trading decisions. Supports cursor-based pagination and append mode. */
export const fetchDecisions = createAsyncThunk(
  "aiManager/fetchDecisions",
  async ({ accountId, limit = 50, cursor, append = false }: { accountId: string; limit?: number; cursor?: string | null; append?: boolean }) => {
    const result = await aiManagerApi.getDecisions(accountId, { limit, cursor: cursor || undefined });
    return { accountId, decisions: result.decisions as AIManagerDecision[], nextCursor: result.next_cursor, append };
  },
);

/** Fetches aggregated performance stats for the given time period (default "7d"). */
export const fetchPerformance = createAsyncThunk(
  "aiManager/fetchPerformance",
  async ({ accountId, period = "7d" }: { accountId: string; period?: string }) => {
    const data = await aiManagerApi.getPerformance(accountId, period);
    return { accountId, data: data as unknown as AIManagerPerformance };
  },
);

/** Activates the global kill switch across ALL accounts. */
export const globalKill = createAsyncThunk(
  "aiManager/globalKill",
  async () => {
    await aiManagerApi.globalKill();
  },
);

/** Fetches paginated runtime logs with optional level/category filters. */
export const fetchLogs = createAsyncThunk(
  "aiManager/fetchLogs",
  async ({ accountId, limit = 100, level, category, cursor, append = false }: {
    accountId: string; limit?: number; level?: string; category?: string; cursor?: number | null; append?: boolean;
  }) => {
    const result = await aiManagerApi.getLogs(accountId, { limit, level, category, cursor: cursor || undefined });
    return { accountId, logs: result.logs as AIManagerLog[], nextCursor: result.next_cursor, append };
  },
);

// --- Dashboard Enhancement Thunks ---

export const fetchLLMCalls = createAsyncThunk(
  "aiManager/fetchLLMCalls",
  async ({ accountId, limit = 50, cursor, append = false }: {
    accountId: string; limit?: number; cursor?: string | null; append?: boolean;
  }) => {
    const data = await aiManagerApi.getLLMCalls(accountId, { limit, cursor: cursor ?? undefined });
    return { accountId, calls: data.calls as LLMCallEntry[], nextCursor: data.next_cursor, append };
  },
);

export const fetchCapabilities = createAsyncThunk(
  "aiManager/fetchCapabilities",
  async (accountId: string) => {
    const data = await aiManagerApi.getCapabilities(accountId);
    return { accountId, data: data as { capabilities: CapabilityStatus[] } };
  },
);

export const fetchInsights = createAsyncThunk(
  "aiManager/fetchInsights",
  async (accountId: string) => {
    const data = await aiManagerApi.getInsights(accountId);
    return { accountId, data: data as unknown as MarketInsight };
  },
);

const aiManagerSlice = createSlice({
  name: "aiManager",
  initialState,
  reducers: {
    /** Handles FSM state-change events from WebSocket. Creates a stub entry for unknown-but-enabled accounts so UI reflects state before fetchStatus completes. Forces state to "sleeping" when enabled=false. */
    onStateChange(state, action: PayloadAction<{ account_id: string; state: string; enabled: boolean }>) {
      const { account_id, state: fsmState, enabled } = action.payload;
      const existing = state.statusByAccount[account_id];
      if (existing) {
        existing.state = enabled ? fsmState : AI_MGR_STATE.SLEEPING;
        existing.enabled = enabled;
      }
      // If not yet in store, create a stub so the UI reflects the state immediately
      // before the fetchAIManagerStatus call completes
      if (!existing && enabled) {
        state.statusByAccount[account_id] = createDefaultStatus({ state: fsmState });
      }
    },
    /** Increments actions_today and decrements budget on trade execution. No-ops for unknown accounts. Budget clamped to 0 minimum. */
    onExecution(state, action: PayloadAction<{ account_id: string; action: string; symbol: string; pnl: number }>) {
      const { account_id } = action.payload;
      const existing = state.statusByAccount[account_id];
      if (existing) {
        existing.actions_today += 1;
        existing.budget_remaining.actions = Math.max(0, existing.budget_remaining.actions - 1);
      }
    },
    /** Clears the slice-level error field after it has been displayed or handled. */
    clearError(state) {
      state.error = null;
    },
    // --- Dashboard Enhancement Reducers ---
    onLLMStarted(state, action: PayloadAction<{ account_id: string; call_id: string }>) {
      const { account_id, call_id } = action.payload;
      if (!state.inFlightCalls[account_id]) state.inFlightCalls[account_id] = [];
      state.inFlightCalls[account_id].push(call_id);
    },
    onLLMCompleted(state, action: PayloadAction<LLMCallEntry & { account_id: string }>) {
      const { account_id, ...entry } = action.payload;
      state.inFlightCalls[account_id] = (state.inFlightCalls[account_id] || []).filter(id => id !== entry.call_id);
      if (!state.llmCallsByAccount[account_id]) state.llmCallsByAccount[account_id] = [];
      state.llmCallsByAccount[account_id].unshift(entry);
      if (state.llmCallsByAccount[account_id].length > 200) {
        state.llmCallsByAccount[account_id].pop();
      }
    },
    onCapabilityUpdate(state, action: PayloadAction<{ account_id: string; capability_key: string; new_status: string }>) {
      const caps = state.capabilitiesByAccount[action.payload.account_id];
      if (caps) {
        const cap = caps.find(c => c.capability_key === action.payload.capability_key);
        if (cap) cap.status = action.payload.new_status as CapabilityStatus["status"];
      }
    },
    onMarketCommentary(state, action: PayloadAction<{ account_id: string; day_score: number | null; day_score_label: string | null; summary_text: string; regime: string; generated_at: string }>) {
      const { account_id, ...data } = action.payload;
      if (!state.insightsByAccount[account_id]) {
        state.insightsByAccount[account_id] = {
          day_score: data.day_score, day_score_label: data.day_score_label as MarketInsight["day_score_label"],
          day_score_justification: null,
          latest_commentary: { id: 0, generated_at: data.generated_at, summary_text: data.summary_text, regime_label: data.regime, commentary_type: "template" },
          regime: null, session: null, correlation_heat: null, active_sweeps: [], positions_health: [],
        };
        return;
      }
      const insight = state.insightsByAccount[account_id]!;
      insight.day_score = data.day_score;
      insight.day_score_label = data.day_score_label as MarketInsight["day_score_label"];
      if (insight.latest_commentary) {
        insight.latest_commentary.summary_text = data.summary_text;
        insight.latest_commentary.generated_at = data.generated_at;
      } else {
        insight.latest_commentary = { id: 0, generated_at: data.generated_at, summary_text: data.summary_text, regime_label: data.regime, commentary_type: "template" };
      }
    },
    addAttentionItem(state, action: PayloadAction<AttentionItem & { account_id: string }>) {
      const { account_id, ...item } = action.payload;
      if (!state.attentionByAccount[account_id]) state.attentionByAccount[account_id] = [];
      state.attentionByAccount[account_id].unshift(item);
      if (state.attentionByAccount[account_id].length > 50) state.attentionByAccount[account_id].pop();
    },
    dismissAttentionItem(state, action: PayloadAction<{ account_id: string; item_id: string }>) {
      const items = state.attentionByAccount[action.payload.account_id];
      if (items) {
        const item = items.find(i => i.id === action.payload.item_id);
        if (item) item.dismissed = true;
      }
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
        // Don't overwrite a WS-created stub with null (404 race condition)
        if (action.payload.data === null && state.statusByAccount[action.payload.accountId] != null) {
          return;
        }
        state.statusByAccount[action.payload.accountId] = action.payload.data;
      })
      .addCase(fetchAIManagerStatus.rejected, setError("status"))

      .addCase(enableAIManager.pending, setLoading("enable"))
      .addCase(enableAIManager.fulfilled, (state, action) => {
        state.loading["enable"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) {
          s.enabled = true;
        } else {
          state.statusByAccount[action.payload.accountId] = createDefaultStatus();
        }
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
        if (s) s.state = AI_MGR_STATE.PAUSED;
      })
      .addCase(pauseAIManager.rejected, setError("pause"))

      .addCase(resumeAIManager.pending, setLoading("resume"))
      .addCase(resumeAIManager.fulfilled, (state, action) => {
        state.loading["resume"] = false;
        const s = state.statusByAccount[action.payload.accountId];
        if (s) s.state = AI_MGR_STATE.MONITORING;
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

      .addCase(patchAIManagerConfig.pending, setLoading("patchConfig"))
      .addCase(patchAIManagerConfig.fulfilled, clearLoading("patchConfig"))
      .addCase(patchAIManagerConfig.rejected, setError("patchConfig"))

      .addCase(fetchConfig.pending, setLoading("fetchConfig"))
      .addCase(fetchConfig.fulfilled, (state, action) => {
        state.loading["fetchConfig"] = false;
        state.configByAccount[action.payload.accountId] = action.payload.data ?? null;
      })
      .addCase(fetchConfig.rejected, setError("fetchConfig"))

      .addCase(fetchDecisions.pending, setLoading("decisions"))
      .addCase(fetchDecisions.fulfilled, (state, action) => {
        state.loading["decisions"] = false;
        const { accountId, decisions, nextCursor, append } = action.payload;
        if (append) {
          const combined = [...(state.decisionsByAccount[accountId] || []), ...decisions];
          state.decisionsByAccount[accountId] = combined.slice(-MAX_DECISIONS);
        } else {
          state.decisionsByAccount[accountId] = decisions.slice(-MAX_DECISIONS);
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
      .addCase(globalKill.rejected, setError("globalKill"))

      .addCase(fetchLogs.pending, setLoading("logs"))
      .addCase(fetchLogs.fulfilled, (state, action) => {
        state.loading["logs"] = false;
        const { accountId, logs, nextCursor, append } = action.payload;
        if (append) {
          const combined = [...(state.logsByAccount[accountId] || []), ...logs];
          state.logsByAccount[accountId] = combined.slice(-MAX_LOGS);
        } else {
          state.logsByAccount[accountId] = logs.slice(-MAX_LOGS);
        }
        state.logCursors[accountId] = nextCursor;
      })
      .addCase(fetchLogs.rejected, setError("logs"))

      // Dashboard enhancement (rejections clear loading but don't set global error)
      .addCase(fetchLLMCalls.pending, setLoading("llmCalls"))
      .addCase(fetchLLMCalls.fulfilled, (state, action) => {
        state.loading["llmCalls"] = false;
        const { accountId, calls, nextCursor, append } = action.payload;
        if (append) {
          const combined = [...(state.llmCallsByAccount[accountId] || []), ...calls];
          state.llmCallsByAccount[accountId] = combined.slice(0, 200);
        } else {
          state.llmCallsByAccount[accountId] = calls.slice(0, 200);
        }
        state.llmCallCursors[accountId] = nextCursor;
      })
      .addCase(fetchLLMCalls.rejected, clearLoading("llmCalls"))

      .addCase(fetchCapabilities.pending, setLoading("capabilities"))
      .addCase(fetchCapabilities.fulfilled, (state, action) => {
        state.loading["capabilities"] = false;
        state.capabilitiesByAccount[action.payload.accountId] = action.payload.data.capabilities;
      })
      .addCase(fetchCapabilities.rejected, clearLoading("capabilities"))

      .addCase(fetchInsights.pending, setLoading("insights"))
      .addCase(fetchInsights.fulfilled, (state, action) => {
        state.loading["insights"] = false;
        state.insightsByAccount[action.payload.accountId] = action.payload.data;
      })
      .addCase(fetchInsights.rejected, clearLoading("insights"));
  },
});

export const { onStateChange, onExecution, clearError, onLLMStarted, onLLMCompleted, onCapabilityUpdate, onMarketCommentary, addAttentionItem, dismissAttentionItem } = aiManagerSlice.actions;
export default aiManagerSlice.reducer;
