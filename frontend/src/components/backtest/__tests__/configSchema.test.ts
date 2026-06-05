import { describe, it, expect } from "vitest";
import {
  backtestConfigSchema,
  scanSourceSchema,
  buildDefaults,
  toCreateRequest,
} from "../configSchema";

describe("scanSourceSchema", () => {
  it("requires schedule_id in schedule mode", () => {
    expect(scanSourceSchema.safeParse({ mode: "schedule" }).success).toBe(false);
    expect(
      scanSourceSchema.safeParse({ mode: "schedule", schedule_id: "s1" }).success,
    ).toBe(true);
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
  it("parses a minimal valid config and applies defaults", () => {
    const result = backtestConfigSchema.safeParse({
      starting_capital: 10000,
      date_range_start: "2026-01-01T00:00",
      date_range_end: "2026-02-01T00:00",
      scan_source: { mode: "date_range" },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.simulation_interval).toBe("1h");
      expect(result.data.leverage).toBe(1);
      expect(result.data.skip_if_positions_open).toBe(true);
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
});
