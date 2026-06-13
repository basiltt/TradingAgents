import { Controller, type Control, type FieldPath } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Hint } from "./fields";
import type { BacktestConfigFormValues } from "../configSchema";

interface ToggleNumberPairFieldProps {
  control: Control<BacktestConfigFormValues>;
  /** The boolean `_enabled` field the checkbox drives. */
  enabledName: FieldPath<BacktestConfigFormValues>;
  /** The numeric `_minutes` field revealed when enabled. */
  valueName: FieldPath<BacktestConfigFormValues>;
  title: string;
  description?: string;
  /** Seeded into the value field when toggled on (if currently null/empty). The
   *  schema refines `enabled ⇒ minutes != null`, so seeding is required. */
  enabledValue: number;
  unit?: string;
  min?: number;
  max?: number;
  error?: string;
}

/** A reveal-when-on toggle for a SEPARATE boolean + value field pair (e.g. the
 *  cool-off tiers, where `_enabled` and `_minutes` are distinct schema fields).
 *  The checkbox owns the boolean; the numeric input appears inline only when on,
 *  seeding a sensible default so the form stays valid. Mirrors ToggleNumberField's
 *  visual structure, which uses a single nullable field instead. */
export function ToggleNumberPairField({
  control,
  enabledName,
  valueName,
  title,
  description,
  enabledValue,
  unit,
  min,
  max,
  error,
}: ToggleNumberPairFieldProps) {
  return (
    <div className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
      <Controller
        control={control}
        name={enabledName}
        render={({ field: enabledField }) => {
          const enabled = enabledField.value === true;
          return (
            <Controller
              control={control}
              name={valueName}
              render={({ field: valueField }) => (
                <div className="flex items-start justify-between gap-3">
                  <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
                    <Checkbox
                      checked={enabled}
                      onCheckedChange={(checked) => {
                        const on = checked === true;
                        enabledField.onChange(on);
                        // Seed a default so the schema's "enabled ⇒ minutes != null" holds.
                        if (on && (valueField.value == null || valueField.value === "")) {
                          valueField.onChange(enabledValue);
                        }
                      }}
                      className="mt-0.5"
                    />
                    <span className="flex flex-col">
                      {title}
                      {description ? <Hint text={description} /> : null}
                    </span>
                  </label>
                  {enabled ? (
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="number"
                          min={min}
                          max={max}
                          step="any"
                          value={valueField.value == null ? "" : String(valueField.value)}
                          onChange={(e) => {
                            const v = e.target.value;
                            valueField.onChange(v === "" ? null : v);
                          }}
                          onBlur={valueField.onBlur}
                          aria-invalid={!!error}
                          className="h-10 w-20 text-center"
                        />
                        {unit ? <span className="text-[0.72rem] text-[var(--neu-text-muted)]">{unit}</span> : null}
                      </div>
                      {error ? <span className="text-[0.72rem] text-[var(--neu-danger)]">{error}</span> : null}
                    </div>
                  ) : null}
                </div>
              )}
            />
          );
        }}
      />
    </div>
  );
}
