import { describe, it, expect } from "vitest";
import reducer, {
  onStateChange,
  onExecution,
  clearError,
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
