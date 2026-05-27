import { describe, it, expect } from "vitest";
import { uiSlice, toggleSidebar, setSidebarOpen, setTheme, setPalette, setContrast } from "../ui-slice";

const reducer = uiSlice.reducer;

describe("ui-slice", () => {
  const initial = reducer(undefined, { type: "@@INIT" });

  it("has sidebar closed by default", () => {
    expect(initial.sidebarOpen).toBe(false);
  });

  it("toggleSidebar flips state", () => {
    const opened = reducer(initial, toggleSidebar());
    expect(opened.sidebarOpen).toBe(true);
    const closed = reducer(opened, toggleSidebar());
    expect(closed.sidebarOpen).toBe(false);
  });

  it("setSidebarOpen sets explicitly", () => {
    const state = reducer(initial, setSidebarOpen(true));
    expect(state.sidebarOpen).toBe(true);
    const closed = reducer(state, setSidebarOpen(false));
    expect(closed.sidebarOpen).toBe(false);
  });

  it("setTheme updates theme", () => {
    const state = reducer(initial, setTheme("dark"));
    expect(state.theme).toBe("dark");
    const light = reducer(state, setTheme("light"));
    expect(light.theme).toBe("light");
  });

  it("setPalette updates palette", () => {
    const state = reducer(initial, setPalette("aurora"));
    expect(state.palette).toBe("aurora");
  });

  it("setContrast updates contrast", () => {
    const state = reducer(initial, setContrast("high"));
    expect(state.contrast).toBe("high");
  });
});
