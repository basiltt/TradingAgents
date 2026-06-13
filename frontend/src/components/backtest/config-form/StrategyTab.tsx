import { CheckField, NumberField, SelectField, HoursListField, Section, GRID } from "./fields";
import type { TabProps } from "./tabProps";

interface StrategyTabProps extends TabProps {
  mrLongEnabled: boolean | undefined;
}

export function StrategyTab({ control, fieldError, mrLongEnabled }: StrategyTabProps) {
  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Trade Decisions"
        subtitle="Mirrors the scanner's auto-trade config — same field names, same meaning."
      >
        <div className={GRID}>
          <SelectField control={control} name="direction" label="Direction" hint="Scanner: Direction" error={fieldError("direction")} options={[
            { value: "straight", label: "Straight (follow signal)" },
            { value: "reverse", label: "Reverse (invert signal)" },
          ]} />
          <NumberField control={control} name="leverage" label="Leverage" hint="Scanner: Leverage" error={fieldError("leverage")} />
          <NumberField control={control} name="capital_pct" label="Capital %" hint="Scanner: Capital % · margin per trade" error={fieldError("capital_pct")} />
          <NumberField control={control} name="take_profit_pct" label="Take profit %" hint="Scanner: Take profit %" error={fieldError("take_profit_pct")} />
          <NumberField control={control} name="stop_loss_pct" label="Stop loss %" hint="Scanner: Stop loss %" error={fieldError("stop_loss_pct")} />
          <NumberField control={control} name="min_score" label="Min score" hint="Scanner: Min score" error={fieldError("min_score")} />
          <SelectField control={control} name="confidence_filter" label="Min confidence" hint="Scanner: Min confidence" error={fieldError("confidence_filter")} options={[
            { value: "any", label: "Any" },
            { value: "high", label: "High only" },
            { value: "moderate", label: "Moderate+" },
            { value: "low", label: "Low+" },
          ]} />
          <SelectField control={control} name="signal_sides" label="Signal sides" hint="Scanner: Signal sides" error={fieldError("signal_sides")} options={[
            { value: "both", label: "Both" },
            { value: "buy", label: "Buy only" },
            { value: "sell", label: "Sell only" },
          ]} />
          <NumberField control={control} name="max_trades" label="Max trades" hint="Scanner: Max trades · per scan cycle" error={fieldError("max_trades")} />
          <SelectField control={control} name="execution_mode" label="Execution mode" hint="Scanner: Execution mode" error={fieldError("execution_mode")} options={[
            { value: "immediate", label: "Immediate" },
            { value: "batch", label: "Batch" },
          ]} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
          <CheckField control={control} name="fill_to_max_trades" label="Fill to max trades" hint="Scanner: Fill to max trades" />
          <CheckField control={control} name="skip_if_positions_open" label="Skip if positions open" hint="Scanner: Skip if positions open" />
        </div>
      </Section>

      <Section title="Market Regime & Strategy (F1/F2/F3)">
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
          <SelectField control={control} name="btc_vol_interval" label="BTC vol interval" error={fieldError("btc_vol_interval")} options={[
            { value: "15m", label: "15m" }, { value: "1h", label: "1h" }, { value: "4h", label: "4h" },
          ]} />
          <NumberField control={control} name="btc_vol_lookback_candles" label="BTC vol lookback" error={fieldError("btc_vol_lookback_candles")} />
        </div>

        {/* F3 — Strategy Cohort */}
        <div className="mt-4">
          <SelectField control={control} name="strategy_cohort" label="Strategy cohort (F3)" emptyToNull error={fieldError("strategy_cohort")} options={[
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
          <SelectField control={control} name="mr_mean_interval" label="MR mean interval" error={fieldError("mr_mean_interval")} options={[
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
    </div>
  );
}
