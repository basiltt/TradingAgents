import { describe, it, expect } from "vitest";
import {
  MAPPABLE_KEYS,
  PROTECTED_KEYS,
  getReferencePreset,
  presetToAutoTradeConfig,
  presetChangesCard,
  cardHasEdits,
} from "../applyReferencePreset";
import {
  DAD_DEMO_REFERENCE_CONFIG,
  OPTIMIZED_REFERENCE_CONFIG,
} from "@/components/backtest/referencePresets";
import { DEFAULT_CONFIG } from "../AutoTradeSection";
import type { AutoTradeConfig } from "@/api/client";

// Backtest-only preset keys that have NO AutoTradeConfig equivalent and must be skipped.
const BACKTEST_ONLY = new Set([
  "starting_capital",
  "date_range_start",
  "date_range_end",
  "scan_source",
  "simulation_interval",
  "fee_rate_pct",
  "slippage_bps",
  "funding_rate_model",
  "funding_rate_fixed_pct",
]);

function makeCard(overrides: Partial<AutoTradeConfig> = {}): AutoTradeConfig {
  return { ...DEFAULT_CONFIG, account_id: "acct-1", ...overrides };
}

describe("applyReferencePreset — mapper", () => {
  it("maps the reference preset's trade/risk values onto AutoTradeConfig", () => {
    const out = presetToAutoTradeConfig("reference");
    expect(out.leverage).toBe(8);
    expect(out.capital_pct).toBe(22);
    expect(out.take_profit_pct).toBe(150);
    expect(out.min_score).toBe(7);
    expect(out.confidence_filter).toBe("moderate");
    expect(out.execution_mode).toBe("batch");
    expect(out.cooloff_on_double_failure_enabled).toBe(true);
    expect(out.cooloff_on_double_failure_minutes).toBe(600);
    expect(out.max_drawdown_pct).toBe(12);
    expect(out.target_goal_type).toBe("profit_pct");
    expect(out.target_goal_value).toBe(15);
  });

  it("excludes every backtest-only key from the mapped output", () => {
    const out = presetToAutoTradeConfig("reference") as Record<string, unknown>;
    for (const k of BACKTEST_ONLY) {
      expect(out).not.toHaveProperty(k);
    }
  });

  it("excludes every protected (account/AI/response-only) key from the mapped output", () => {
    const ref = presetToAutoTradeConfig("reference") as Record<string, unknown>;
    const opt = presetToAutoTradeConfig("optimized") as Record<string, unknown>;
    for (const k of PROTECTED_KEYS) {
      expect(ref).not.toHaveProperty(k);
      expect(opt).not.toHaveProperty(k);
    }
  });

  it("optimized differs from reference EXACTLY on the 4 documented knobs", () => {
    const ref = presetToAutoTradeConfig("reference") as Record<string, unknown>;
    const opt = presetToAutoTradeConfig("optimized") as Record<string, unknown>;
    const changed = Object.keys({ ...ref, ...opt }).filter(
      (k) => !Object.is(ref[k], opt[k]),
    );
    expect(new Set(changed)).toEqual(
      new Set(["leverage", "max_trades", "max_drawdown_pct", "target_goal_value"]),
    );
    expect(opt.leverage).toBe(7);
    expect(opt.max_trades).toBe(4);
    expect(opt.max_drawdown_pct).toBe(100);
    expect(opt.target_goal_value).toBe(12);
  });

  it("getReferencePreset returns the underlying literal for each id", () => {
    expect(getReferencePreset("reference")).toBe(DAD_DEMO_REFERENCE_CONFIG);
    expect(getReferencePreset("optimized")).toBe(OPTIMIZED_REFERENCE_CONFIG);
  });
});

describe("applyReferencePreset — guards & drift safety", () => {
  it("MAPPABLE_KEYS and PROTECTED_KEYS are disjoint (runtime backstop for the type guard)", () => {
    const protectedSet = new Set<string>(PROTECTED_KEYS);
    const overlap = (MAPPABLE_KEYS as readonly string[]).filter((k) => protectedSet.has(k));
    expect(overlap).toEqual([]);
  });

  it("has no duplicate keys in MAPPABLE_KEYS", () => {
    expect(new Set(MAPPABLE_KEYS).size).toBe(MAPPABLE_KEYS.length);
  });

  it("covers every preset key: each is either mappable or explicitly backtest-only", () => {
    // A future preset key nobody mapped fails HERE instead of silently dropping.
    const mappable = new Set<string>(MAPPABLE_KEYS as readonly string[]);
    for (const k of Object.keys(DAD_DEMO_REFERENCE_CONFIG)) {
      expect(mappable.has(k) || BACKTEST_ONLY.has(k)).toBe(true);
    }
  });

  it("maps exactly 65 keys", () => {
    expect(MAPPABLE_KEYS.length).toBe(65);
  });
});

describe("applyReferencePreset — card-state helpers", () => {
  it("cardHasEdits is false for a pristine card (defaults + account_id only)", () => {
    expect(cardHasEdits(makeCard(), DEFAULT_CONFIG)).toBe(false);
  });

  it("cardHasEdits is true once a mappable field diverges from defaults", () => {
    expect(cardHasEdits(makeCard({ leverage: 13 }), DEFAULT_CONFIG)).toBe(true);
  });

  it("cardHasEdits ignores account_id and AI fields (not mappable keys)", () => {
    // Changing only protected fields must NOT count as a trade-settings edit.
    const card = makeCard({ account_id: "other", ai_manager_enabled: true });
    expect(cardHasEdits(card, DEFAULT_CONFIG)).toBe(false);
  });

  it("presetChangesCard is true for a pristine card (preset differs from defaults)", () => {
    expect(presetChangesCard(makeCard(), "reference")).toBe(true);
  });

  it("presetChangesCard is false when the card already equals the preset", () => {
    const applied = makeCard(presetToAutoTradeConfig("optimized"));
    expect(presetChangesCard(applied, "optimized")).toBe(false);
  });
});
