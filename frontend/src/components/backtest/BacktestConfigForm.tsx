import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { DashboardCard } from "@/api/client";
import type { BacktestCreateRequest } from "./types";
import {
  backtestConfigSchema,
  buildDefaults,
  buildDadDemoReferenceDefaults,
  buildOptimizedReferenceDefaults,
  toCreateRequest,
  ADAPTIVE_BLACKLIST_DEFAULTS,
  type BacktestConfigFormValues,
} from "./configSchema";
import {
  clearDraft,
  loadDraft,
  loadReferenceConfig,
  saveDraft,
  saveReferenceConfig,
  type BacktestDraft,
} from "./backtestDraft";
import { SetupTab } from "./config-form/SetupTab";
import { StrategyTab } from "./config-form/StrategyTab";
import { RiskExitsTab } from "./config-form/RiskExitsTab";
import { FiltersAdvancedTab } from "./config-form/FiltersAdvancedTab";
import { TAB_ORDER, TAB_LABELS, FIELD_PATHS_BY_TAB, type TabId } from "./config-form/tabMeta";
import { errorMessageAt, hasErrorAt, collectErrors } from "./config-form/errorTree";
import type { ScheduleOption } from "./config-form/tabProps";

/* --------------------------------- error helpers --------------------------------- */

const ERROR_FIELD_LABELS: Record<string, string> = {
  starting_capital: "Initial Balance",
  date_range_start: "Start",
  date_range_end: "End",
  "scan_source.mode": "Source Mode",
  "scan_source.schedule_id": "Schedule",
  "scan_source.scan_ids": "Selected Scans",
  "scan_source.replay_account_id": "Replay Account",
  simulation_interval: "Simulation Interval",
  fee_rate_pct: "Fee Rate",
  slippage_bps: "Slippage",
  funding_rate_model: "Funding Model",
  funding_rate_fixed_pct: "Funding Rate",
  direction: "Direction",
  leverage: "Leverage",
  capital_pct: "Capital %",
  take_profit_pct: "Take profit %",
  stop_loss_pct: "Stop loss %",
  min_score: "Min score",
  confidence_filter: "Min confidence",
  signal_sides: "Signal sides",
  max_trades: "Max trades",
  execution_mode: "Execution mode",
  max_same_direction: "Max positions same direction",
  max_signal_age_minutes: "Max signal age",
  symbol_whitelist: "Whitelist",
  symbol_blacklist: "Blacklist",
  max_drawdown_pct: "Max drawdown %",
  breakeven_timeout_hours: "Breakeven timeout",
  max_trade_duration_hours: "Max duration",
  trailing_profit_pct: "Trailing profit stop",
  close_on_profit_pct: "Close and re-trade on profit",
  target_goal_type: "Goal Type",
  target_goal_value: "Goal Value",
  max_same_sector: "Max positions same asset category",
  max_price_drift_pct: "Max price drift %",
  adaptive_blacklist_min_trades: "Adaptive blacklist min trades",
  adaptive_blacklist_max_win_rate: "Adaptive blacklist max win rate",
  adaptive_blacklist_lookback_hours: "Adaptive blacklist lookback",
  session_blocked_hours_utc: "Blocked UTC hours",
  session_allowed_hours_utc: "Allowed UTC hours",
  btc_vol_min_threshold: "BTC vol min",
  btc_vol_max_threshold: "BTC vol max",
  btc_vol_lookback_candles: "BTC vol lookback",
  mr_short_enabled: "MR short side",
  mr_leverage: "MR leverage",
  mr_capital_pct: "MR capital",
  mr_max_trades: "MR max trades",
  mr_mean_period: "MR mean period",
  mr_target_capture_pct: "MR target capture",
  mr_tight_stop_pct: "MR tight stop",
  mr_time_stop_minutes: "MR time-stop",
  mr_min_edge_pct: "MR min edge",
};

