import type { UseFormSetValue } from "react-hook-form";
import { Checkbox } from "@/components/ui/checkbox";
import type { BacktestConfigFormValues } from "../configSchema";
import { CheckField, NumberField, SelectField, ToggleNumberField, Section, Hint, GRID } from "./fields";
import type { TabProps } from "./tabProps";

interface RiskExitsTabProps extends TabProps {
  durationLimitsOn: boolean;
  setValue: UseFormSetValue<BacktestConfigFormValues>;
}

export function RiskExitsTab({ control, fieldError, durationLimitsOn, setValue }: RiskExitsTabProps) {
  return (
    <div className="flex flex-col gap-4">
      <Section title="Close Rules">
        <p className="mb-3 text-[0.72rem] leading-snug text-[var(--neu-text-muted)]">
          Same close automation as the scanner. Each switch reveals its input when turned on; off means the rule is disabled.
        </p>
        <div className="mb-4 sm:w-1/2 lg:w-1/3">
          <NumberField control={control} name="max_drawdown_pct" label="Max drawdown %" hint="Scanner: Max drawdown % · close all if equity falls this far" error={fieldError("max_drawdown_pct")} />
        </div>
        <div className="space-y-3">
          <CheckField control={control} name="smart_drawdown_close" label="Smart drawdown (close only losers)" hint="Scanner: when drawdown triggers, keep winners running" />
          <ToggleNumberField control={control} name="close_on_profit_pct" title="Close and re-trade on profit" description="Scanner: close all once open equity rises this %, then re-trade" enabledValue={50} unit="%" min={1} max={100} step={5} error={fieldError("close_on_profit_pct")} />
          {/* Trade duration limits — ONE scanner switch driving TWO fields (4h / 8h). */}
          <div className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
            <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
              <Checkbox
                checked={durationLimitsOn}
                onCheckedChange={(checked) => {
                  const on = checked === true;
                  setValue("breakeven_timeout_hours", on ? 4 : null, { shouldDirty: true, shouldValidate: true });
                  setValue("max_trade_duration_hours", on ? 8 : null, { shouldDirty: true, shouldValidate: true });
                }}
                className="mt-0.5"
              />
              <span className="flex flex-col">
                Trade duration limits
                <Hint text="Scanner: auto-close trades based on how long they've been open" />
              </span>
            </label>
            {durationLimitsOn ? (
              <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <NumberField control={control} name="breakeven_timeout_hours" label="Close all at breakeven after (hours)" nullable hint="Scanner: then close once open PnL covers fees" error={fieldError("breakeven_timeout_hours")} />
                <NumberField control={control} name="max_trade_duration_hours" label="Force close after (hours)" nullable hint="Scanner: close all even at a loss after this time" error={fieldError("max_trade_duration_hours")} />
              </div>
            ) : null}
          </div>
          <ToggleNumberField control={control} name="trailing_profit_pct" title="Trailing profit stop" description="Scanner: after gaining this %, close if profit drops 50% from peak" enabledValue={2.0} unit="%" min={0.5} max={50} step={0.5} error={fieldError("trailing_profit_pct")} />
        </div>
      </Section>

      <Section title="Risk Limits">
        <div className={GRID}>
          <NumberField control={control} name="max_same_direction" label="Max positions same direction" nullable hint="Scanner: Max positions same direction" error={fieldError("max_same_direction")} />
          <NumberField control={control} name="max_signal_age_minutes" label="Max signal age (min)" nullable hint="Scanner: Max signal age (minutes)" error={fieldError("max_signal_age_minutes")} />
        </div>
      </Section>

      <Section title="Target Goal">
        <p className="mb-3 text-[0.72rem] leading-snug text-[var(--neu-text-muted)]">
          Scanner: Target goal — stops the whole cycle once reached. Different from &ldquo;Close and re-trade on profit&rdquo; in Close Rules, which closes mid-cycle and keeps trading.
        </p>
        <div className={GRID}>
          <SelectField control={control} name="target_goal_type" label="Goal Type" emptyToNull hint="Scanner: Target goal type" error={fieldError("target_goal_type")} options={[
            { value: "", label: "None" },
            { value: "trade_count", label: "Trade count" },
            { value: "profit_pct", label: "Profit %" },
          ]} />
          <NumberField control={control} name="target_goal_value" label="Goal Value" nullable hint="Scanner: target trade count or profit %, per Goal Type" error={fieldError("target_goal_value")} />
        </div>
      </Section>
    </div>
  );
}
