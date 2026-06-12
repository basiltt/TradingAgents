import { describe, it, expect } from "vitest";
import {
  validateCooloff,
  cooloffConfigsValid,
  cooloffGateValid,
  collectCooloffGateErrors,
} from "../cooloffValidation";
import type { AutoTradeConfig } from "@/api/client";

/**
 * Build an AutoTradeConfig with all four cool-off tiers OFF by default. Tests
 * override only the cool-off fields under test — every other field is irrelevant
 * to validateCooloff, which reads only the cool-off enabled/minutes pairs.
 */
function cfg(overrides: Partial<AutoTradeConfig> = {}): AutoTradeConfig {
  return {
    account_id: "acct-1",
    cooloff_on_success_enabled: false,
    cooloff_on_success_minutes: null,
    cooloff_on_failure_enabled: false,
    cooloff_on_failure_minutes: null,
    cooloff_on_double_success_enabled: false,
    cooloff_on_double_success_minutes: null,
    cooloff_on_double_failure_enabled: false,
    cooloff_on_double_failure_minutes: null,
    ...overrides,
  } as AutoTradeConfig;
}

describe("validateCooloff", () => {
  it("returns no errors when all tiers are off (the default)", () => {
    expect(validateCooloff(cfg())).toEqual([]);
  });

  it("ignores the duration of a disabled tier (off + null is valid)", () => {
    // A disabled tier with a leftover/blank duration must never error — only
    // ENABLED tiers require a duration.
    expect(validateCooloff(cfg({ cooloff_on_success_minutes: null }))).toEqual([]);
  });

  it("flags a DISABLED tier whose leftover duration is out of range (backend field constraint)", () => {
    // The backend field constraint Field(None, ge=1, le=43200) rejects ANY non-null
    // out-of-range minutes even on a disabled tier, so a stale over-max value (from
    // localStorage / an imported config) must be flagged rather than 422 on submit.
    const errors = validateCooloff(
      cfg({ cooloff_on_failure_enabled: false, cooloff_on_failure_minutes: 99999 }),
    );
    expect(errors).toHaveLength(1);
    expect(errors[0].tier).toBe("Failure cool-off");
  });

  it("does NOT flag a disabled tier with an in-range leftover duration (kept for re-enable)", () => {
    expect(
      validateCooloff(cfg({ cooloff_on_failure_enabled: false, cooloff_on_failure_minutes: 60 })),
    ).toEqual([]);
  });

  it("flags an enabled tier with a null duration", () => {
    const errors = validateCooloff(
      cfg({ cooloff_on_success_enabled: true, cooloff_on_success_minutes: null }),
    );
    expect(errors).toHaveLength(1);
    expect(errors[0].tier).toBe("Success cool-off");
  });

  it("flags an enabled tier below the 1-minute minimum", () => {
    const errors = validateCooloff(
      cfg({ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 0 }),
    );
    expect(errors).toHaveLength(1);
    expect(errors[0].tier).toBe("Failure cool-off");
  });

  it("flags an enabled tier above the 43200-minute (30-day) maximum", () => {
    const errors = validateCooloff(
      cfg({
        cooloff_on_double_failure_enabled: true,
        cooloff_on_double_failure_minutes: 43201,
      }),
    );
    expect(errors).toHaveLength(1);
    expect(errors[0].tier).toBe("Double-failure cool-off");
  });

  it("accepts the boundary durations 1 and 43200", () => {
    expect(
      validateCooloff(cfg({ cooloff_on_success_enabled: true, cooloff_on_success_minutes: 1 })),
    ).toEqual([]);
    expect(
      validateCooloff(
        cfg({ cooloff_on_success_enabled: true, cooloff_on_success_minutes: 43200 }),
      ),
    ).toEqual([]);
  });

  it("accumulates one error per invalid enabled tier", () => {
    const errors = validateCooloff(
      cfg({
        cooloff_on_success_enabled: true,
        cooloff_on_success_minutes: null,
        cooloff_on_failure_enabled: true,
        cooloff_on_failure_minutes: -5,
        cooloff_on_double_success_enabled: true,
        cooloff_on_double_success_minutes: 60, // valid → no error
        cooloff_on_double_failure_enabled: true,
        cooloff_on_double_failure_minutes: 999999, // too large
      }),
    );
    expect(errors.map((e) => e.tier).sort()).toEqual([
      "Double-failure cool-off",
      "Failure cool-off",
      "Success cool-off",
    ]);
  });
});

describe("cooloffConfigsValid", () => {
  it("is true for an empty list of configs", () => {
    expect(cooloffConfigsValid([])).toBe(true);
  });

  it("is true when every config's enabled tiers are valid", () => {
    expect(
      cooloffConfigsValid([
        cfg(),
        cfg({ cooloff_on_success_enabled: true, cooloff_on_success_minutes: 30 }),
      ]),
    ).toBe(true);
  });

  it("is false when any single config has an invalid enabled tier", () => {
    expect(
      cooloffConfigsValid([
        cfg(),
        cfg({ cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: null }),
      ]),
    ).toBe(false);
  });
});

describe("cooloffGateValid (host-page Launch/Save gate)", () => {
  it("ignores draft rows with no account selected (account_id empty)", () => {
    // A draft row with an enabled-but-blank tier but NO account must not block the
    // button — it isn't submittable. Only account-bound rows gate.
    const draft = cfg({
      account_id: "",
      cooloff_on_failure_enabled: true,
      cooloff_on_failure_minutes: null,
    });
    expect(cooloffGateValid([draft])).toBe(true);
  });

  it("blocks when an ACCOUNT-BOUND row has an invalid enabled tier", () => {
    const bound = cfg({
      account_id: "acct-9",
      cooloff_on_success_enabled: true,
      cooloff_on_success_minutes: null,
    });
    expect(cooloffGateValid([bound])).toBe(false);
  });

  it("is true for an empty list and for all-valid account-bound rows", () => {
    expect(cooloffGateValid([])).toBe(true);
    expect(
      cooloffGateValid([
        cfg({ account_id: "a", cooloff_on_success_enabled: true, cooloff_on_success_minutes: 30 }),
      ]),
    ).toBe(true);
  });
});

describe("collectCooloffGateErrors", () => {
  it("returns errors only from account-bound configs", () => {
    const errs = collectCooloffGateErrors([
      // draft, no account → excluded even though invalid
      cfg({ account_id: "", cooloff_on_success_enabled: true, cooloff_on_success_minutes: null }),
      // account-bound, invalid → included
      cfg({ account_id: "a", cooloff_on_failure_enabled: true, cooloff_on_failure_minutes: 0 }),
    ]);
    expect(errs).toHaveLength(1);
    expect(errs[0].tier).toBe("Failure cool-off");
  });

  it("returns an empty list when every account-bound config is valid", () => {
    expect(
      collectCooloffGateErrors([
        cfg({ account_id: "a" }),
        cfg({ account_id: "b", cooloff_on_success_enabled: true, cooloff_on_success_minutes: 15 }),
      ]),
    ).toEqual([]);
  });
});
