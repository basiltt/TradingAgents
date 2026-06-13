import { describe, it, expect } from "vitest";
import {
  backtestConfigSchema,
  DAD_DEMO_REFERENCE_CONFIG,
  OPTIMIZED_REFERENCE_CONFIG,
  scanSourceSchema,
  buildDefaults,
  buildDadDemoReferenceDefaults,
  buildOptimizedReferenceDefaults,
  toCreateRequest,
} from "../configSchema";

describe("scanSourceSchema", () => {
  it("requires schedule_id in schedule mode", () => {
    expect(scanSourceSchema.safeParse({ mode: "schedule" }).success).toBe(false);
    expect(
      scanSourceSchema.safeParse({ mode: "schedule", schedule_id: "s1" }).success,
    ).toBe(true);
  });
  it("ignores stale null sibling fields from inactive source modes", () => {
    const result = scanSourceSchema.safeParse({
      mode: "schedule",
      schedule_id: "s1",
      scan_ids: null,
      replay_account_id: null,
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.mode).toBe("schedule");
      expect(result.data.schedule_id).toBe("s1");
      expect(result.data.scan_ids).toBeUndefined();
      expect(result.data.replay_account_id).toBeUndefined();
    }
  });
  it("requires non-empty scan_ids in explicit mode", () => {
    expect(scanSourceSchema.safeParse({ mode: "explicit", scan_ids: [] }).success).toBe(false);
    expect(
      scanSourceSchema.safeParse({ mode: "explicit", scan_ids: ["a"] }).success,
    ).toBe(true);
  });
  it("accepts date_range mode with no extra fields", () => {
    expect(scanSourceSchema.safeParse({ mode: "date_range" }).success).toBe(true);
  });
});

describe("backtestConfigSchema", () => {
  it("parses a minimal valid config and applies production-aligned defaults", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: 10000,
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      // Defaults mirror the backend BacktestCreateRequest / production AutoTradeConfig
      // so omitted fields reflect real-world trading, not an arbitrary form preset.
      expect(result.data.simulation_interval).toBe("5m");
      expect(result.data.leverage).toBe(20);
      expect(result.data.capital_pct).toBe(5);
      expect(result.data.take_profit_pct).toBe(150);
      expect(result.data.stop_loss_pct).toBe(100);
      expect(result.data.max_trades).toBe(999);
      expect(result.data.execution_mode).toBe("immediate");
      expect(result.data.slippage_bps).toBe(2);
      expect(result.data.skip_if_positions_open).toBe(false);
      expect(result.data.fee_rate_pct).toBeCloseTo(0.055);
    }
  });

  it("rejects non-positive starting capital", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: 0,
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(false);
  });

  it("rejects end <= start", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: 10000,
      date_range_start: "2026-02-01T00:00",
      date_range_end: "2026-01-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues.some((i) => i.path.includes("date_range_end"))).toBe(true);
    }
  });

  it("coerces string numbers (form inputs) to numbers", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: "5000",
      leverage: "10",
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.starting_capital).toBe(5000);
      expect(result.data.leverage).toBe(10);
    }
  });

  it("clamps leverage to <= 125", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: 10000,
      leverage: 200,
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(false);
  });

  const baseValid = {
    starting_capital: 10000,
    date_range_start: "2026-01-01T00:00",
    date_range_end: "2026-02-01T00:00",
    scan_source: { mode: "date_range" as const },
  };

  it("rejects an enabled cool-off tier with no duration (backend validate_cooloff parity)", () => {
    const result = backtestConfigSchema.safeParse({
      ...baseValid,
      cooloff_on_failure_enabled: true,
      cooloff_on_failure_minutes: null,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(
        result.error.issues.some((i) => i.path.includes("cooloff_on_failure_minutes")),
      ).toBe(true);
    }
  });

  it("accepts an enabled cool-off tier with a valid duration", () => {
    const result = backtestConfigSchema.safeParse({
      ...baseValid,
      cooloff_on_double_success_enabled: true,
      cooloff_on_double_success_minutes: 90,
    });
    expect(result.success).toBe(true);
  });

  it("accepts cool-off tiers left off (the default)", () => {
    expect(backtestConfigSchema.safeParse(baseValid).success).toBe(true);
  });

  it("rejects a cool-off duration above the 43200-minute maximum", () => {
    const result = backtestConfigSchema.safeParse({
      ...baseValid,
      cooloff_on_success_enabled: true,
      cooloff_on_success_minutes: 43201,
    });
    expect(result.success).toBe(false);
  });

  it("rejects a cool-off duration below the 1-minute minimum", () => {
    const result = backtestConfigSchema.safeParse({
      ...baseValid,
      cooloff_on_failure_enabled: true,
      cooloff_on_failure_minutes: 0,
    });
    expect(result.success).toBe(false);
  });
});

