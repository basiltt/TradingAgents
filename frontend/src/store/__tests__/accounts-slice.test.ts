import { describe, it, expect } from "vitest";
import { configureStore } from "@reduxjs/toolkit";
import accountsReducer, {
  setAccounts,
  setDashboard,
  setLoading,
  setError,
  setFilterType,
  setSelectedAccount,
  setPollingInterval,
  recordManualRefresh,
  addAccount,
  removeAccount,
  updateAccountInList,
  updateCardRealtime,
  handleCloseExecution,
} from "@/store/accounts-slice";
import type { DashboardCard, TradingAccount } from "@/api/client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createStore() {
  return configureStore({ reducer: { accounts: accountsReducer } });
}

/** Convenience: run the reducer from its own initial state. */
const init = () => accountsReducer(undefined, { type: "@@INIT" });

const baseAccount: TradingAccount = {
  id: "acc-1",
  label: "Test Account",
  account_type: "demo",
  api_key_masked: "****1234",
  is_active: true,
  include_in_analytics: true,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

const baseCard: DashboardCard = {
  id: "acc-1",
  label: "Test Account",
  account_type: "demo",
  is_active: true,
  include_in_analytics: true,
  positions_count: 3,
  total_equity: "10000",
  total_perp_upl: "50",
  total_wallet_balance: "9950",
};

// ---------------------------------------------------------------------------
// 1. Initial state shape
// ---------------------------------------------------------------------------

describe("accountsSlice – initial state", () => {
  const state = init();

  it("has empty accounts list", () => {
    expect(state.accounts).toEqual([]);
  });

  it("has empty dashboard list", () => {
    expect(state.dashboard).toEqual([]);
  });

  it("status is idle", () => {
    expect(state.status).toBe("idle");
  });

  it("error is null", () => {
    expect(state.error).toBeNull();
  });

  it("filterType defaults to all", () => {
    expect(state.filterType).toBe("all");
  });

  it("selectedAccountId is null", () => {
    expect(state.selectedAccountId).toBeNull();
  });

  it("pollingIntervalMs is 30000", () => {
    expect(state.pollingIntervalMs).toBe(30_000);
  });

  it("lastManualRefresh is an empty object", () => {
    expect(state.lastManualRefresh).toEqual({});
  });

  it("directions is an empty object", () => {
    expect(state.directions).toEqual({});
  });

  it("closeExecutionSeq is 0", () => {
    expect(state.closeExecutionSeq).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 2. setAccounts
// ---------------------------------------------------------------------------

describe("accountsSlice – setAccounts", () => {
  it("replaces the accounts list", () => {
    const next = accountsReducer(init(), setAccounts([baseAccount]));
    expect(next.accounts).toHaveLength(1);
    expect(next.accounts[0].id).toBe("acc-1");
  });

  it("sets status to success", () => {
    const next = accountsReducer(init(), setAccounts([baseAccount]));
    expect(next.status).toBe("success");
  });

  it("clears any previous error", () => {
    const withError = accountsReducer(init(), setError("oops"));
    const next = accountsReducer(withError, setAccounts([baseAccount]));
    expect(next.error).toBeNull();
  });

  it("replaces an existing list rather than appending", () => {
    const s1 = accountsReducer(init(), setAccounts([baseAccount]));
    const second: TradingAccount = { ...baseAccount, id: "acc-2", label: "Second" };
    const s2 = accountsReducer(s1, setAccounts([second]));
    expect(s2.accounts).toHaveLength(1);
    expect(s2.accounts[0].id).toBe("acc-2");
  });

  it("accepts an empty array", () => {
    const withData = accountsReducer(init(), setAccounts([baseAccount]));
    const next = accountsReducer(withData, setAccounts([]));
    expect(next.accounts).toHaveLength(0);
    expect(next.status).toBe("success");
  });
});

// ---------------------------------------------------------------------------
// 3. setDashboard
// ---------------------------------------------------------------------------

describe("accountsSlice – setDashboard", () => {
  it("replaces dashboard cards", () => {
    const next = accountsReducer(init(), setDashboard([baseCard]));
    expect(next.dashboard).toHaveLength(1);
    expect(next.dashboard[0].id).toBe("acc-1");
  });

  it("sets status to success", () => {
    const next = accountsReducer(init(), setDashboard([baseCard]));
    expect(next.status).toBe("success");
  });

  it("clears any previous error", () => {
    const withError = accountsReducer(init(), setError("fail"));
    const next = accountsReducer(withError, setDashboard([baseCard]));
    expect(next.error).toBeNull();
  });

  it("replaces an existing dashboard rather than appending", () => {
    const s1 = accountsReducer(init(), setDashboard([baseCard]));
    const card2: DashboardCard = { ...baseCard, id: "acc-2", label: "Card 2" };
    const s2 = accountsReducer(s1, setDashboard([card2]));
    expect(s2.dashboard).toHaveLength(1);
    expect(s2.dashboard[0].id).toBe("acc-2");
  });

  it("accepts an empty array", () => {
    const withData = accountsReducer(init(), setDashboard([baseCard]));
    const next = accountsReducer(withData, setDashboard([]));
    expect(next.dashboard).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 4. updateCardRealtime
// ---------------------------------------------------------------------------

describe("accountsSlice – updateCardRealtime: field updates", () => {
  function stateWithCard(overrides: Partial<DashboardCard> = {}) {
    return accountsReducer(init(), setDashboard([{ ...baseCard, ...overrides }]));
  }

  it("updates totalEquity on a matching card", () => {
    const s = stateWithCard({ total_equity: "10000" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "11000" } }),
    );
    expect(next.dashboard[0].total_equity).toBe("11000");
  });

  it("updates totalPerpUPL on a matching card", () => {
    const s = stateWithCard({ total_perp_upl: "50" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "75" } }),
    );
    expect(next.dashboard[0].total_perp_upl).toBe("75");
  });

  it("updates totalWalletBalance on a matching card", () => {
    const s = stateWithCard({ total_wallet_balance: "9950" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalWalletBalance: "10500" } }),
    );
    expect(next.dashboard[0].total_wallet_balance).toBe("10500");
  });

  it("no-ops on unknown account_id (card values unchanged)", () => {
    const s = stateWithCard({ total_equity: "10000" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "unknown-id", type: "wallet", data: { totalEquity: "99999" } }),
    );
    expect(next.dashboard[0].total_equity).toBe("10000");
  });

  it("no-ops on unknown account_id (directions unchanged)", () => {
    const s = stateWithCard();
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "unknown-id", type: "wallet", data: { totalEquity: "99999" } }),
    );
    expect(next.directions["unknown-id"]).toBeUndefined();
  });

  it("does not overwrite equity for an empty-string value", () => {
    const s = stateWithCard({ total_equity: "10000" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "" } }),
    );
    expect(next.dashboard[0].total_equity).toBe("10000");
  });

  it("does not overwrite PnL for an empty-string value", () => {
    const s = stateWithCard({ total_perp_upl: "50" });
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "" } }),
    );
    expect(next.dashboard[0].total_perp_upl).toBe("50");
  });

  it("can update all three fields in one event", () => {
    const s = stateWithCard({ total_equity: "10000", total_perp_upl: "50", total_wallet_balance: "9950" });
    const next = accountsReducer(
      s,
      updateCardRealtime({
        account_id: "acc-1",
        type: "wallet",
        data: { totalEquity: "11000", totalPerpUPL: "100", totalWalletBalance: "10900" },
      }),
    );
    expect(next.dashboard[0].total_equity).toBe("11000");
    expect(next.dashboard[0].total_perp_upl).toBe("100");
    expect(next.dashboard[0].total_wallet_balance).toBe("10900");
  });
});

