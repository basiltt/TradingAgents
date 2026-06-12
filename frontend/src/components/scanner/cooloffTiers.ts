/**
 * Single source of truth for the four Cool Off Time tiers.
 *
 * Consumed by CoolOffFields (the editor), cooloffValidation (the Launch/Save gate),
 * and the backtest configSchema (cross-field Zod refine) so the tier list, its
 * field-name pairs, and the duration bounds can never drift between the three.
 *
 * The field-name types are narrowed to template-literal unions of the actual
 * AutoTradeConfig keys (not the whole `keyof`), so `config[tier.minutesField]`
 * resolves to exactly `number | null | undefined` with NO cast, and mispairing a
 * boolean `_enabled` key into a `minutesField` slot is a compile error.
 */
import type { AutoTradeConfig, CooloffReason } from "@/api/client";

/** Re-export so cool-off UI modules can import the reason union from one place
 * alongside the tier descriptors. Defined in api/client.ts (the wire-type layer). */
export type { CooloffReason };

export type CooloffEnabledKey = `cooloff_on_${CooloffReason}_enabled`;
export type CooloffMinutesKey = `cooloff_on_${CooloffReason}_minutes`;

/** Canonical duration bounds, identical to the backend (validate_cooloff /
 * AutoTradeConfig CHECK constraint) and the DB CHECK (1..43200 minutes = 30 days). */
export const COOLOFF_MIN_MINUTES = 1;
export const COOLOFF_MAX_MINUTES = 43200; // 30 days

export interface CooloffTierDef {
  key: CooloffReason;
  enabledField: CooloffEnabledKey;
  minutesField: CooloffMinutesKey;
  /** Editor heading. */
  title: string;
  /** Editor sub-text. */
  desc: string;
  /** Duration applied (in minutes) when the tier is first enabled with no prior value. */
  defaultMinutes: number;
}

export const COOLOFF_TIERS: CooloffTierDef[] = [
  {
    key: "success",
    enabledField: "cooloff_on_success_enabled",
    minutesField: "cooloff_on_success_minutes",
    title: "After a win",
    desc: "Pause this account after a winning cycle.",
    defaultMinutes: 30,
  },
  {
    key: "failure",
    enabledField: "cooloff_on_failure_enabled",
    minutesField: "cooloff_on_failure_minutes",
    title: "After a loss",
    desc: "Pause this account after a losing cycle.",
    defaultMinutes: 60,
  },
  {
    key: "double_success",
    enabledField: "cooloff_on_double_success_enabled",
    minutesField: "cooloff_on_double_success_minutes",
    title: "After 2 wins in a row",
    desc: "Pause after two consecutive winning cycles.",
    defaultMinutes: 60,
  },
  {
    key: "double_failure",
    enabledField: "cooloff_on_double_failure_enabled",
    minutesField: "cooloff_on_double_failure_minutes",
    title: "After 2 losses in a row",
    desc: "Pause after two consecutive losing cycles.",
    defaultMinutes: 120,
  },
];

/** Read a tier's stored duration off a config with no cast (the narrowed key type
 * guarantees a `number | null | undefined` result). */
export function tierMinutes(
  config: AutoTradeConfig,
  tier: CooloffTierDef,
): number | null | undefined {
  return config[tier.minutesField];
}

/** A tier's stored duration is valid iff present and within [MIN, MAX]. Shared by
 * the editor's inline-error state and the Launch/Save validation gate so they
 * never disagree (DS15). */
export function tierMinutesValid(minutes: number | null | undefined): boolean {
  return minutes != null && minutes >= COOLOFF_MIN_MINUTES && minutes <= COOLOFF_MAX_MINUTES;
}