describe("buildDefaults", () => {
  it("produces a schema-valid object", () => {
    const defaults = buildDefaults();
    const result = backtestConfigSchema.safeParse(defaults);
    expect(result.success).toBe(true);
  });
  it("honors seed overrides", () => {
    const defaults = buildDefaults({ starting_capital: 50000, leverage: 3 });
    expect(defaults.starting_capital).toBe(50000);
    expect(defaults.leverage).toBe(3);
  });
  it("converts an ISO-string seed date into datetime-local format (Retry round-trip)", () => {
    // toCreateRequest stores dates as full ISO with 'Z'; a datetime-local input
    // would blank such a value, so buildDefaults must strip it to YYYY-MM-DDTHH:mm.
    const defaults = buildDefaults({
      date_range_start: "2026-05-06T12:00:00.000Z",
      date_range_end: "2026-06-06T12:00:00.000Z",
    });
    expect(defaults.date_range_start).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(defaults.date_range_start).not.toContain("Z");
    expect(defaults.date_range_end).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    // Still schema-valid.
    expect(backtestConfigSchema.safeParse(defaults).success).toBe(true);
  });
  it("passes through a plain datetime-local seed unchanged", () => {
    const defaults = buildDefaults({ date_range_start: "2026-05-06T12:00" });
    expect(defaults.date_range_start).toBe("2026-05-06T12:00");
  });
  it("round-trips an ISO seed date to the same absolute instant (value-stable, not just shape)", () => {
    // Guards against a getHours()→getUTCHours() regression: the retry seed must
    // resolve back to the exact same instant it came from, to the minute.
    const iso = "2026-05-06T12:34:00.000Z";
    const defaults = buildDefaults({ date_range_start: iso, date_range_end: "2026-06-06T12:34:00.000Z" });
    // The local-format string, re-parsed as local time, equals the original instant (minute precision).
    const roundTripped = new Date(defaults.date_range_start);
    expect(roundTripped.getTime()).toBe(new Date(iso).getTime());
  });
  it("defaults max_drawdown_pct to a backend-valid positive value (not 0)", () => {
    // Backend requires gt=0; a 0 default would 422 on every untouched submit.
    expect(buildDefaults().max_drawdown_pct).toBe(100);
  });

  it("applies the Dad Demo reference config without carrying an account id", () => {
    const defaults = buildDadDemoReferenceDefaults({
      date_range_start: "2026-06-05T00:00",
      date_range_end: "2026-06-11T00:00",
      scan_source: { mode: "schedule", schedule_id: "sched-1" },
      leverage: 99,
      symbol_whitelist: ["BTCUSDT"],
    });

    expect(defaults.starting_capital).toBe(234);
    expect(defaults.leverage).toBe(8);
    expect(defaults.capital_pct).toBe(22);
    expect(defaults.max_trades).toBe(3);
    expect(defaults.execution_mode).toBe("batch");
    expect(defaults.confidence_filter).toBe("moderate");
    expect(defaults.funding_rate_model).toBe("fixed_8h");
    expect(defaults.max_drawdown_pct).toBe(12);
    expect(defaults.breakeven_timeout_hours).toBeNull();
    expect(defaults.max_trade_duration_hours).toBe(24);
    expect(defaults.target_goal_type).toBe("profit_pct");
    expect(defaults.target_goal_value).toBe(15);
    expect(defaults.max_same_sector).toBe(4);
    expect(defaults.max_price_drift_pct).toBe(6);
    expect(defaults.max_signal_age_minutes).toBe(150);
    expect(defaults.cooloff_on_double_failure_enabled).toBe(true);
    expect(defaults.cooloff_on_double_failure_minutes).toBe(600);
    expect(defaults.symbol_blacklist).toBeNull();
    expect(defaults.symbol_whitelist).toBeNull();
    expect(defaults.adaptive_blacklist_enabled).toBe(false);
    expect(defaults.mr_short_enabled).toBe(false);
    expect(defaults.date_range_start).toBe("2026-06-04T18:30");
    expect(defaults.date_range_end).toBe("2026-06-13T06:07");
    expect(defaults.scan_source).toEqual({
      mode: "schedule",
      schedule_id: "d9c5f14f-a71f-4907-9449-dab3b75a52cb",
    });
    expect("account_id" in DAD_DEMO_REFERENCE_CONFIG).toBe(false);
    expect(backtestConfigSchema.safeParse(defaults).success).toBe(true);
  });

  it("applies the optimized reference config without carrying an account id", () => {
    const defaults = buildOptimizedReferenceDefaults();

    // The optimized preset is the June 2026 sweep winner: the Dad-Demo baseline
    // with exactly four knobs changed (leverage 8→7, max_trades 3→4, portfolio
    // drawdown stop 12→off, profit target 15→12). Everything else is inherited.
    expect(defaults.starting_capital).toBe(234);
    expect(defaults.leverage).toBe(7);
    expect(defaults.capital_pct).toBe(22);
    expect(defaults.min_score).toBe(7);
    expect(defaults.confidence_filter).toBe("moderate");
    expect(defaults.max_trades).toBe(4);
    expect(defaults.execution_mode).toBe("batch");
    expect(defaults.max_signal_age_minutes).toBe(150);
    expect(defaults.max_price_drift_pct).toBe(6);
    expect(defaults.max_drawdown_pct).toBe(100);
    expect(defaults.breakeven_timeout_hours).toBeNull();
    expect(defaults.max_trade_duration_hours).toBe(24);
    expect(defaults.trailing_profit_pct).toBe(2);
    expect(defaults.target_goal_type).toBe("profit_pct");
    expect(defaults.target_goal_value).toBe(12);
    expect(defaults.date_range_start).toBe("2026-06-04T18:30");
    expect(defaults.date_range_end).toBe("2026-06-13T06:07");
    expect(defaults.scan_source).toEqual({
      mode: "schedule",
      schedule_id: "d9c5f14f-a71f-4907-9449-dab3b75a52cb",
    });
    expect("account_id" in OPTIMIZED_REFERENCE_CONFIG).toBe(false);
    expect(backtestConfigSchema.safeParse(defaults).success).toBe(true);
  });

  it("its non-seed fallbacks equal the schema's own defaults (no silent drift)", () => {
    // buildDefaults() supplies EVERY field, so the zod .default()s never fire in the
    // form. If these two drift, the form ships non-production presets while a raw-API
    // caller gets the schema defaults — breaking the "~100% real trading" guarantee.
    // Parsing an (almost) empty object surfaces the schema's own defaults; compare the
    // production-relevant scalar fields field-by-field.
    const schemaDefaults = backtestConfigSchema.parse({
      starting_capital: 10000,
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    const formDefaults = buildDefaults();
    const fields: Array<keyof typeof schemaDefaults> = [
      "simulation_interval", "fee_rate_pct", "slippage_bps", "funding_rate_model",
      "funding_rate_fixed_pct", "direction", "leverage", "capital_pct",
      "take_profit_pct", "stop_loss_pct", "min_score", "confidence_filter",
      "signal_sides", "max_trades", "execution_mode", "fill_to_max_trades",
      "skip_if_positions_open", "max_drawdown_pct", "smart_drawdown_close",
      "adaptive_blacklist_enabled", "adaptive_blacklist_min_trades",
      "adaptive_blacklist_max_win_rate", "adaptive_blacklist_lookback_hours",
    ];
    for (const f of fields) {
      expect(formDefaults[f], `buildDefaults.${String(f)} must equal the schema default`)
        .toEqual(schemaDefaults[f]);
    }
  });
});

/**
 * Contract-alignment guards: these ranges MUST mirror backend
 * BacktestCreateRequest (backtest_schemas.py). The unit suite mocks the POST, so
 * without these a range drift would only surface as a runtime 422.
 */
describe("backend contract alignment", () => {
  const base = {
    starting_capital: 10000,
    date_range_start: "2026-01-01T00:00",
    date_range_end: "2026-02-01T00:00",
    scan_source: { mode: "date_range" as const },
  };
  const parse = (over: Record<string, unknown>) =>
    backtestConfigSchema.safeParse({ ...base, ...over });

  it("max_drawdown_pct must be > 0 (backend gt=0)", () => {
    expect(parse({ max_drawdown_pct: 0 }).success).toBe(false);
    expect(parse({ max_drawdown_pct: 50 }).success).toBe(true);
  });
  it("min_score is on the -10..10 scale (not 0..100)", () => {
    expect(parse({ min_score: 5 }).success).toBe(true);
    expect(parse({ min_score: -10 }).success).toBe(true);
    expect(parse({ min_score: 10 }).success).toBe(true); // upper boundary accepted
    expect(parse({ min_score: 11 }).success).toBe(false);
    expect(parse({ min_score: 50 }).success).toBe(false);
  });
  it("funding_rate_fixed_pct accepts -0.5..0.5 and rejects beyond", () => {
    expect(parse({ funding_rate_fixed_pct: -0.5 }).success).toBe(true);
    expect(parse({ funding_rate_fixed_pct: 0.5 }).success).toBe(true);
    expect(parse({ funding_rate_fixed_pct: -1 }).success).toBe(false);
    expect(parse({ funding_rate_fixed_pct: 0.6 }).success).toBe(false);
  });
  it("adaptive_blacklist_lookback_hours caps at 720", () => {
    expect(parse({ adaptive_blacklist_lookback_hours: 720 }).success).toBe(true);
    expect(parse({ adaptive_blacklist_lookback_hours: 721 }).success).toBe(false);
  });
  it("scan_ids are capped at 500 (explicit mode)", () => {
    const ids = (n: number) => Array.from({ length: n }, (_, i) => `s${i}`);
    expect(
      backtestConfigSchema.safeParse({
        ...base,
        scan_source: { mode: "explicit", scan_ids: ids(500) },
      }).success,
    ).toBe(true);
    expect(
      backtestConfigSchema.safeParse({
        ...base,
        scan_source: { mode: "explicit", scan_ids: ids(501) },
      }).success,
    ).toBe(false);
  });
  it("take_profit_pct and stop_loss_pct must be > 0", () => {
    expect(parse({ take_profit_pct: 0 }).success).toBe(false);
    expect(parse({ stop_loss_pct: 0 }).success).toBe(false);
  });
  it("starting_capital max is 100,000,000", () => {
    expect(parse({ starting_capital: 100_000_000 }).success).toBe(true);
    expect(parse({ starting_capital: 100_000_001 }).success).toBe(false);
  });
  it("max_trades caps at 999", () => {
    expect(parse({ max_trades: 999 }).success).toBe(true);
    expect(parse({ max_trades: 1000 }).success).toBe(false);
  });
  it("fee_rate_pct max is 1, slippage_bps max is 50", () => {
    expect(parse({ fee_rate_pct: 2 }).success).toBe(false);
    expect(parse({ slippage_bps: 100 }).success).toBe(false);
  });
  it("nullable risk limits enforce backend min/max (max_same_sector 1..50)", () => {
    expect(parse({ max_same_sector: 0 }).success).toBe(false);
    expect(parse({ max_same_sector: 51 }).success).toBe(false);
    expect(parse({ max_same_sector: 25 }).success).toBe(true);
  });
  it("rejects a date range exceeding 365 days", () => {
    expect(
      backtestConfigSchema.safeParse({
        ...base,
        date_range_start: "2026-01-01T00:00",
        date_range_end: "2027-06-01T00:00",
      }).success,
    ).toBe(false);
  });
  it("rejects stop_loss_pct that reaches liquidation at the given leverage", () => {
    // sl/lev >= 100 → liquidation. 1000 / 5 = 200 >= 100 → invalid.
    expect(parse({ stop_loss_pct: 1000, leverage: 5 }).success).toBe(false);
    expect(parse({ stop_loss_pct: 100, leverage: 5 }).success).toBe(true);
  });
  it("rejects breakeven_timeout >= max_trade_duration when both set", () => {
    expect(parse({ breakeven_timeout_hours: 10, max_trade_duration_hours: 5 }).success).toBe(false);
    expect(parse({ breakeven_timeout_hours: 5, max_trade_duration_hours: 10 }).success).toBe(true);
  });
  it("coerces empty string to 0 for non-nullable numbers (footgun documented)", () => {
    // z.coerce.number() turns "" into 0; leverage 0 < min 1 → rejected.
    expect(parse({ leverage: "" }).success).toBe(false);
  });
  it("rejects fractional max_trades (.int())", () => {
    expect(parse({ max_trades: 10.5 }).success).toBe(false);
  });
});

describe("toCreateRequest", () => {
  it("normalizes dates to ISO 8601", () => {
    const parsed = backtestConfigSchema.parse(buildDefaults({
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
    }));
    const req = toCreateRequest(parsed);
    expect(req.date_range_start).toMatch(/^\d{4}-\d{2}-\d{2}T.*Z$/);
    expect(req.date_range_end).toMatch(/Z$/);
  });

  it("whitelists scan_source fields by mode (no stale sibling leaks)", () => {
    // A replay request must carry ONLY mode + replay_account_id — a stale schedule_id
    // left over from a prior selection must not reach the backend.
    const parsed = backtestConfigSchema.parse(buildDefaults({
      scan_source: {
        mode: "replay",
        replay_account_id: "acct-1",
        schedule_id: "stale-sched",   // simulate a leftover from switching modes
      } as never,
    }));
    const req = toCreateRequest(parsed);
    expect(req.scan_source).toEqual({ mode: "replay", replay_account_id: "acct-1" });
    expect((req.scan_source as unknown as Record<string, unknown>).schedule_id).toBeUndefined();
  });

  it("keeps only schedule_id in schedule mode", () => {
    const parsed = backtestConfigSchema.parse(buildDefaults({
      scan_source: { mode: "schedule", schedule_id: "s1", scan_ids: ["x"] } as never,
    }));
    const req = toCreateRequest(parsed);
    expect(req.scan_source).toEqual({ mode: "schedule", schedule_id: "s1" });
  });
});

describe("regime multi-strategy (F1/F2/F3) config", () => {
  const base = {
    starting_capital: 10000,
    date_range_start: "2026-01-01T00:00",
    date_range_end: "2026-02-01T00:00",
    scan_source: { mode: "date_range" as const },
  };

  it("defaults all regime features off / inherit (mirrors backend)", () => {
    const r = backtestConfigSchema.safeParse(base);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.regime_filter_enabled).toBe(false);
      expect(r.data.mean_reversion_enabled).toBe(false);
      expect(r.data.strategy_cohort).toBeNull();      // inherit -> trend in backtest
      expect(r.data.mr_short_enabled).toBe(true);
      expect(r.data.mr_long_enabled).toBe(false);
      expect(r.data.mr_time_stop_minutes).toBe(120);
    }
  });

  it("accepts an enabled MR + F1 config", () => {
    const r = backtestConfigSchema.safeParse({
      ...base, regime_filter_enabled: true, session_filter_enabled: true,
      session_blocked_hours_utc: [1, 6, 7, 8], mean_reversion_enabled: true,
      strategy_cohort: "mean_reversion", mr_long_enabled: true,
    });
    expect(r.success).toBe(true);
  });

  it("rejects blocked+allowed session hours together", () => {
    const r = backtestConfigSchema.safeParse({
      ...base, session_blocked_hours_utc: [1], session_allowed_hours_utc: [2],
    });
    expect(r.success).toBe(false);
  });

  it("rejects an inverted BTC vol band", () => {
    const r = backtestConfigSchema.safeParse({
      ...base, btc_vol_min_threshold: 3, btc_vol_max_threshold: 1,
    });
    expect(r.success).toBe(false);
  });

  it("rejects MR enabled with no direction", () => {
    const r = backtestConfigSchema.safeParse({
      ...base, mean_reversion_enabled: true, mr_short_enabled: false, mr_long_enabled: false,
    });
    expect(r.success).toBe(false);
  });

  it("buildDefaults supplies every regime field", () => {
    const d = buildDefaults();
    expect(d.regime_filter_enabled).toBe(false);
    expect(d.strategy_cohort).toBeNull();
    expect(d.mr_leverage).toBe(10);
    expect(d.mr_capital_pct).toBe(2);
  });
});
