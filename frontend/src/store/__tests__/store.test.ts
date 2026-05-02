import { describe, it, expect } from "vitest";
import { store } from "../index";

describe("Redux store", () => {
  it("has analysis slice with initial state", () => {
    const state = store.getState();
    expect(state.analysis).toBeDefined();
    expect(state.analysis.activeRuns).toEqual({});
  });

  it("has ui slice with initial state", () => {
    const state = store.getState();
    expect(state.ui).toBeDefined();
    expect(state.ui.sidebarOpen).toBe(true);
    expect(state.ui.theme).toBe("system");
  });
});
