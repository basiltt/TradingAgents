import * as React from "react";
import { Controller, type Control, type FieldPath } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import type { BacktestConfigFormValues } from "../configSchema";

/* ----------------------------- small field helpers ----------------------------- */

interface NumFieldProps {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  step?: string;
  placeholder?: string;
  nullable?: boolean;
  error?: string;
  /** Small grey help line under the field (e.g. what it maps to in the scanner config). */
  hint?: string;
}

/** A grey one-line help text rendered under a field's input. */
export function Hint({ text }: { text?: string }) {
  if (!text) return null;
  return <span className="text-[0.68rem] leading-tight text-[var(--neu-text-muted)]">{text}</span>;
}

export function NumberField({ control, name, label, step, placeholder, nullable, error, hint }: NumFieldProps) {
  const errorId = `${name}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Controller
        control={control}
        name={name}
        render={({ field }) => (
          <Input
            id={name}
            type="number"
            step={step ?? "any"}
            placeholder={placeholder}
            value={field.value == null ? "" : String(field.value)}
            onChange={(e) => {
              const v = e.target.value;
              // Clearing a NULLABLE field → null (an explicit "unset"). Clearing a
              // NON-nullable field → undefined, NOT "" — an empty string coerces to 0
              // via z.coerce.number(), which for cost/rate fields (fee, slippage)
              // silently means "zero-cost trading" and inflates PnL. undefined lets
              // the schema's .default() restore the production value on submit.
              if (v === "") field.onChange(nullable ? null : undefined);
              else field.onChange(v);
            }}
            onBlur={field.onBlur}
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
          />
        )}
      />
      <Hint text={hint} />
      {error ? (
        <span id={errorId} className="text-[0.72rem] text-[var(--neu-danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

interface SelectFieldProps {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  options: Array<{ value: string; label: string }>;
  /** Map the empty-string option to null on change (for nullable enum fields). */
  emptyToNull?: boolean;
  hint?: string;
  error?: string;
}

export function SelectField({ control, name, label, options, emptyToNull, hint, error }: SelectFieldProps) {
  const errorId = `${name}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Controller
        control={control}
        name={name}
        render={({ field }) => (
          <select
            id={name}
            value={String(field.value ?? "")}
            onChange={(e) => {
              const v = e.target.value;
              field.onChange(emptyToNull && v === "" ? null : v);
            }}
            onBlur={field.onBlur}
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            className="neu-input-base neu-focus-ring h-11 w-full rounded-[var(--neu-radius-md)] px-3 text-sm text-[var(--neu-text-strong)]"
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      />
      <Hint text={hint} />
      {error ? (
        <span id={errorId} className="text-[0.72rem] text-[var(--neu-danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

interface CheckFieldProps {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  hint?: string;
}

export function CheckField({ control, name, label, hint }: CheckFieldProps) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <label className="flex cursor-pointer items-start gap-2.5 py-1 text-[0.85rem] text-[var(--neu-text-strong)]">
          <Checkbox
            checked={!!field.value}
            onCheckedChange={(checked) => field.onChange(checked === true)}
            className="mt-0.5"
          />
          <span className="flex flex-col">
            {label}
            <Hint text={hint} />
          </span>
        </label>
      )}
    />
  );
}

/** A scanner-style ON/OFF toggle that reveals a number input only when enabled.
 * Mirrors the Scheduled Market Scan auto-trade "ToggleRow" pattern: turning the
 * switch off sets the field to null (disabled); turning it on seeds `enabledValue`
 * and shows the input. Keeps the backtest form visually 1:1 with the scanner. */
export function ToggleNumberField({
  control,
  name,
  title,
  description,
  enabledValue,
  unit,
  min,
  max,
  step,
  error,
}: {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  title: string;
  description?: string;
  /** Value written when the toggle is switched on (the scanner's default). */
  enabledValue: number;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  error?: string;
}) {
  const revealId = `${name}-reveal`;
  const errorId = `${name}-error`;
  const inputRef = React.useRef<HTMLInputElement>(null);
  const justEnabled = React.useRef(false);
  // Move focus to the revealed input the render after the toggle is switched on, so
  // keyboard/SR users land on the field they just exposed instead of having to hunt
  // for it. Only fires on the off→on transition the user initiated (justEnabled).
  React.useEffect(() => {
    if (justEnabled.current) {
      justEnabled.current = false;
      inputRef.current?.focus();
    }
  });
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => {
        const enabled = field.value != null && Number(field.value) > 0;
        return (
          <div className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
            <div className="flex items-start justify-between gap-3">
              <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
                <Checkbox
                  checked={enabled}
                  aria-expanded={enabled}
                  aria-controls={enabled ? revealId : undefined}
                  onCheckedChange={(checked) => {
                    const on = checked === true;
                    if (on) justEnabled.current = true;
                    field.onChange(on ? enabledValue : null);
                  }}
                  className="mt-0.5"
                />
                <span className="flex flex-col">
                  {title}
                  {description ? <Hint text={description} /> : null}
                </span>
              </label>
              {enabled ? (
                <div id={revealId} className="flex shrink-0 flex-col items-end gap-1">
                  <div className="flex items-center gap-1.5">
                    <Input
                      ref={inputRef}
                      type="number"
                      min={min}
                      max={max}
                      step={step ?? "any"}
                      aria-label={unit ? `${title} (${unit})` : title}
                      aria-invalid={!!error}
                      aria-describedby={error ? errorId : undefined}
                      value={field.value == null ? "" : String(field.value)}
                      onChange={(e) => {
                        const v = e.target.value;
                        field.onChange(v === "" ? enabledValue : v);
                      }}
                      onBlur={field.onBlur}
                      className="h-10 w-20 text-center"
                    />
                    {unit ? <span className="text-[0.72rem] text-[var(--neu-text-muted)]">{unit}</span> : null}
                  </div>
                  {error ? (
                    <span id={errorId} className="text-[0.72rem] text-[var(--neu-danger)]">
                      {error}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        );
      }}
    />
  );
}

/** A comma/space-separated text field that maps to a number[] | null form value of
 * UTC hours (0-23) — for the F1 session blocked/allowed hours. Empty → null. */
export function HoursListField({
  control,
  name,
  label,
  placeholder,
  error,
}: {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  placeholder?: string;
  error?: string;
}) {
  const errorId = `${name}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Controller
        control={control}
        name={name}
        render={({ field }) => {
          const arr = Array.isArray(field.value) ? (field.value as number[]) : [];
          return (
            <Input
              id={name}
              type="text"
              placeholder={placeholder ?? "e.g. 1, 6, 7, 8"}
              defaultValue={arr.join(", ")}
              aria-invalid={!!error}
              aria-describedby={error ? errorId : undefined}
              onBlur={(e) => {
                const hours = Array.from(
                  new Set(
                    e.target.value
                      .split(/[\s,]+/)
                      .map((s) => parseInt(s.trim(), 10))
                      .filter((n) => Number.isInteger(n) && n >= 0 && n <= 23),
                  ),
                ).sort((a, b) => a - b);
                field.onChange(hours.length ? hours : null);
                field.onBlur();
              }}
            />
          );
        }}
      />
      {error ? (
        <span id={errorId} className="text-[0.72rem] text-[var(--neu-danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/** A comma/space-separated text field that maps to a string[] | null form value
 * (used for symbol blacklist/whitelist). Empty input → null. */
export function SymbolListField({
  control,
  name,
  label,
  placeholder,
  error,
  hint,
}: {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  placeholder?: string;
  error?: string;
  hint?: string;
}) {
  const errorId = `${name}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Controller
        control={control}
        name={name}
        render={({ field }) => {
          const arr = Array.isArray(field.value) ? (field.value as string[]) : [];
          return (
            <Input
              id={name}
              type="text"
              placeholder={placeholder ?? "e.g. BTCUSDT, ETHUSDT"}
              defaultValue={arr.join(", ")}
              aria-invalid={!!error}
              aria-describedby={error ? errorId : undefined}
              onBlur={(e) => {
                // Dedupe so repeated symbols don't inflate the count past the
                // backend's 200-element cap when there are <200 unique symbols.
                const symbols = Array.from(
                  new Set(
                    e.target.value
                      .split(/[\s,]+/)
                      .map((s) => s.trim().toUpperCase())
                      .filter(Boolean),
                  ),
                );
                field.onChange(symbols.length ? symbols : null);
                field.onBlur();
              }}
            />
          );
        }}
      />
      <Hint text={hint} />
      {error ? (
        <span id={errorId} className="text-[0.72rem] text-[var(--neu-danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  /** Optional one-line description shown under the section title. */
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4">
      <h3 className="text-sm font-bold text-[var(--neu-text-strong)]">{title}</h3>
      {subtitle ? (
        <p className="mt-1 text-[0.72rem] leading-snug text-[var(--neu-text-muted)]">{subtitle}</p>
      ) : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";