describe("accountsSlice – updateCardRealtime: direction for equity", () => {
  function stateWithEquity(equity: string | undefined) {
    return accountsReducer(init(), setDashboard([{ ...baseCard, total_equity: equity }]));
  }

  it("sets direction 'up' when equity increases", () => {
    const s = stateWithEquity("10000");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "11000" } }),
    );
    expect(next.directions["acc-1"]?.equity).toBe("up");
  });

  it("sets direction 'down' when equity decreases", () => {
    const s = stateWithEquity("10000");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "9000" } }),
    );
    expect(next.directions["acc-1"]?.equity).toBe("down");
  });

  it("sets direction 'neutral' when equity is unchanged", () => {
    const s = stateWithEquity("10000");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "10000" } }),
    );
    expect(next.directions["acc-1"]?.equity).toBe("neutral");
  });

  it("treats missing old equity as 0 — positive new value gives 'up'", () => {
    const s = stateWithEquity(undefined);
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "500" } }),
    );
    expect(next.directions["acc-1"]?.equity).toBe("up");
  });

  it("treats missing old equity as 0 — negative new value gives 'down'", () => {
    const s = stateWithEquity(undefined);
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "-100" } }),
    );
    expect(next.directions["acc-1"]?.equity).toBe("down");
  });
});