function summarizeError(path: string, message: string): string {
  const normalizedPath = path.replace(/\.root$/, "");
  const label =
    ERROR_FIELD_LABELS[normalizedPath] ??
    normalizedPath
      .split(".")
      .filter(Boolean)
      .map((part) =>
        part
          .replace(/_/g, " ")
          .replace(/\b\w/g, (char) => char.toUpperCase()),
      )
      .join(" > ");
  return label ? `${label}: ${message}` : message;
}

/* --------------------------------- main form --------------------------------- */

// ScheduleOption is defined in the shared tab-props module; re-export it here so
// existing importers of `ScheduleOption` from this file keep working.
export type { ScheduleOption };

/**
 * Sanitize fields that live behind a disable toggle so a config from ANY entry path
 * (seed, restored draft, or a stored "Reference" preset) can't carry a value that
 * fails validation from a control that isn't in the DOM — an unfixable soft-lock.
 * The backtest engine ignores these when their feature is disabled (cooloff_core
 * gates on *_enabled; backtest_engine gates on adaptive_blacklist_enabled), so
 * forcing valid/empty values when off is inert. Returns a shallow copy; the input
 * is never mutated (so callers can pass a stored/shared object safely).
 */
function normalizeDisabledGroups(input: BacktestConfigFormValues): BacktestConfigFormValues {
  const values = { ...input };
  // Adaptive blacklist: deps are non-nullable with min/max — force valid defaults.
  if (!values.adaptive_blacklist_enabled) {
    values.adaptive_blacklist_min_trades = ADAPTIVE_BLACKLIST_DEFAULTS.min_trades;
    values.adaptive_blacklist_max_win_rate = ADAPTIVE_BLACKLIST_DEFAULTS.max_win_rate;
    values.adaptive_blacklist_lookback_hours = ADAPTIVE_BLACKLIST_DEFAULTS.lookback_hours;
  }
  // Cool-off tiers: minutes are nullable + range-checked — null any disabled tier so
  // an out-of-range leftover can't block submit from a hidden input.
  if (!values.cooloff_on_success_enabled) values.cooloff_on_success_minutes = null;
  if (!values.cooloff_on_failure_enabled) values.cooloff_on_failure_minutes = null;
  if (!values.cooloff_on_double_success_enabled) values.cooloff_on_double_success_minutes = null;
  if (!values.cooloff_on_double_failure_enabled) values.cooloff_on_double_failure_minutes = null;
  return values;
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
    const merged = draft ? { ...base, ...draft } : base;
    // Sanitize disabled-feature fields so a stale draft/seed can't soft-lock submit.
    return normalizeDisabledGroups(merged);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time inputs only
  }, []);

  // Restore the active tab from the same draft (UI-only; falls back to "setup"
  // for a seed or a draft predating this field). A seed is an intentional config,
  // so it always starts on Setup.
  const initialTab = React.useMemo<TabId>(() => {
    const draft = seed ? undefined : loadDraft();
    const t = draft?.active_tab;
    return t && TAB_ORDER.includes(t) ? t : "setup";
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time only
  }, []);
  const [activeTab, setActiveTab] = React.useState<TabId>(initialTab);
  // Mirror activeTab into a ref so the non-rendering watch() subscription can read
  // the current tab without re-subscribing (avoids a stale closure).
  const activeTabRef = React.useRef(activeTab);
  activeTabRef.current = activeTab;

  const {
    control,
    handleSubmit,
    watch,
    setValue,
    getValues,
    reset,
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
    const sub = watch(() => {
      // The callback payload can be partial when fields are hidden/unmounted. Pull
      // the canonical RHF snapshot so every save keeps the full form state. Spread
      // the current tab (via ref) so a field edit never clobbers the saved tab.
      saveDraft({ ...(getValues() as BacktestDraft), active_tab: activeTabRef.current });
    });
    return () => sub.unsubscribe();
  }, [getValues, watch]);

  // Switch tabs AND persist the choice. This is interaction-driven (only fires when
  // the user clicks a tab), mirroring the watch() field-persistence above — so it
  // never runs on mount. A mount-time write would clobber an existing draft when the
  // form is opened with a `seed` (which intentionally ignores the draft) and would
  // persist a defaults snapshot before the user has touched anything.
  const handleTabChange = React.useCallback(
    (next: TabId) => {
      setActiveTab(next);
      saveDraft({ ...(getValues() as BacktestDraft), active_tab: next });
    },
    [getValues],
  );

  const applyDadDemoReference = React.useCallback(() => {
    const storedReference = loadReferenceConfig();
    const usableStoredReference =
      storedReference?.date_range_start === "" || storedReference?.date_range_end === ""
        ? undefined
        : storedReference;
    const referenceValues = normalizeDisabledGroups(
      usableStoredReference
        ? { ...buildDefaults(), ...usableStoredReference }
        : buildDadDemoReferenceDefaults(getValues() as Partial<BacktestCreateRequest>),
    );
    reset(referenceValues);
    saveDraft(referenceValues);
  }, [getValues, reset]);

  const applyOptimizedReference = React.useCallback(() => {
    const referenceValues = normalizeDisabledGroups(buildOptimizedReferenceDefaults());
    reset(referenceValues);
    saveDraft(referenceValues);
  }, [reset]);

  const storeReferenceConfig = React.useCallback(() => {
    saveReferenceConfig(getValues() as BacktestDraft);
  }, [getValues]);

  const resetForm = React.useCallback(() => {
    reset(buildDefaults());
    clearDraft();
  }, [reset]);

  const scanMode = watch("scan_source.mode");
  const replayAccountId = watch("scan_source.replay_account_id");
  const mrLongEnabled = watch("mr_long_enabled");
  // "Trade duration limits" is a single scanner toggle that drives BOTH the
  // breakeven-timeout and force-close fields together (scanner seeds 4h / 8h).
  const breakevenHours = watch("breakeven_timeout_hours");
  const maxDurationHours = watch("max_trade_duration_hours");
  // Gate on null, NOT `> 0`: toggling off sets both to null, so null === collapsed.
  // `> 0` would unmount the revealed inputs the instant a user types a leading "0"
  // (e.g. entering "0.5"), destroying focus and silently unchecking the toggle —
  // the same trap fixed in ToggleNumberField's reveal gate.
  const durationLimitsOn = breakevenHours != null || maxDurationHours != null;
  const formRef = React.useRef<HTMLFormElement>(null);
  const summaryRef = React.useRef<HTMLDivElement>(null);

  // The leaf message at a field path (supports dotted scan_source.* paths). Memoized
  // so the reference is stable across renders for the four tab components it's passed to.
  const fieldError = React.useCallback(
    (path: string): string | undefined => errorMessageAt(errors, path),
    [errors],
  );

  // Per-tab error count, derived from the field→tab map so badges and auto-switch
  // share one source of truth and cannot drift.
  const tabErrorCount = React.useCallback(
    (id: TabId): number => FIELD_PATHS_BY_TAB[id].reduce((n, p) => n + (hasErrorAt(errors, p) ? 1 : 0), 0),
    [errors],
  );

  const submit = handleSubmit(
    (values) => {
      const parsed = backtestConfigSchema.parse(values);
      onSubmit(toCreateRequest(parsed));
    },
    (submitErrors) => {
      // Surface errors hidden on inactive tabs: switch to the earliest errored tab
      // (lifecycle order), THEN focus its first invalid control after the DOM updates.
      // Compute the target from the FRESH errors passed to this handler (the render-
      // scope `errors` can lag a tick behind on the first failed submit).
      const target = TAB_ORDER.find((id) =>
        FIELD_PATHS_BY_TAB[id].some((path) => hasErrorAt(submitErrors, path)),
      );
      if (target) setActiveTab(target);
      requestAnimationFrame(() => {
        const el =
          formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
          summaryRef.current;
        el?.focus();
      });
    },
  );

  const validationMessages = React.useMemo(
    () =>
      Array.from(
        new Set(collectErrors(errors).map(({ path, message }) => summarizeError(path, message))),
      ),
    [errors],
  );

  return (
    <form ref={formRef} onSubmit={submit} className={cn("flex flex-col gap-4", className)} aria-label="Backtest configuration">
      {validationMessages.length ? (
        <div
          ref={summaryRef}
          role="alert"
          tabIndex={-1}
          data-testid="backtest-validation-summary"
          className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-danger)]/45 bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] px-4 py-3 text-sm text-[var(--neu-danger)]"
        >
          <p className="font-semibold">Fix the highlighted backtest settings before running.</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {validationMessages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)]/50 bg-[var(--neu-surface-inset)]/30 px-4 py-3">
        <p className="text-[0.78rem] leading-snug text-[var(--neu-text-muted)]">
          Most settings mirror your <span className="font-semibold text-[var(--neu-text)]">Scheduled Market Scan</span> auto-trade
          config — those fields are tagged <span className="font-semibold text-[var(--neu-text)]">Scanner:</span> with the exact
          name you&rsquo;ll find there. <span className="font-semibold text-[var(--neu-text)]">Backtest-only</span> fields (initial
          balance, date range, fees, slippage, funding) replace what a live account normally provides.
          <span className="font-semibold text-[var(--neu-text)]"> Engine-level</span> fields under Advanced are auto-trade features
          that don&rsquo;t appear in the scanner form. Fields marked <em>not simulated</em> have no effect here.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => handleTabChange(v as TabId)}>
        <TabsList className="max-w-full overflow-x-auto overflow-y-hidden">
          {TAB_ORDER.map((id) => {
            const count = tabErrorCount(id);
            return (
              <TabsTrigger key={id} value={id} className="gap-2">
                {TAB_LABELS[id]}
                {count > 0 ? (
                  <span
                    aria-label={`${count} ${count === 1 ? "error" : "errors"}`}
                    className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--neu-danger)] px-1.5 text-[0.65rem] font-bold leading-none text-white"
                  >
                    {count}
                  </span>
                ) : null}
              </TabsTrigger>
            );
          })}
        </TabsList>

        <TabsContent value="setup" keepMounted>
          <SetupTab control={control} fieldError={fieldError} schedules={schedules} accounts={accounts} scanMode={scanMode} replayAccountId={replayAccountId} />
        </TabsContent>
        <TabsContent value="strategy" keepMounted>
          <StrategyTab control={control} fieldError={fieldError} mrLongEnabled={mrLongEnabled} />
        </TabsContent>
        <TabsContent value="risk" keepMounted>
          <RiskExitsTab control={control} fieldError={fieldError} durationLimitsOn={durationLimitsOn} setValue={setValue} />
        </TabsContent>
        <TabsContent value="filters" keepMounted>
          <FiltersAdvancedTab control={control} fieldError={fieldError} setValue={setValue} />
        </TabsContent>
      </Tabs>

      <div className="sticky bottom-0 z-10 -mx-1 mt-2 flex flex-wrap items-center justify-end gap-3 border-t border-[color:var(--neu-stroke-soft)]/50 bg-[var(--neu-surface-base)]/95 px-1 py-3 backdrop-blur supports-[backdrop-filter]:bg-[var(--neu-surface-base)]/80">
        <Button type="button" variant="outline" onClick={resetForm} disabled={isSubmitting}>
          Reset
        </Button>
        <Button type="button" variant="outline" onClick={storeReferenceConfig} disabled={isSubmitting}>
          Store Reference
        </Button>
        <Button type="button" variant="secondary" onClick={applyDadDemoReference} disabled={isSubmitting}>
          Reference Config
        </Button>
        <Button type="button" variant="secondary" onClick={applyOptimizedReference} disabled={isSubmitting}>
          Optimized Reference
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Running…" : "Run Backtest"}
        </Button>
      </div>
    </form>
  );
}
