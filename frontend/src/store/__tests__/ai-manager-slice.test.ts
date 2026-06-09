import { describe, it, expect } from "vitest";
import reducer, {
  onStateChange,
  onExecution,
  clearError,
  fetchDecisions,
  fetchLogs,
  fetchLLMCalls,
  globalKill,
} from "@/store/ai-manager-slice";

describe("aiManagerSlice reducer", () => {
  const initialState = reducer(undefined, { type: "@@INIT" });

  it("returns initial state", () => {
    expect(initialState.statusByAccount).toEqual({});
    expect(initialState.error).toBeNull();
  });

  it("onStateChange updates existing status", () => {
    const withStatus = {
      ...initialState,
      statusByAccount: {
        "acc-1": {
          enabled: true,
          state: "monitoring",
          last_analysis_at: null,
          circuit_breaker: { count: 0, active: false },
          actions_today: 5,
          budget_remaining: { actions: 25, tokens: 90000 },
          degradation_tier: 0,
          kill_switch: false,
        },
      },
    };
    const next = reducer(withStatus, onStateChange({ account_id: "acc-1", state: "paused", enabled: true }));
    expect(next.statusByAccount["acc-1"]!.state).toBe("paused");
  });

  it("onExecution increments actions_today", () => {
    const withStatus = {
      ...initialState,
      statusByAccount: {
        "acc-1": {
          enabled: true,
          state: "executing",
          last_analysis_at: null,
          circuit_breaker: { count: 0, active: false },
          actions_today: 3,
          budget_remaining: { actions: 27, tokens: 90000 },
          degradation_tier: 0,
          kill_switch: false,
        },
      },
    };
    const next = reducer(withStatus, onExecution({ account_id: "acc-1", action: "CLOSE", symbol: "BTCUSDT", pnl: 10 }));
    expect(next.statusByAccount["acc-1"]!.actions_today).toBe(4);
    expect(next.statusByAccount["acc-1"]!.budget_remaining.actions).toBe(26);
  });

  it("clearError resets error", () => {
    const withError = { ...initialState, error: "something broke" };
    const next = reducer(withError, clearError());
    expect(next.error).toBeNull();
  });

  it("onStateChange creates stub for unknown enabled account", () => {
    const next = reducer(initialState, onStateChange({ account_id: "nope", state: "paused", enabled: true }));
    expect(next.statusByAccount["nope"]).toBeDefined();
    expect(next.statusByAccount["nope"]!.state).toBe("paused");
    expect(next.statusByAccount["nope"]!.enabled).toBe(true);
  });

  it("onStateChange does nothing for unknown disabled account", () => {
    const next = reducer(initialState, onStateChange({ account_id: "nope", state: "paused", enabled: false }));
    expect(next.statusByAccount["nope"]).toBeUndefined();
  });
});

describe("aiManagerSlice truncation", () => {
  const initialState = reducer(undefined, { type: "@@INIT" });

  it("fetchDecisions.fulfilled truncates to MAX_DECISIONS (500) on append", () => {
    const existing = Array.from({ length: 490 }, (_, i) => ({ id: i, action_taken: { action: "HOLD", symbol: "BTC" }, confidence: 0.5, timestamp: "", reasoning: "", urgency: "low", execution_result: null, outcome: null, outcome_label: null }));
    const state = { ...initialState, decisionsByAccount: { "acc-1": existing } };
    const newDecisions = Array.from({ length: 20 }, (_, i) => ({ id: 500 + i, action_taken: { action: "BUY", symbol: "ETH" }, confidence: 0.8, timestamp: "", reasoning: "", urgency: "medium", execution_result: null, outcome: null, outcome_label: null }));

    const next = reducer(state, fetchDecisions.fulfilled({ accountId: "acc-1", decisions: newDecisions, nextCursor: null, append: true }, "", { accountId: "acc-1" }));
    expect(next.decisionsByAccount["acc-1"]).toHaveLength(500);
    expect(next.decisionsByAccount["acc-1"][499].id).toBe(519);
  });

  it("fetchLogs.fulfilled truncates to MAX_LOGS (1000) on append", () => {
    const existing = Array.from({ length: 990 }, (_, i) => ({ id: i, level: "info", message: `msg-${i}`, timestamp: "", category: "general", details: null }));
    const state = { ...initialState, logsByAccount: { "acc-1": existing } };
    const newLogs = Array.from({ length: 20 }, (_, i) => ({ id: 1000 + i, level: "warn", message: `new-${i}`, timestamp: "", category: "general", details: null }));

    const next = reducer(state, fetchLogs.fulfilled({ accountId: "acc-1", logs: newLogs, nextCursor: null, append: true }, "", { accountId: "acc-1", cursor: null }));
    expect(next.logsByAccount["acc-1"]).toHaveLength(1000);
    expect(next.logsByAccount["acc-1"][999].id).toBe(1019);
  });

  it("fetchLLMCalls.fulfilled append KEEPS older paginated entries (regression: was capped away at 200)", () => {
    // BUG GUARD: the feed is newest-first; "Load more" appends OLDER entries to the
    // tail. Previously the buffer was capped at 200, so appending the next page onto
    // an already-200 buffer kept only the existing newest 200 and silently discarded
    // every older page — "Load more" was a no-op. With the 1000 cap, the older page
    // must survive.
    const llmCall = (id: number) => ({
      id, call_id: `c${id}`, evaluation_cycle_id: "e1", node_name: "trader",
      timestamp: "", model: "x", input_tokens: 1, output_tokens: 1, latency_ms: 1,
      success: true, urgency_tier: "low", action_returned: null, confidence: null,
      reasoning_preview: null, attempt_number: 1,
    });
    const existing = Array.from({ length: 200 }, (_, i) => llmCall(i)); // newest 200
    const olderPage = Array.from({ length: 50 }, (_, i) => llmCall(1000 + i)); // older page
    const state = { ...initialState, llmCallsByAccount: { "acc-1": existing } };

    const next = reducer(
      state,
      fetchLLMCalls.fulfilled(
        { accountId: "acc-1", calls: olderPage, nextCursor: null, append: true },
        "",
        { accountId: "acc-1" },
      ),
    );
    // All 250 survive (200 existing + 50 older), not capped back to 200.
    expect(next.llmCallsByAccount["acc-1"]).toHaveLength(250);
    // The older page is appended at the tail (after the existing newest entries).
    expect(next.llmCallsByAccount["acc-1"][200].id).toBe(1000);
  });

  it("globalKill.fulfilled sets kill_switch on all accounts", () => {
    const state = {
      ...initialState,
      statusByAccount: {
        "a": { enabled: true, state: "monitoring", last_analysis_at: null, circuit_breaker: { count: 0, active: false }, actions_today: 0, budget_remaining: { actions: 30, tokens: 100000 }, degradation_tier: 0, kill_switch: false },
        "b": { enabled: true, state: "paused", last_analysis_at: null, circuit_breaker: { count: 0, active: false }, actions_today: 0, budget_remaining: { actions: 30, tokens: 100000 }, degradation_tier: 0, kill_switch: false },
      },
    };
    const next = reducer(state, globalKill.fulfilled(undefined, ""));
    expect(next.statusByAccount["a"]!.kill_switch).toBe(true);
    expect(next.statusByAccount["b"]!.kill_switch).toBe(true);
  });
});