describe("accountsSlice – updateCardRealtime: direction for PnL", () => {
  function stateWithPnl(pnl: string | undefined) {
    return accountsReducer(init(), setDashboard([{ ...baseCard, total_perp_upl: pnl }]));
  }

  it("sets direction 'up' when PnL increases", () => {
    const s = stateWithPnl("50");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "100" } }),
    );
    expect(next.directions["acc-1"]?.pnl).toBe("up");
  });

  it("sets direction 'down' when PnL decreases", () => {
    const s = stateWithPnl("50");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "-20" } }),
    );
    expect(next.directions["acc-1"]?.pnl).toBe("down");
  });

  it("sets direction 'neutral' when PnL is unchanged", () => {
    const s = stateWithPnl("50");
    const next = accountsReducer(
      s,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "50" } }),
    );
    expect(next.directions["acc-1"]?.pnl).toBe("neutral");
  });

  it("preserves existing equity direction while adding pnl direction", () => {
    const s0 = accountsReducer(
      init(),
      setDashboard([{ ...baseCard, total_equity: "10000", total_perp_upl: "50" }]),
    );
    const s1 = accountsReducer(
      s0,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "11000" } }),
    );
    const s2 = accountsReducer(
      s1,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalPerpUPL: "75" } }),
    );
    expect(s2.directions["acc-1"]?.equity).toBe("up");
    expect(s2.directions["acc-1"]?.pnl).toBe("up");
  });
});

// ---------------------------------------------------------------------------
// 5. selectAccountById (via store state)
// ---------------------------------------------------------------------------

