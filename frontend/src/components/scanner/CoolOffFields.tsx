import { useId, useState } from "react";
import { Input } from "@/components/ui/input";
import { type AutoTradeConfig } from "@/api/client";
import { NeuSwitch } from "@/design-system/neumorphism";
import {
  COOLOFF_TIERS,
  COOLOFF_MAX_MINUTES,
  type CooloffTierDef,
  tierMinutes,
  tierMinutesValid,
} from "./cooloffTiers";

const SECTION_CLASS =
  "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4 border-none shadow-[var(--shadow-card)]";

const MAX_HOURS = COOLOFF_MAX_MINUTES / 60; // 720

type Unit = "min" | "hr";

interface Props {
  config: AutoTradeConfig;
  onChange: (partial: Partial<AutoTradeConfig>) => void;
}

/** Convert a UI value+unit to canonical integer minutes (rounded, NOT clamped).
 * Out-of-range values are stored as-is so the inline error + Launch/Save gate flag
 * them transparently — silently snapping a typed value to the max would change the
 * user's intent without telling them (a money-app anti-pattern). */
function toMinutes(value: number, unit: Unit): number {
  return Math.round(unit === "hr" ? value * 60 : value);
}

/** Display the stored minutes in the selected unit (trimmed hours, full-precision minutes). */
function fromMinutes(minutes: number, unit: Unit): string {
  if (unit === "hr") {
    const h = minutes / 60;
    return Number.isInteger(h) ? String(h) : h.toFixed(2).replace(/\.?0+$/, "");
  }
  return String(minutes);
}

/**
 * Cool Off Time config — 4 optional pause tiers per account, all default-off.
 * Mounted inside the shared AutoTradeSection card, so it appears on BOTH the manual
 * Market Scan and the Scheduled Market Scan forms. Minutes are the canonical stored
 * unit; the Min/Hr selector is sticky per-card edit state (FR-021, DS24).
 */
export function CoolOffFields({ config, onChange }: Props) {
  const errId = useId();
  // Sticky per-tier unit. Initialise to Hr when the stored value is a clean
  // multiple of 60 (and >= 60), else Min — then the user's choice persists.
  const [units, setUnits] = useState<Record<string, Unit>>(() => {
    const initial: Record<string, Unit> = {};
    for (const t of COOLOFF_TIERS) {
      const m = tierMinutes(config, t);
      initial[t.key] = m != null && m >= 60 && m % 60 === 0 ? "hr" : "min";
    }
    return initial;
  });

  // Raw, in-progress input text per tier. While a tier's text is being edited we
  // render this verbatim (so "1." or "1.5" survive a keystroke) and only reformat
  // from canonical minutes when the field is NOT being actively edited. This stops
  // the controlled value from snapping mid-type (e.g. dropping a trailing ".") and
  // silently storing a wrong number. null = "not editing → show canonical".
  const [drafts, setDrafts] = useState<Record<string, string | null>>({});

  const setUnit = (key: string, unit: Unit) =>
    setUnits((prev) => ({ ...prev, [key]: unit }));

  const renderTier = (t: CooloffTierDef) => {
    const enabled = !!config[t.enabledField];
    const minutes = tierMinutes(config, t);
    const unit = units[t.key];
    const max = unit === "hr" ? MAX_HOURS : COOLOFF_MAX_MINUTES;
    const draft = drafts[t.key];
    const displayVal =
      draft != null ? draft : minutes != null ? fromMinutes(minutes, unit) : "";
    const invalid = enabled && !tierMinutesValid(minutes);
    const tierErrId = `${errId}-${t.key}`;

    return (
      <div key={t.key} className="flex items-start gap-3">
        <NeuSwitch
          checked={enabled}
          onChange={(v: boolean) => {
            // Clear any in-progress (unblurred) draft on enable/disable so the input
            // re-renders the canonical stored value rather than a stale edit.
            setDrafts((d) => ({ ...d, [t.key]: null }));
            onChange({
              [t.enabledField]: v,
              // Enable: apply a sensible default when none is stored. Disable: keep an
              // IN-RANGE value (convenience for re-enable) but NULL an out-of-range one
              // — the backend field rejects any non-null out-of-range minutes even for a
              // disabled tier, and the gate (which skips disabled tiers) wouldn't catch
              // it, so a stale over-max value must not survive a disable.
              [t.minutesField]: v
                ? (minutes ?? t.defaultMinutes)
                : tierMinutesValid(minutes)
                  ? minutes
                  : null,
            } as Partial<AutoTradeConfig>);
          }}
          className="p-0 gap-0 shrink-0 mt-0.5"
          ariaLabel={t.title}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-[var(--neu-text-strong)]">{t.title}</p>
          <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">{t.desc}</p>
          {enabled && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Input
                type="number"
                inputMode="decimal"
                min={unit === "hr" ? 0.1 : 1}
                max={max}
                step={unit === "hr" ? 0.5 : 1}
                value={displayVal}
                aria-label={`${t.title} duration`}
                aria-invalid={invalid}
                aria-describedby={invalid ? tierErrId : undefined}
                onChange={(e) => {
                  const text = e.target.value;
                  setDrafts((d) => ({ ...d, [t.key]: text }));
                  const raw = parseFloat(text);
                  if (text.trim() === "" || Number.isNaN(raw) || raw <= 0) {
                    onChange({ [t.minutesField]: null } as Partial<AutoTradeConfig>);
                    return;
                  }
                  onChange({ [t.minutesField]: toMinutes(raw, unit) } as Partial<AutoTradeConfig>);
                }}
                onBlur={() => setDrafts((d) => ({ ...d, [t.key]: null }))}
                className="w-24 h-9"
              />
              <div role="group" aria-label={`${t.title} duration unit`} className="flex gap-1">
                {(["min", "hr"] as Unit[]).map((u) => (
                  <button
                    key={u}
                    type="button"
                    aria-pressed={unit === u}
                    onClick={() => {
                      // Switching unit: drop any in-progress draft so the field
                      // re-renders the canonical value in the new unit.
                      setDrafts((d) => ({ ...d, [t.key]: null }));
                      setUnit(t.key, u);
                    }}
                    className={
                      "px-2.5 py-1 text-[11px] rounded-full border " +
                      (unit === u
                        ? "border-sky-500/40 bg-sky-500/[0.12] text-sky-300"
                        : "border-[var(--neu-stroke-soft)] text-[var(--neu-text-muted)]")
                    }
                  >
                    {u === "min" ? "Min" : "Hr"}
                  </button>
                ))}
              </div>
              {invalid && (
                <span id={tierErrId} className="text-[11px] text-[var(--neu-danger)]">
                  Enter 1–{COOLOFF_MAX_MINUTES}m{unit === "hr" ? ` (≤ ${MAX_HOURS}h)` : ""}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={SECTION_CLASS}>
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        Cool Off Time
      </div>
      <p className="mb-3 text-[11px] leading-5 text-[var(--neu-text-muted)]">
        Pause this account&apos;s auto-trading for a set time after a cycle&apos;s outcome.
        All off by default. Account-specific.
      </p>

      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
        Single trade
      </div>
      <div className="space-y-3">{COOLOFF_TIERS.slice(0, 2).map(renderTier)}</div>

      <div className="mb-2 mt-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
        Win / loss streak
      </div>
      <div className="space-y-3">{COOLOFF_TIERS.slice(2, 4).map(renderTier)}</div>
    </div>
  );
}
