import { CheckField, NumberField, SymbolListField, Section, GRID } from "./fields";
import type { TabProps } from "./tabProps";

export function FiltersAdvancedTab({ control, fieldError }: TabProps) {
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
        <div className="mb-2 mt-4">
          <CheckField control={control} name="adaptive_blacklist_enabled" label="Enable adaptive blacklist" hint="Engine-level · auto-skip symbols whose recent win rate is poor" />
        </div>
        <div className={GRID}>
          <NumberField control={control} name="adaptive_blacklist_min_trades" label="Min trades" hint="Engine-level · min trades before blacklisting" error={fieldError("adaptive_blacklist_min_trades")} />
          <NumberField control={control} name="adaptive_blacklist_max_win_rate" label="Max win rate %" hint="Engine-level · blacklist below this win rate" error={fieldError("adaptive_blacklist_max_win_rate")} />
          <NumberField control={control} name="adaptive_blacklist_lookback_hours" label="Lookback (hours)" hint="Engine-level · win-rate lookback window" error={fieldError("adaptive_blacklist_lookback_hours")} />
        </div>
        <div className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Cool Off Time
        </div>
        <div className="mb-2">
          <CheckField control={control} name="cooloff_on_success_enabled" label="Cool off after a win" hint="Engine-level · pause new entries after a winning cycle" />
        </div>
        <div className={GRID}>
          <NumberField control={control} name="cooloff_on_success_minutes" label="Win cool off (min)" nullable hint="1–43200 minutes" error={fieldError("cooloff_on_success_minutes")} />
          <CheckField control={control} name="cooloff_on_failure_enabled" label="Cool off after a loss" hint="Engine-level · pause after a losing cycle" />
          <NumberField control={control} name="cooloff_on_failure_minutes" label="Loss cool off (min)" nullable hint="1–43200 minutes" error={fieldError("cooloff_on_failure_minutes")} />
        </div>
        <div className={GRID}>
          <CheckField control={control} name="cooloff_on_double_success_enabled" label="Cool off after 2 wins" hint="Engine-level · 2 consecutive wins" />
          <NumberField control={control} name="cooloff_on_double_success_minutes" label="2-win cool off (min)" nullable hint="1–43200 minutes" error={fieldError("cooloff_on_double_success_minutes")} />
          <CheckField control={control} name="cooloff_on_double_failure_enabled" label="Cool off after 2 losses" hint="Engine-level · 2 consecutive losses" />
          <NumberField control={control} name="cooloff_on_double_failure_minutes" label="2-loss cool off (min)" nullable hint="1–43200 minutes" error={fieldError("cooloff_on_double_failure_minutes")} />
        </div>
      </Section>
    </div>
  );
}