describe("accountsSlice – selectAccountById (via store)", () => {
  it("finds the matching account by id", () => {
    const store = createStore();
    const second: TradingAccount = { ...baseAccount, id: "acc-2", label: "Second" };
    store.dispatch(setAccounts([baseAccount, second]));
    const found = store.getState().accounts.accounts.find((a) => a.id === "acc-2");
    expect(found).toBeDefined();
    expect(found?.label).toBe("Second");
  });

  it("returns undefined for an id that does not exist", () => {
    const store = createStore();
    store.dispatch(setAccounts([baseAccount]));
    const found = store.getState().accounts.accounts.find((a) => a.id === "no-such-id");
    expect(found).toBeUndefined();
  });

  it("returns undefined when the accounts list is empty", () => {
    const store = createStore();
    const found = store.getState().accounts.accounts.find((a) => a.id === "acc-1");
    expect(found).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 6. setLoading
// ---------------------------------------------------------------------------

describe("accountsSlice – setLoading", () => {
  it("sets status to loading", () => {
    const next = accountsReducer(init(), setLoading());
    expect(next.status).toBe("loading");
  });

  it("does not clear an existing error message", () => {
    const withError = accountsReducer(init(), setError("prev error"));
    const next = accountsReducer(withError, setLoading());
    // status changes but error text remains until setError or setAccounts clear it
    expect(next.status).toBe("loading");
    expect(next.error).toBe("prev error");
  });
});

// ---------------------------------------------------------------------------
// 7. setError
// ---------------------------------------------------------------------------

describe("accountsSlice – setError", () => {
  it("sets status to error", () => {
    const next = accountsReducer(init(), setError("network failure"));
    expect(next.status).toBe("error");
  });

  it("stores the error message", () => {
    const next = accountsReducer(init(), setError("network failure"));
    expect(next.error).toBe("network failure");
  });

  it("overwrites a previous error", () => {
    const s1 = accountsReducer(init(), setError("first error"));
    const s2 = accountsReducer(s1, setError("second error"));
    expect(s2.error).toBe("second error");
  });
});

// ---------------------------------------------------------------------------
// 8. setFilterType
// ---------------------------------------------------------------------------

describe("accountsSlice – setFilterType", () => {
  it("sets filterType to live", () => {
    const next = accountsReducer(init(), setFilterType("live"));
    expect(next.filterType).toBe("live");
  });

  it("sets filterType to demo", () => {
    const next = accountsReducer(init(), setFilterType("demo"));
    expect(next.filterType).toBe("demo");
  });

  it("resets filterType back to all", () => {
    const s1 = accountsReducer(init(), setFilterType("demo"));
    const s2 = accountsReducer(s1, setFilterType("all"));
    expect(s2.filterType).toBe("all");
  });
});

// ---------------------------------------------------------------------------
// 9. setSelectedAccount
// ---------------------------------------------------------------------------

describe("accountsSlice – setSelectedAccount", () => {
  it("sets selectedAccountId to the given id", () => {
    const next = accountsReducer(init(), setSelectedAccount("acc-1"));
    expect(next.selectedAccountId).toBe("acc-1");
  });

  it("clears selectedAccountId when passed null", () => {
    const s1 = accountsReducer(init(), setSelectedAccount("acc-1"));
    const s2 = accountsReducer(s1, setSelectedAccount(null));
    expect(s2.selectedAccountId).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 10. setPollingInterval
// ---------------------------------------------------------------------------

describe("accountsSlice – setPollingInterval", () => {
  it("updates pollingIntervalMs", () => {
    const next = accountsReducer(init(), setPollingInterval(60_000));
    expect(next.pollingIntervalMs).toBe(60_000);
  });

  it("accepts custom low values", () => {
    const next = accountsReducer(init(), setPollingInterval(5_000));
    expect(next.pollingIntervalMs).toBe(5_000);
  });
});

// ---------------------------------------------------------------------------
// 11. recordManualRefresh
// ---------------------------------------------------------------------------

describe("accountsSlice – recordManualRefresh", () => {
  it("records a timestamp for the given account id", () => {
    const before = Date.now();
    const next = accountsReducer(init(), recordManualRefresh("acc-1"));
    const after = Date.now();
    expect(next.lastManualRefresh["acc-1"]).toBeGreaterThanOrEqual(before);
    expect(next.lastManualRefresh["acc-1"]).toBeLessThanOrEqual(after);
  });

  it("keeps separate timestamps for different accounts", () => {
    const s1 = accountsReducer(init(), recordManualRefresh("acc-1"));
    const s2 = accountsReducer(s1, recordManualRefresh("acc-2"));
    expect(s2.lastManualRefresh["acc-1"]).toBeDefined();
    expect(s2.lastManualRefresh["acc-2"]).toBeDefined();
  });

  it("overwrites the previous timestamp on re-refresh", () => {
    const s1 = accountsReducer(init(), recordManualRefresh("acc-1"));
    const ts1 = s1.lastManualRefresh["acc-1"]!;
    const s2 = accountsReducer(s1, recordManualRefresh("acc-1"));
    expect(s2.lastManualRefresh["acc-1"]).toBeGreaterThanOrEqual(ts1);
  });
});

// ---------------------------------------------------------------------------
// 12. addAccount
// ---------------------------------------------------------------------------

describe("accountsSlice – addAccount", () => {
  it("prepends the new account at index 0", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const newAcc: TradingAccount = { ...baseAccount, id: "acc-new", label: "New" };
    const next = accountsReducer(s0, addAccount(newAcc));
    expect(next.accounts[0].id).toBe("acc-new");
  });

  it("increases the list length by 1", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const newAcc: TradingAccount = { ...baseAccount, id: "acc-new", label: "New" };
    const next = accountsReducer(s0, addAccount(newAcc));
    expect(next.accounts).toHaveLength(2);
  });

  it("works when the list is initially empty", () => {
    const next = accountsReducer(init(), addAccount(baseAccount));
    expect(next.accounts).toHaveLength(1);
    expect(next.accounts[0].id).toBe("acc-1");
  });
});

// ---------------------------------------------------------------------------
// 13. removeAccount
// ---------------------------------------------------------------------------

describe("accountsSlice – removeAccount", () => {
  it("removes the account from the accounts list", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const next = accountsReducer(s0, removeAccount("acc-1"));
    expect(next.accounts).toHaveLength(0);
  });

  it("removes the matching card from the dashboard list", () => {
    let s = accountsReducer(init(), setAccounts([baseAccount]));
    s = accountsReducer(s, setDashboard([baseCard]));
    const next = accountsReducer(s, removeAccount("acc-1"));
    expect(next.dashboard).toHaveLength(0);
  });

  it("clears the direction cache for that account", () => {
    const s0 = accountsReducer(init(), setDashboard([baseCard]));
    const s1 = accountsReducer(
      s0,
      updateCardRealtime({ account_id: "acc-1", type: "wallet", data: { totalEquity: "11000" } }),
    );
    expect(s1.directions["acc-1"]).toBeDefined();
    const s2 = accountsReducer(s1, removeAccount("acc-1"));
    expect(s2.directions["acc-1"]).toBeUndefined();
  });

  it("leaves other accounts untouched", () => {
    const second: TradingAccount = { ...baseAccount, id: "acc-2", label: "Second" };
    const s0 = accountsReducer(init(), setAccounts([baseAccount, second]));
    const next = accountsReducer(s0, removeAccount("acc-1"));
    expect(next.accounts).toHaveLength(1);
    expect(next.accounts[0].id).toBe("acc-2");
  });

  it("no-ops gracefully for an unknown id", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const next = accountsReducer(s0, removeAccount("ghost-id"));
    expect(next.accounts).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 14. updateAccountInList
// ---------------------------------------------------------------------------

describe("accountsSlice – updateAccountInList", () => {
  it("replaces the matching account in the list", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const updated: TradingAccount = { ...baseAccount, label: "Updated Label" };
    const next = accountsReducer(s0, updateAccountInList(updated));
    expect(next.accounts[0].label).toBe("Updated Label");
  });

  it("does not change the list length", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const updated: TradingAccount = { ...baseAccount, label: "Updated" };
    const next = accountsReducer(s0, updateAccountInList(updated));
    expect(next.accounts).toHaveLength(1);
  });

  it("no-ops for an unknown account id", () => {
    const s0 = accountsReducer(init(), setAccounts([baseAccount]));
    const ghost: TradingAccount = { ...baseAccount, id: "ghost", label: "Ghost" };
    const next = accountsReducer(s0, updateAccountInList(ghost));
    expect(next.accounts).toHaveLength(1);
    expect(next.accounts[0].id).toBe("acc-1");
  });
});

// ---------------------------------------------------------------------------
// 15. handleCloseExecution
// ---------------------------------------------------------------------------

describe("accountsSlice – handleCloseExecution", () => {
  it("decrements positions_count by the closed number", () => {
    const s0 = accountsReducer(init(), setDashboard([{ ...baseCard, positions_count: 5 }]));
    const next = accountsReducer(s0, handleCloseExecution({ account_id: "acc-1", data: { closed: 2 } }));
    expect(next.dashboard[0].positions_count).toBe(3);
  });

  it("does not let positions_count go below zero", () => {
    const s0 = accountsReducer(init(), setDashboard([{ ...baseCard, positions_count: 1 }]));
    const next = accountsReducer(s0, handleCloseExecution({ account_id: "acc-1", data: { closed: 10 } }));
    expect(next.dashboard[0].positions_count).toBe(0);
  });

  it("increments closeExecutionSeq by 1", () => {
    const s0 = accountsReducer(init(), setDashboard([baseCard]));
    const next = accountsReducer(s0, handleCloseExecution({ account_id: "acc-1", data: { closed: 1 } }));
    expect(next.closeExecutionSeq).toBe(1);
  });

  it("accumulates closeExecutionSeq across multiple dispatches", () => {
    const s0 = accountsReducer(init(), setDashboard([{ ...baseCard, positions_count: 5 }]));
    const s1 = accountsReducer(s0, handleCloseExecution({ account_id: "acc-1", data: { closed: 1 } }));
    const s2 = accountsReducer(s1, handleCloseExecution({ account_id: "acc-1", data: { closed: 1 } }));
    expect(s2.closeExecutionSeq).toBe(2);
  });

  it("no-ops (positions and seq unchanged) for an unknown account_id", () => {
    const s0 = accountsReducer(init(), setDashboard([{ ...baseCard, positions_count: 3 }]));
    const next = accountsReducer(s0, handleCloseExecution({ account_id: "unknown", data: { closed: 1 } }));
    expect(next.dashboard[0].positions_count).toBe(3);
    expect(next.closeExecutionSeq).toBe(0);
  });

  it("treats a non-number closed value as 0 (positions unchanged)", () => {
    const s0 = accountsReducer(init(), setDashboard([{ ...baseCard, positions_count: 3 }]));
    // data.closed coerced via the guard inside the reducer: non-number → 0
    const next = accountsReducer(
      s0,
      handleCloseExecution({ account_id: "acc-1", data: { closed: "bad" as unknown as number } }),
    );
    expect(next.dashboard[0].positions_count).toBe(3);
  });
});
