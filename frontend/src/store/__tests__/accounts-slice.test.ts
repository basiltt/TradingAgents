import { describe, it, expect } from "vitest";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer, {
  setAccounts,
  setDashboard,
  setLoading,
  setError,
  setFilterType,
  setSelectedAccount,
  addAccount,
  removeAccount,
  updateAccountInList,
  recordManualRefresh,
} from "../accounts-slice";

function createStore() {
  return configureStore({ reducer: { accounts: accountsReducer } });
}

describe("accounts-slice", () => {
  it("has correct initial state", () => {
    const store = createStore();
    const state = store.getState().accounts;
    expect(state.accounts).toEqual([]);
    expect(state.dashboard).toEqual([]);
    expect(state.status).toBe("idle");
    expect(state.error).toBeNull();
    expect(state.filterType).toBe("all");
    expect(state.selectedAccountId).toBeNull();
  });

  it("setLoading sets status to loading", () => {
    const store = createStore();
    store.dispatch(setLoading());
    expect(store.getState().accounts.status).toBe("loading");
  });

  it("setError sets error and status", () => {
    const store = createStore();
    store.dispatch(setError("Something failed"));
    expect(store.getState().accounts.status).toBe("error");
    expect(store.getState().accounts.error).toBe("Something failed");
  });

  it("setAccounts replaces accounts list", () => {
    const store = createStore();
    const accounts = [{ id: "1", label: "Test" }] as unknown as Parameters<typeof setAccounts>[0];
    store.dispatch(setAccounts(accounts));
    expect(store.getState().accounts.accounts).toEqual(accounts);
    expect(store.getState().accounts.status).toBe("success");
  });

  it("setDashboard replaces dashboard cards", () => {
    const store = createStore();
    const cards = [{ id: "1", status: "active" }] as unknown as Parameters<typeof setDashboard>[0];
    store.dispatch(setDashboard(cards));
    expect(store.getState().accounts.dashboard).toEqual(cards);
    expect(store.getState().accounts.status).toBe("success");
  });

  it("setFilterType changes filter", () => {
    const store = createStore();
    store.dispatch(setFilterType("live"));
    expect(store.getState().accounts.filterType).toBe("live");
  });

  it("setSelectedAccount sets accountId", () => {
    const store = createStore();
    store.dispatch(setSelectedAccount("abc-123"));
    expect(store.getState().accounts.selectedAccountId).toBe("abc-123");
  });

  it("addAccount prepends to accounts list", () => {
    const store = createStore();
    store.dispatch(setAccounts([{ id: "1", label: "A" }] as unknown as Parameters<typeof setAccounts>[0]));
    store.dispatch(addAccount({ id: "2", label: "B" } as unknown as Parameters<typeof addAccount>[0]));
    expect(store.getState().accounts.accounts).toHaveLength(2);
    expect(store.getState().accounts.accounts[0].id).toBe("2");
  });

  it("removeAccount filters out account by id", () => {
    const store = createStore();
    store.dispatch(setAccounts([{ id: "1" }, { id: "2" }] as unknown as Parameters<typeof setAccounts>[0]));
    store.dispatch(removeAccount("1"));
    expect(store.getState().accounts.accounts).toHaveLength(1);
    expect(store.getState().accounts.accounts[0].id).toBe("2");
  });

  it("updateAccountInList updates matching account", () => {
    const store = createStore();
    store.dispatch(setAccounts([{ id: "1", label: "Old" }] as unknown as Parameters<typeof setAccounts>[0]));
    store.dispatch(updateAccountInList({ id: "1", label: "New" } as unknown as Parameters<typeof updateAccountInList>[0]));
    expect(store.getState().accounts.accounts[0].label).toBe("New");
  });

  it("recordManualRefresh updates timestamp for account", () => {
    const store = createStore();
    store.dispatch(recordManualRefresh("acc-1"));
    const ts = store.getState().accounts.lastManualRefresh["acc-1"];
    expect(ts).toBeGreaterThan(0);
    expect(ts).toBeLessThanOrEqual(Date.now());
  });
});
