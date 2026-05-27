import { describe, it, expect } from "vitest";
import { analysisSlice, setActiveRun, updateRunStatus, removeActiveRun } from "@/store/analysis-slice";

const reducer = analysisSlice.reducer;

describe("analysis-slice", () => {
  const initial = reducer(undefined, { type: "@@INIT" });

  it("starts with empty activeRuns", () => {
    expect(initial.activeRuns).toEqual({});
  });

  it("setActiveRun inserts a run", () => {
    const run = { runId: "r1", ticker: "AAPL", status: "queued", progress: 0 };
    const state = reducer(initial, setActiveRun(run));
    expect(state.activeRuns["r1"]).toEqual(run);
  });

  it("setActiveRun overwrites existing run", () => {
    const run1 = { runId: "r1", ticker: "AAPL", status: "queued", progress: 0 };
    const run2 = { runId: "r1", ticker: "AAPL", status: "running", progress: 50 };
    let state = reducer(initial, setActiveRun(run1));
    state = reducer(state, setActiveRun(run2));
    expect(state.activeRuns["r1"].status).toBe("running");
    expect(state.activeRuns["r1"].progress).toBe(50);
  });

  it("updateRunStatus updates existing run fields", () => {
    const run = { runId: "r1", ticker: "AAPL", status: "queued", progress: 0 };
    let state = reducer(initial, setActiveRun(run));
    state = reducer(state, updateRunStatus({ runId: "r1", status: "running", progress: 42, currentAgent: "FundAgent" }));
    expect(state.activeRuns["r1"].status).toBe("running");
    expect(state.activeRuns["r1"].progress).toBe(42);
    expect(state.activeRuns["r1"].currentAgent).toBe("FundAgent");
  });

  it("updateRunStatus does not overwrite progress when undefined", () => {
    const run = { runId: "r1", ticker: "AAPL", status: "running", progress: 50 };
    let state = reducer(initial, setActiveRun(run));
    state = reducer(state, updateRunStatus({ runId: "r1", status: "running" }));
    expect(state.activeRuns["r1"].progress).toBe(50);
  });

  it("updateRunStatus creates placeholder for unknown run", () => {
    const state = reducer(initial, updateRunStatus({ runId: "new", status: "running", progress: 10 }));
    expect(state.activeRuns["new"]).toEqual({ runId: "new", ticker: "", status: "running", progress: 10, currentAgent: undefined });
  });

  it("removeActiveRun deletes a run", () => {
    const run = { runId: "r1", ticker: "AAPL", status: "completed", progress: 100 };
    let state = reducer(initial, setActiveRun(run));
    state = reducer(state, removeActiveRun("r1"));
    expect(state.activeRuns["r1"]).toBeUndefined();
  });
});
