import { type AutoTradeConfig } from "@/api/client";
import {
  COOLOFF_TIERS,
  COOLOFF_MIN_MINUTES,
  COOLOFF_MAX_MINUTES,
  tierMinutes,
  tierMinutesValid,
} from "./cooloffTiers";

const TIER_LABELS: Record<string, string> = {
  success: "Success cool-off",
  failure: "Failure cool-off",
  double_success: "Double-success cool-off",
  double_failure: "Double-failure cool-off",
};

export interface CooloffValidationError {
  tier: string;
  message: string;
}

/**
 * Validate the 4 cool-off tiers of one AutoTradeConfig. Mirrors the backend's TWO
 * checks: (1) the model validator — an ENABLED tier requires a duration; and (2) the
 * field constraint `Field(None, ge=1, le=43200)` — ANY non-null minutes (even on a
 * disabled tier) must be in [1, 43200], or the backend 422s on a field the disabled
 * UI doesn't show. Returns the list of errors (empty = valid). Shared by CoolOffFields
 * (inline error) and the host pages (Save/Launch disable gate) so they never diverge (DS15).
 */
export function validateCooloff(config: AutoTradeConfig): CooloffValidationError[] {
  const errors: CooloffValidationError[] = [];
  for (const tier of COOLOFF_TIERS) {
    const enabled = !!config[tier.enabledField];
    const minutes = tierMinutes(config, tier);
    const label = TIER_LABELS[tier.key] ?? tier.key;
    if (enabled && !tierMinutesValid(minutes)) {
      // Enabled tier: must have a valid duration (null/blank or out-of-range → error).
      errors.push({
        tier: label,
        message: `${label} needs a duration of ${COOLOFF_MIN_MINUTES}–${COOLOFF_MAX_MINUTES} minutes.`,
      });
    } else if (!enabled && minutes != null && !tierMinutesValid(minutes)) {
      // Disabled tier: a leftover out-of-range value still fails the backend field
      // constraint, so flag it (the backend would 422 on submit otherwise).
      errors.push({
        tier: label,
        message: `${label} has an out-of-range duration (${COOLOFF_MIN_MINUTES}–${COOLOFF_MAX_MINUTES} minutes); clear or fix it.`,
      });
    }
  }
  return errors;
}

/** True if every enabled cool-off tier of every config has a valid duration. */
export function cooloffConfigsValid(configs: AutoTradeConfig[]): boolean {
  return configs.every((c) => validateCooloff(c).length === 0);
}

/**
 * Host-page gate predicate: are all ACCOUNT-BOUND configs' cool-off settings valid?
 *
 * The scanner pages keep draft rows that may not yet have an account selected
 * (account_id === ""); those are not submittable and must not block the Launch/Save
 * button. This bakes the `account_id` filter into one tested seam so both
 * ScannerPage and ScheduledScansPage share identical gate logic (no inline drift).
 */
export function cooloffGateValid(configs: AutoTradeConfig[]): boolean {
  return cooloffConfigsValid(configs.filter((c) => c.account_id));
}

/** All cool-off validation errors across the account-bound configs (for the
 * Launch/Save handler's alert/toast). Empty ⇒ the gate is satisfied. */
export function collectCooloffGateErrors(configs: AutoTradeConfig[]): CooloffValidationError[] {
  return configs.filter((c) => c.account_id).flatMap((c) => validateCooloff(c));
}
