import { describe, it, expect } from "vitest";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice, setActiveRun, updateRunStatus, removeActiveRun } from "../analysis-slice";
import { uiSlice, toggleSidebar, setSidebarOpen, setTheme } from "../ui-slice";

function createTestStore() {
  return configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
}

describe("Redux store", () => {
  it("has analysis slice with initial state", () => {
    const store = createTestStore();
    expect(store.getState().analysis.activeRuns).toEqual({});
  });

  it("has ui slice with initial state", () => {
    const store = createTestStore();
    expect(store.getState().ui.sidebarOpen).toBe(false);
    expect(store.getState().ui.theme).toBe("system");
  });
});

describe("analysis slice reducers", () => {
  it("setActiveRun adds a run", () => {
    const store = createTestStore();
    store.dispatch(setActiveRun({ runId: "r1", ticker: "SPY", status: "running", progress: 0 }));
    expect(store.getState().analysis.activeRuns["r1"]).toBeDefined();
    expect(store.getState().analysis.activeRuns["r1"].ticker).toBe("SPY");
  });

  it("updateRunStatus updates existing run", () => {
    const store = createTestStore();
    store.dispatch(setActiveRun({ runId: "r1", ticker: "SPY", status: "running", progress: 0 }));
    store.dispatch(updateRunStatus({ runId: "r1", status: "running", progress: 50, currentAgent: "market" }));
    expect(store.getState().analysis.activeRuns["r1"].progress).toBe(50);
    expect(store.getState().analysis.activeRuns["r1"].currentAgent).toBe("market");
  });

  it("updateRunStatus is no-op for unknown run", () => {
    const store = createTestStore();
    store.dispatch(updateRunStatus({ runId: "unknown", status: "running" }));
    expect(store.getState().analysis.activeRuns).toEqual({});
  });

  it("updateRunStatus preserves terminal status runs for UI display", () => {
    const store = createTestStore();
    store.dispatch(setActiveRun({ runId: "r1", ticker: "SPY", status: "running", progress: 0 }));
    store.dispatch(updateRunStatus({ runId: "r1", status: "completed" }));
    expect(store.getState().analysis.activeRuns["r1"]).toBeDefined();
    expect(store.getState().analysis.activeRuns["r1"].status).toBe("completed");
  });

  it("removeActiveRun removes a run", () => {
    const store = createTestStore();
    store.dispatch(setActiveRun({ runId: "r1", ticker: "SPY", status: "running", progress: 0 }));
    store.dispatch(removeActiveRun("r1"));
    expect(store.getState().analysis.activeRuns["r1"]).toBeUndefined();
  });
});

describe("ui slice reducers", () => {
  it("toggleSidebar toggles state", () => {
    const store = createTestStore();
    expect(store.getState().ui.sidebarOpen).toBe(false);
    store.dispatch(toggleSidebar());
    expect(store.getState().ui.sidebarOpen).toBe(true);
    store.dispatch(toggleSidebar());
    expect(store.getState().ui.sidebarOpen).toBe(false);
  });

  it("setSidebarOpen sets explicit value", () => {
    const store = createTestStore();
    store.dispatch(setSidebarOpen(true));
    expect(store.getState().ui.sidebarOpen).toBe(true);
  });

  it("setTheme changes theme", () => {
    const store = createTestStore();
    store.dispatch(setTheme("dark"));
    expect(store.getState().ui.theme).toBe("dark");
  });
});
