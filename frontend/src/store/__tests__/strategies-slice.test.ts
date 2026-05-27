import { describe, it, expect } from "vitest";
import reducer, {
  setLoading,
  setStrategies,
  setError,
  setFilterStatus,
  setFilterCategory,
  setSearchQuery,
  addStrategy,
  updateStrategy,
  removeStrategy,
} from "../strategies-slice";
import type { Strategy } from "@/api/client";

const mockStrategy = (id: string, name = "Strat"): Strategy => ({
  id,
  name,
  description: "desc",
  status: "active",
  category: "scalping",
  config: {},
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
});

describe("strategies-slice", () => {
  const initial = reducer(undefined, { type: "@@INIT" });

  it("has correct initial state", () => {
    expect(initial.strategies).toEqual([]);
    expect(initial.status).toBe("idle");
    expect(initial.error).toBeNull();
    expect(initial.filterStatus).toBe("all");
    expect(initial.filterCategory).toBe("all");
    expect(initial.searchQuery).toBe("");
  });

  it("setLoading transitions to loading and clears error", () => {
    const state = reducer({ ...initial, error: "old error" }, setLoading());
    expect(state.status).toBe("loading");
    expect(state.error).toBeNull();
  });

  it("setStrategies replaces the list and sets success", () => {
    const strats = [mockStrategy("1"), mockStrategy("2")];
    const state = reducer(initial, setStrategies(strats));
    expect(state.strategies).toHaveLength(2);
    expect(state.status).toBe("success");
  });

  it("setError records message and sets error status", () => {
    const state = reducer(initial, setError("Network failed"));
    expect(state.status).toBe("error");
    expect(state.error).toBe("Network failed");
  });

  it("setFilterStatus updates filter", () => {
    const state = reducer(initial, setFilterStatus("paused"));
    expect(state.filterStatus).toBe("paused");
  });

  it("setFilterCategory updates filter", () => {
    const state = reducer(initial, setFilterCategory("swing"));
    expect(state.filterCategory).toBe("swing");
  });

  it("setSearchQuery updates query", () => {
    const state = reducer(initial, setSearchQuery("momentum"));
    expect(state.searchQuery).toBe("momentum");
  });

  it("addStrategy prepends to list", () => {
    const withOne = reducer(initial, setStrategies([mockStrategy("1")]));
    const state = reducer(withOne, addStrategy(mockStrategy("2", "New")));
    expect(state.strategies[0].id).toBe("2");
    expect(state.strategies).toHaveLength(2);
  });

  it("updateStrategy replaces by ID match", () => {
    const withOne = reducer(initial, setStrategies([mockStrategy("1", "Old")]));
    const updated = { ...mockStrategy("1", "New"), description: "updated" };
    const state = reducer(withOne, updateStrategy(updated));
    expect(state.strategies[0].name).toBe("New");
    expect(state.strategies[0].description).toBe("updated");
  });

  it("updateStrategy is no-op when ID not found", () => {
    const withOne = reducer(initial, setStrategies([mockStrategy("1")]));
    const state = reducer(withOne, updateStrategy(mockStrategy("999")));
    expect(state.strategies).toHaveLength(1);
    expect(state.strategies[0].id).toBe("1");
  });

  it("removeStrategy removes by ID", () => {
    const withTwo = reducer(initial, setStrategies([mockStrategy("1"), mockStrategy("2")]));
    const state = reducer(withTwo, removeStrategy("1"));
    expect(state.strategies).toHaveLength(1);
    expect(state.strategies[0].id).toBe("2");
  });

  it("removeStrategy is no-op for non-existent ID", () => {
    const withOne = reducer(initial, setStrategies([mockStrategy("1")]));
    const state = reducer(withOne, removeStrategy("999"));
    expect(state.strategies).toHaveLength(1);
  });
});
