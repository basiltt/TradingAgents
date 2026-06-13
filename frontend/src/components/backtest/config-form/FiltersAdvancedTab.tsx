import { Controller, type UseFormSetValue } from "react-hook-form";
import { Checkbox } from "@/components/ui/checkbox";
import { ADAPTIVE_BLACKLIST_DEFAULTS, type BacktestConfigFormValues } from "../configSchema";
import { NumberField, SymbolListField, Section, Hint, GRID } from "./fields";
import { ToggleNumberPairField } from "./ToggleNumberPairField";
import type { TabProps } from "./tabProps";

interface FiltersAdvancedTabProps extends TabProps {
  setValue: UseFormSetValue<BacktestConfigFormValues>;
}

export function FiltersAdvancedTab({ control, fieldError, setValue }: FiltersAdvancedTabProps) {
  return (
    <div className="flex flex-col gap-4">
      <Section title="Symbol Filters">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SymbolListField control={control} name="symbol_whitelist" label="Whitelist (only these)" hint="Scanner: Symbol whitelist · trade only these" error={fieldError("symbol_whitelist")} />
          <SymbolListField control={control} name="symbol_blacklist" label="Blacklist (never these)" hint="Scanner: Symbol blacklist · never trade these" error={fieldError("symbol_blacklist")} />
        </div>
      </Section>

      <Section
        title="Advanced (engine-level)"
        subtitle="Auto-trade engine features that are NOT shown in the scanner's config form. They still affect the backtest unless marked not-simulated."
      >
        <div className={GRID}>
          <NumberField control={control} name="max_price_drift_pct" label="Max price drift %" nullable hint="Engine-level · skip a signal if price moved this % since the scan" error={fieldError("max_price_drift_pct")} />
          <NumberField control={control} name="max_same_sector" label="Max positions same sector" nullable hint="Not simulated · sector data is live-only, no effect on results" error={fieldError("max_same_sector")} />
        </div>

        {/* Adaptive blacklist — reveal group: checkbox header + dependent fields shown only when on. */}
        <div className="mt-4 rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
          <Controller
            control={control}
            name="adaptive_blacklist_enabled"
            render={({ field }) => {
              const on = field.value === true;
              return (
                <>
                  <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
                    <Checkbox
                      checked={on}
                      aria-expanded={on}
                      aria-controls={on ? "adaptive-blacklist-reveal" : undefined}
                      onCheckedChange={(c) => {
                        const next = c === true;
                        field.onChange(next);
                        // On disable, reset the (now-hidden) dependent fields to their
                        // valid schema defaults. They are non-nullable and ignored by the
                        // engine when disabled, so this changes no backtest behavior — but
                        // it prevents a soft-lock where an invalid value typed while enabled
                        // would block submit from a field that is no longer in the DOM.
                        if (!next) {
                          setValue("adaptive_blacklist_min_trades", ADAPTIVE_BLACKLIST_DEFAULTS.min_trades, { shouldDirty: true, shouldValidate: true });
                          setValue("adaptive_blacklist_max_win_rate", ADAPTIVE_BLACKLIST_DEFAULTS.max_win_rate, { shouldDirty: true, shouldValidate: true });
                          setValue("adaptive_blacklist_lookback_hours", ADAPTIVE_BLACKLIST_DEFAULTS.lookback_hours, { shouldDirty: true, shouldValidate: true });
                        }
                      }}
                      className="mt-0.5"
                    />
                    <span className="flex flex-col">
                      Enable adaptive blacklist
                      <Hint text="Engine-level · auto-skip symbols whose recent win rate is poor" />
                    </span>
                  </label>
                  {on ? (
                    <div id="adaptive-blacklist-reveal" className={`${GRID} mt-3`}>
                      <NumberField control={control} name="adaptive_blacklist_min_trades" label="Min trades" hint="Engine-level · min trades before blacklisting" error={fieldError("adaptive_blacklist_min_trades")} />
                      <NumberField control={control} name="adaptive_blacklist_max_win_rate" label="Max win rate %" hint="Engine-level · blacklist below this win rate" error={fieldError("adaptive_blacklist_max_win_rate")} />
                      <NumberField control={control} name="adaptive_blacklist_lookback_hours" label="Lookback (hours)" hint="Engine-level · win-rate lookback window" error={fieldError("adaptive_blacklist_lookback_hours")} />
                    </div>
                  ) : null}
                </>
              );
            }}
          />
        </div>

        {/* Cool Off Time — 2-column matrix of self-contained reveal-when-on cards. */}
        <div className="mt-4 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
          Cool Off Time
        </div>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <ToggleNumberPairField control={control} enabledName="cooloff_on_success_enabled" valueName="cooloff_on_success_minutes" title="Cool off after a win" description="pause new entries after a winning cycle" enabledValue={60} unit="min" error={fieldError("cooloff_on_success_minutes")} />
          <ToggleNumberPairField control={control} enabledName="cooloff_on_failure_enabled" valueName="cooloff_on_failure_minutes" title="Cool off after a loss" description="pause after a losing cycle" enabledValue={60} unit="min" error={fieldError("cooloff_on_failure_minutes")} />
          <ToggleNumberPairField control={control} enabledName="cooloff_on_double_success_enabled" valueName="cooloff_on_double_success_minutes" title="Cool off after 2 wins" description="2 consecutive wins" enabledValue={120} unit="min" error={fieldError("cooloff_on_double_success_minutes")} />
          <ToggleNumberPairField control={control} enabledName="cooloff_on_double_failure_enabled" valueName="cooloff_on_double_failure_minutes" title="Cool off after 2 losses" description="2 consecutive losses" enabledValue={480} unit="min" error={fieldError("cooloff_on_double_failure_minutes")} />
        </div>
      </Section>
    </div>
  );
}
