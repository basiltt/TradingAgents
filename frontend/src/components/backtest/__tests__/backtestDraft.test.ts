import { describe, it, expect, beforeEach } from "vitest";
import {
  clearDraft,
  loadDraft,
  loadReferenceConfig,
  saveDraft,
  saveReferenceConfig,
} from "../backtestDraft";

describe("backtestDraft", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("loadDraft returns undefined when nothing is saved", () => {
    expect(loadDraft()).toBeUndefined();
  });

  it("loadDraft returns undefined on corrupt JSON", () => {
    localStorage.setItem("tradingagents_backtest_draft", "not-json{");
    expect(loadDraft()).toBeUndefined();
  });

  it("saveDraft then loadDraft round-trips the values", () => {
    saveDraft({ starting_capital: 25000, leverage: 7, scan_source: { mode: "date_range" } });
    expect(loadDraft()).toEqual({
      starting_capital: 25000,
      leverage: 7,
      scan_source: { mode: "date_range" },
    });
  });

  it("saveDraft overwrites a previous draft", () => {
    saveDraft({ starting_capital: 1000 });
    saveDraft({ starting_capital: 2000 });
    expect(loadDraft()?.starting_capital).toBe(2000);
  });

  it("clearDraft removes the saved draft", () => {
    saveDraft({ starting_capital: 1000 });
    clearDraft();
    expect(loadDraft()).toBeUndefined();
  });

  it("reference config is stored separately from the in-progress draft", () => {
    saveDraft({ starting_capital: 1000, leverage: 5 });
    saveReferenceConfig({ starting_capital: 234, leverage: 10 });

    expect(loadDraft()).toEqual({ starting_capital: 1000, leverage: 5 });
    expect(loadReferenceConfig()).toEqual({ starting_capital: 234, leverage: 10 });

    clearDraft();
    expect(loadDraft()).toBeUndefined();
    expect(loadReferenceConfig()).toEqual({ starting_capital: 234, leverage: 10 });
  });
});
