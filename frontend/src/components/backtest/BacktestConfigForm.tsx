import * as React from "react";
import { useForm, Controller, type Control, type FieldPath } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import type { DashboardCard } from "@/api/client";
import type { BacktestCreateRequest } from "./types";
import {
  backtestConfigSchema,
  buildDefaults,
  toCreateRequest,
  type BacktestConfigFormValues,
} from "./configSchema";
import { loadDraft, saveDraft, type BacktestDraft } from "./backtestDraft";

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
function Hint({ text }: { text?: string }) {
  if (!text) return null;
  return <span className="text-[0.68rem] leading-tight text-[var(--neu-text-muted)]">{text}</span>;
}

function NumberField({ control, name, label, step, placeholder, nullable, error, hint }: NumFieldProps) {
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
}

function SelectField({ control, name, label, options, emptyToNull, hint }: SelectFieldProps) {
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
    </div>
  );
}

interface CheckFieldProps {
  control: Control<BacktestConfigFormValues>;
  name: FieldPath<BacktestConfigFormValues>;
  label: string;
  hint?: string;
}

function CheckField({ control, name, label, hint }: CheckFieldProps) {
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

/** A comma/space-separated text field that maps to a number[] | null form value of
 * UTC hours (0-23) — for the F1 session blocked/allowed hours. Empty → null. */
function HoursListField({
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
function SymbolListField({
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

function Section({
  title,
  subtitle,
  children,
  defaultOpen = true,
  forceOpen = false,
}: {
  title: string;
  /** Optional one-line description shown under the section title when expanded. */
  subtitle?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  /** When true (e.g. the section contains a validation error), force it open. */
  forceOpen?: boolean;
}) {
  // Initialize open from defaultOpen OR an initial forceOpen so a section mounted
  // already-forced (e.g. a seeded form that fails validation immediately) starts
  // open — matching the original mount-time effect behavior.
  const [open, setOpen] = React.useState(defaultOpen || forceOpen);
  // AI-CONTEXT: A failed submit inside a collapsed section must reveal its errors.
  // We open on the rising edge of `forceOpen` using React's "adjust state during
  // render when a prop changes" pattern rather than a setState-in-effect
  // (react-hooks/set-state-in-effect). Tracking the previous value preserves the
  // original semantics: only the false→true transition forces it open, so the user
  // can still manually collapse the section afterward while forceOpen stays true.
  const [prevForceOpen, setPrevForceOpen] = React.useState(forceOpen);
  if (forceOpen !== prevForceOpen) {
    setPrevForceOpen(forceOpen);
    if (forceOpen) setOpen(true);
  }
  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-sm font-bold text-[var(--neu-text-strong)]"
        aria-expanded={open}
      >
        <span className={cn("transition-transform", open ? "rotate-90" : "")}>›</span>
        {title}
      </button>
      {open ? (
        <div className="mt-4">
          {subtitle ? (
            <p className="mb-4 text-[0.72rem] leading-snug text-[var(--neu-text-muted)]">{subtitle}</p>
          ) : null}
          {children}
        </div>
      ) : null}
    </div>
  );
}

const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";

/* --------------------------------- main form --------------------------------- */

export interface ScheduleOption {
  value: string;
  label: string;
}

export interface BacktestConfigFormProps {
  /** Pre-fill the form (e.g. "Backtest these settings" from the scanner). */
  seed?: Partial<BacktestCreateRequest>;
  /** Available schedules for the scan-source picker. */
  schedules?: ScheduleOption[];
  /** Accounts for the Replay source picker (carries ai_manager_state for the note). */
  accounts?: DashboardCard[];
  /** Called with the validated, API-ready request body. */
  onSubmit: (request: BacktestCreateRequest) => void;
  isSubmitting?: boolean;
  className?: string;
}

export function BacktestConfigForm({
  seed,
  schedules = [],
  accounts = [],
  onSubmit,
  isSubmitting = false,
  className,
}: BacktestConfigFormProps) {
  // Restore a saved draft so a user's entries survive navigating away from the
  // form and back (or a reload). An explicit `seed` (Retry / "Backtest these
  // settings") is an intentional, complete config and takes precedence over any
  // draft, so the draft is consulted ONLY when there is no seed. `base` backfills
  // any field a stale draft predates. Computed once on mount; RHF owns the values
  // thereafter.
  const initialValues = React.useMemo<BacktestConfigFormValues>(() => {
    const base = buildDefaults(seed);
    const draft = seed ? undefined : loadDraft();
    return draft ? { ...base, ...draft } : base;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time inputs only
  }, []);

  const {
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<BacktestConfigFormValues>({
    // zod v4 resolver: cast to keep RHF's generic happy across input/output types.
    resolver: zodResolver(backtestConfigSchema) as never,
    defaultValues: initialValues,
    mode: "onBlur",
  });

  // Persist every change as a draft. RHF's watch(callback) fires on subsequent
  // changes only (not on subscribe), so this saves what the user edits without
  // clobbering the restored draft on mount.
  // AI-CONTEXT: This MUST stay as watch(callback), NOT useWatch({control}). The
  // callback subscription persists drafts as a side effect WITHOUT re-rendering the
  // form; useWatch would re-render the entire (large) form on every keystroke — a
  // real perf regression for zero behavioral gain. The React Compiler can't memoize
  // watch() and therefore skips optimizing this component, which is acceptable here:
  // the form is interaction-bound, not render-bound. Disable is scoped to this line.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/incompatible-library -- intentional non-rendering RHF subscription; see note above
    const sub = watch((values) => {
      saveDraft(values as BacktestDraft);
    });
    return () => sub.unsubscribe();
  }, [watch]);

  const scanMode = watch("scan_source.mode");
  const replayAccountId = watch("scan_source.replay_account_id");
  const mrLongEnabled = watch("mr_long_enabled");
  const formRef = React.useRef<HTMLFormElement>(null);

  const submit = handleSubmit(
    (values) => {
      const parsed = backtestConfigSchema.parse(values);
      onSubmit(toCreateRequest(parsed));
    },
    () => {
      // On invalid submit, collapsed sections auto-open (forceOpen) on the next
      // render; RHF's own focus fires too early against the still-unmounted field.
      // Move focus to the first invalid control after the DOM updates.
      requestAnimationFrame(() => {
        const el = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
        el?.focus();
      });
    },
  );

  const fieldError = (path: string): string | undefined => {
    // errors is a nested object; support dotted paths for scan_source.* too.
    const parts = path.split(".");
    let node: unknown = errors;
    for (const p of parts) {
      if (node && typeof node === "object" && p in node) {
        node = (node as Record<string, unknown>)[p];
      } else {
        return undefined;
      }
    }
    if (node && typeof node === "object" && "message" in node) {
      return String((node as { message?: unknown }).message ?? "");
    }
    return undefined;
  };

  const anyError = (...paths: string[]) => paths.some((p) => !!fieldError(p));
  const closeRulesHasError = anyError(
    "max_drawdown_pct",
    "breakeven_timeout_hours",
    "max_trade_duration_hours",
    "trailing_profit_pct",
    "close_on_profit_pct",
  );
  const riskLimitsHasError = anyError(
    "max_same_direction",
    "max_same_sector",
    "max_signal_age_minutes",
    "max_price_drift_pct",
  );

  return (
    <form ref={formRef} onSubmit={submit} className={cn("flex flex-col gap-4", className)} aria-label="Backtest configuration">
      <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)]/50 bg-[var(--neu-surface-inset)]/30 px-4 py-3">
        <p className="text-[0.78rem] leading-snug text-[var(--neu-text-muted)]">
          These settings mirror your <span className="font-semibold text-[var(--neu-text)]">Scheduled Market Scan</span> auto-trade
          config (same trade-decision, close-rule, risk and strategy fields), plus
          <span className="font-semibold text-[var(--neu-text)]"> backtest-only</span> settings the live account would normally
          provide — initial balance, date range, fees, slippage and funding. Each field
          notes its equivalent. Fields marked <em>not simulated</em> have no effect here.
        </p>
      </div>

      <Section
        title="Backtest Setup (backtest-only)"
        subtitle="These exist only for backtesting — in live trading the account supplies the balance and the scanner runs continuously."
      >
        <div className={GRID}>
          <NumberField
            control={control}
            name="starting_capital"
            label="Initial Balance ($)"
            error={fieldError("starting_capital")}
            hint="Backtest-only · the starting wallet, like a live account's balance"
          />
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="date_range_start">Start</Label>
            <Controller
              control={control}
              name="date_range_start"
              render={({ field }) => (
                <Input id="date_range_start" type="datetime-local" value={String(field.value ?? "")} onChange={field.onChange} onBlur={field.onBlur} aria-invalid={!!fieldError("date_range_start")} aria-describedby={fieldError("date_range_start") ? "date_range_start-error" : undefined} />
              )}
            />
            <Hint text="Backtest-only · which historical scans to replay (from)" />
            {fieldError("date_range_start") ? (
              <span id="date_range_start-error" className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("date_range_start")}</span>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="date_range_end">End</Label>
            <Controller
              control={control}
              name="date_range_end"
              render={({ field }) => (
                <Input id="date_range_end" type="datetime-local" value={String(field.value ?? "")} onChange={field.onChange} onBlur={field.onBlur} aria-invalid={!!fieldError("date_range_end")} aria-describedby={fieldError("date_range_end") ? "date_range_end-error" : undefined} />
              )}
            />
            <Hint text="Backtest-only · which historical scans to replay (to)" />
            {fieldError("date_range_end") ? (
              <span id="date_range_end-error" className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("date_range_end")}</span>
            ) : null}
          </div>
        </div>
      </Section>

      <Section title="Signal Source (backtest-only)" subtitle="Which stored scan results feed the simulation — live trading always uses the running scanner.">
        <div className={GRID}>
          <SelectField
            control={control}
            name="scan_source.mode"
            label="Source Mode"
            hint="Backtest-only · where signals come from"
            options={[
              { value: "date_range", label: "All scans in date range" },
              { value: "schedule", label: "Specific schedule" },
              { value: "replay", label: "Replay (validate vs live)" },
            ]}
          />
          {scanMode === "schedule" ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="scan_source.schedule_id">Schedule</Label>
              <Controller
                control={control}
                name="scan_source.schedule_id"
                render={({ field }) => (
                  <select
                    id="scan_source.schedule_id"
                    value={String(field.value ?? "")}
                    onChange={field.onChange}
                    className="neu-input-base neu-focus-ring h-11 w-full rounded-[var(--neu-radius-md)] px-3 text-sm"
                  >
                    <option value="">Select…</option>
                    {schedules.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                )}
              />
              {fieldError("scan_source.schedule_id") ? (
                <span className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("scan_source.schedule_id")}</span>
              ) : null}
              {schedules.length === 0 ? (
                <span className="text-[0.72rem] text-[var(--neu-text-muted)]">
                  No schedules available — create one in Scheduled Scans, or use “All scans in date range”.
                </span>
              ) : null}
            </div>
          ) : null}
          {scanMode === "replay" ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="scan_source.replay_account_id">Replay Account</Label>
              <Controller
                control={control}
                name="scan_source.replay_account_id"
                render={({ field }) => (
                  <select
                    id="scan_source.replay_account_id"
                    value={String(field.value ?? "")}
                    onChange={field.onChange}
                    className="neu-input-base neu-focus-ring h-11 w-full rounded-[var(--neu-radius-md)] px-3 text-sm"
                  >
                    <option value="">Select…</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label} ({a.account_type})
                      </option>
                    ))}
                  </select>
                )}
              />
              {fieldError("scan_source.replay_account_id") ? (
                <span className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("scan_source.replay_account_id")}</span>
              ) : null}
              <span className="text-[0.72rem] text-[var(--neu-text-muted)]">
                Replays this account's actual scanner trades through the engine and
                compares per-cycle results — selection is pinned, so it validates the
                simulation. The Date Range below bounds which trades are replayed;
                AI-Manager-closed and non-scanner trades are excluded.
              </span>
              {(() => {
                const acct = accounts.find((a) => a.id === replayAccountId);
                return acct?.ai_manager_state != null ? (
                  <span className="text-[0.72rem] text-[var(--neu-warning,#b45309)]">
                    This account uses the AI Manager, which the backtest excludes — replay
                    fidelity is most meaningful for non-AI-Manager accounts.
                  </span>
                ) : null;
              })()}
            </div>
          ) : null}
        </div>
      </Section>

      <Section
        title="Execution Model (backtest-only)"
        subtitle="Cost + granularity assumptions the simulator uses — live trading gets these from the exchange."
      >
        <div className={GRID}>
          <SelectField control={control} name="simulation_interval" label="Simulation Interval" hint="Backtest-only · candle size the sim steps through" options={[
            { value: "5m", label: "5 minutes" },
            { value: "15m", label: "15 minutes" },
            { value: "1h", label: "1 hour" },
            { value: "4h", label: "4 hours" },
          ]} />
          <NumberField control={control} name="fee_rate_pct" label="Fee Rate (%)" hint="Backtest-only · taker fee per side (Bybit ≈ 0.055)" error={fieldError("fee_rate_pct")} />
          <NumberField control={control} name="slippage_bps" label="Slippage (bps)" hint="Backtest-only · adverse fill slippage, basis points" error={fieldError("slippage_bps")} />
          <SelectField control={control} name="funding_rate_model" label="Funding Model" hint="Backtest-only · perpetual funding cost model" options={[
            { value: "none", label: "None" },
            { value: "fixed_8h", label: "Fixed (8h)" },
          ]} />
          <NumberField control={control} name="funding_rate_fixed_pct" label="Funding Rate (%/8h)" hint="Backtest-only · used when Funding Model = Fixed" error={fieldError("funding_rate_fixed_pct")} />
        </div>
      </Section>

      <Section
        title="Trade Decisions"
        subtitle="Mirrors the scanner's auto-trade config — same field names, same meaning."
      >
        <div className={GRID}>
          <SelectField control={control} name="direction" label="Direction" hint="Scanner: Direction" options={[
            { value: "straight", label: "Straight (follow signal)" },
            { value: "reverse", label: "Reverse (invert signal)" },
          ]} />
          <NumberField control={control} name="leverage" label="Leverage" hint="Scanner: Leverage" error={fieldError("leverage")} />
          <NumberField control={control} name="capital_pct" label="Capital %" hint="Scanner: Capital % · margin per trade" error={fieldError("capital_pct")} />
          <NumberField control={control} name="take_profit_pct" label="Take profit %" hint="Scanner: Take profit %" error={fieldError("take_profit_pct")} />
          <NumberField control={control} name="stop_loss_pct" label="Stop loss %" hint="Scanner: Stop loss %" error={fieldError("stop_loss_pct")} />
          <NumberField control={control} name="min_score" label="Min score" hint="Scanner: Min score" error={fieldError("min_score")} />
          <SelectField control={control} name="confidence_filter" label="Min confidence" hint="Scanner: Min confidence" options={[
            { value: "any", label: "Any" },
            { value: "high", label: "High only" },
            { value: "moderate", label: "Moderate+" },
            { value: "low", label: "Low+" },
          ]} />
          <SelectField control={control} name="signal_sides" label="Signal sides" hint="Scanner: Signal sides" options={[
            { value: "both", label: "Both" },
            { value: "buy", label: "Buy only" },
            { value: "sell", label: "Sell only" },
          ]} />
          <NumberField control={control} name="max_trades" label="Max trades" hint="Scanner: Max trades · per scan cycle" error={fieldError("max_trades")} />
          <SelectField control={control} name="execution_mode" label="Execution mode" hint="Scanner: Execution mode" options={[
            { value: "immediate", label: "Immediate" },
            { value: "batch", label: "Batch" },
          ]} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
          <CheckField control={control} name="fill_to_max_trades" label="Fill to max trades" hint="Scanner: Fill to max trades" />
          <CheckField control={control} name="skip_if_positions_open" label="Skip if positions open" hint="Scanner: Skip if positions open" />
        </div>
      </Section>

      <Section title="Close Rules" defaultOpen={false} forceOpen={closeRulesHasError}>
        <div className={GRID}>
          <NumberField control={control} name="max_drawdown_pct" label="Max drawdown %" hint="Scanner: Max drawdown % · close cycle on equity drop" error={fieldError("max_drawdown_pct")} />
          <NumberField control={control} name="breakeven_timeout_hours" label="Close all at breakeven after (hours)" nullable hint="Scanner: Close all at breakeven after (hours)" error={fieldError("breakeven_timeout_hours")} />
          <NumberField control={control} name="max_trade_duration_hours" label="Force close after (hours)" nullable hint="Scanner: Force close after (hours) · max trade duration" error={fieldError("max_trade_duration_hours")} />
          <NumberField control={control} name="trailing_profit_pct" label="Trailing profit %" nullable hint="Scanner: Trailing profit %" error={fieldError("trailing_profit_pct")} />
          <NumberField control={control} name="close_on_profit_pct" label="Close on profit %" nullable hint="Scanner: Close on profit % · equity-rise target" error={fieldError("close_on_profit_pct")} />
        </div>
        <div className="mt-3">
          <CheckField control={control} name="smart_drawdown_close" label="Smart drawdown close" hint="Scanner: Smart drawdown close" />
        </div>
      </Section>

      <Section title="Risk Limits" defaultOpen={false} forceOpen={riskLimitsHasError}>
        <div className={GRID}>
          <NumberField control={control} name="max_same_direction" label="Max positions same direction" nullable hint="Scanner: Max positions same direction" error={fieldError("max_same_direction")} />
          <NumberField control={control} name="max_same_sector" label="Max positions same sector" nullable hint="Not simulated · sector data is live-only, no effect on results" error={fieldError("max_same_sector")} />
          <NumberField control={control} name="max_signal_age_minutes" label="Max signal age (min)" nullable hint="Scanner: Max signal age (minutes)" error={fieldError("max_signal_age_minutes")} />
          <NumberField control={control} name="max_price_drift_pct" label="Max price drift %" nullable hint="Scanner: Max price drift % · skip if price moved since scan" error={fieldError("max_price_drift_pct")} />
        </div>
      </Section>

      <Section title="Symbol Filters" defaultOpen={false} forceOpen={anyError("symbol_whitelist", "symbol_blacklist")}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SymbolListField control={control} name="symbol_whitelist" label="Whitelist (only these)" hint="Scanner: Symbol whitelist · trade only these" error={fieldError("symbol_whitelist")} />
          <SymbolListField control={control} name="symbol_blacklist" label="Blacklist (never these)" hint="Scanner: Symbol blacklist · never trade these" error={fieldError("symbol_blacklist")} />
        </div>
      </Section>

      <Section title="Target Goal" defaultOpen={false}>
        <div className={GRID}>
          <SelectField control={control} name="target_goal_type" label="Goal Type" emptyToNull hint="Scanner: Target goal · stop the cycle when reached" options={[
            { value: "", label: "None" },
            { value: "trade_count", label: "Trade count" },
            { value: "profit_pct", label: "Profit %" },
          ]} />
          <NumberField control={control} name="target_goal_value" label="Goal Value" nullable hint="Scanner: Target goal value" error={fieldError("target_goal_value")} />
        </div>
      </Section>

      <Section title="Adaptive Blacklist" defaultOpen={false} subtitle="Mirrors the scanner — auto-skip symbols whose recent win rate is poor.">
        <div className="mb-3">
          <CheckField control={control} name="adaptive_blacklist_enabled" label="Enable adaptive blacklist" hint="Scanner: Adaptive blacklist" />
        </div>
        <div className={GRID}>
          <NumberField control={control} name="adaptive_blacklist_min_trades" label="Min trades" hint="Scanner: Min trades before blacklisting" error={fieldError("adaptive_blacklist_min_trades")} />
          <NumberField control={control} name="adaptive_blacklist_max_win_rate" label="Max win rate %" hint="Scanner: Blacklist below this win rate" error={fieldError("adaptive_blacklist_max_win_rate")} />
          <NumberField control={control} name="adaptive_blacklist_lookback_hours" label="Lookback (hours)" hint="Scanner: Win-rate lookback window" error={fieldError("adaptive_blacklist_lookback_hours")} />
        </div>
      </Section>

      <Section title="Market Regime & Strategy (F1/F2/F3)" defaultOpen={false}
               forceOpen={anyError("session_blocked_hours_utc", "btc_vol_min_threshold", "mr_short_enabled")}>
        <p className="mb-3 text-[0.72rem] leading-5 text-[var(--neu-text-muted)]">
          Replay the regime features on history. All off by default. Modeling notes:
          F2-long honors mr_long_enabled (the live server-ack is bypassed — no live
          account); BTC vol uses historical klines at each scan time; MR entries fill at
          the next bar&apos;s open.
        </p>

        {/* F1 — Regime / Session Filter */}
        <div className="mb-2">
          <CheckField control={control} name="regime_filter_enabled" label="Regime / Session Filter (F1)" />
        </div>
        <div className={GRID}>
          <CheckField control={control} name="session_filter_enabled" label="Session hour filter" />
          <HoursListField control={control} name="session_blocked_hours_utc" label="Blocked UTC hours" error={fieldError("session_blocked_hours_utc")} />
          <HoursListField control={control} name="session_allowed_hours_utc" label="Allowed UTC hours (alt)" error={fieldError("session_allowed_hours_utc")} />
          <CheckField control={control} name="btc_vol_filter_enabled" label="BTC volatility band" />
          <NumberField control={control} name="btc_vol_min_threshold" label="BTC vol min (atr ratio)" nullable error={fieldError("btc_vol_min_threshold")} />
          <NumberField control={control} name="btc_vol_max_threshold" label="BTC vol max (atr ratio)" nullable error={fieldError("btc_vol_max_threshold")} />
          <SelectField control={control} name="btc_vol_interval" label="BTC vol interval" options={[
            { value: "15m", label: "15m" }, { value: "1h", label: "1h" }, { value: "4h", label: "4h" },
          ]} />
          <NumberField control={control} name="btc_vol_lookback_candles" label="BTC vol lookback" error={fieldError("btc_vol_lookback_candles")} />
        </div>

        {/* F3 — Strategy Cohort */}
        <div className="mt-4">
          <SelectField control={control} name="strategy_cohort" label="Strategy cohort (F3)" emptyToNull options={[
            { value: "", label: "Inherit (trend)" },
            { value: "trend", label: "Trend" },
            { value: "mean_reversion", label: "Mean-Reversion" },
          ]} />
        </div>

        {/* F2 — Mean-Reversion */}
        <div className="mb-2 mt-4">
          <CheckField control={control} name="mean_reversion_enabled" label="Mean-Reversion Strategy (F2)" />
        </div>
        <div className={GRID}>
          <CheckField control={control} name="mr_short_enabled" label="MR short side" />
          <CheckField control={control} name="mr_long_enabled" label="MR long side (neg. expectancy)" />
          <NumberField control={control} name="mr_leverage" label="MR leverage" error={fieldError("mr_leverage")} />
          <NumberField control={control} name="mr_capital_pct" label="MR capital / trade (%)" error={fieldError("mr_capital_pct")} />
          <NumberField control={control} name="mr_max_trades" label="MR max trades" error={fieldError("mr_max_trades")} />
          <NumberField control={control} name="mr_mean_period" label="MR mean period" error={fieldError("mr_mean_period")} />
          <SelectField control={control} name="mr_mean_interval" label="MR mean interval" options={[
            { value: "15m", label: "15m" }, { value: "1h", label: "1h" }, { value: "4h", label: "4h" },
          ]} />
          <NumberField control={control} name="mr_target_capture_pct" label="MR target capture (%)" error={fieldError("mr_target_capture_pct")} />
          <NumberField control={control} name="mr_tight_stop_pct" label="MR tight stop (%)" nullable error={fieldError("mr_tight_stop_pct")} />
          <NumberField control={control} name="mr_time_stop_minutes" label="MR time-stop (min)" error={fieldError("mr_time_stop_minutes")} />
          <NumberField control={control} name="mr_min_edge_pct" label="MR min edge (%)" error={fieldError("mr_min_edge_pct")} />
        </div>
        {mrLongEnabled ? (
          <p className="mt-2 text-[0.72rem] leading-5 text-[var(--neu-danger)]" role="note" data-testid="mr-long-danger">
            Research shows the MR long side is net-negative (≈55% win rate, −$0.57/trade).
            The backtest honors it (no live ack) precisely so you can measure that — expect
            the long-side results to confirm the negative expectancy.
          </p>
        ) : null}
      </Section>

      <div className="flex items-center justify-end gap-3">
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Running…" : "Run Backtest"}
        </Button>
      </div>
    </form>
  );
}
