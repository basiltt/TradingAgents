import { Controller } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { DashboardCard } from "@/api/client";
import { NumberField, SelectField, Section, Hint, GRID } from "./fields";
import type { TabProps, ScheduleOption } from "./tabProps";

/** A `datetime-local` value carries no timezone; on submit the form does
 * `new Date(value).toISOString()`, which interprets it in the BROWSER's local zone
 * and converts to UTC. That conversion is otherwise invisible — e.g. in IST (UTC+5:30)
 * a typed "18:30" is sent as "13:00Z". Surface the resolved UTC so the user sees both
 * the local time they entered and the actual window the engine will run. */
function UtcHint({ value }: { value: string }) {
  if (!value) return null;
  const d = new Date(value); // same interpretation as toCreateRequest()
  if (Number.isNaN(d.getTime())) return null;
  const utc = d.toISOString().slice(0, 16).replace("T", " ");
  return (
    <span className="text-[0.68rem] text-[var(--neu-text-muted)]" data-testid="utc-hint">
      = {utc} UTC
    </span>
  );
}

interface SetupTabProps extends TabProps {
  schedules: ScheduleOption[];
  accounts: DashboardCard[];
  scanMode: string | undefined;
  /** RHF types this discriminated-union path as `unknown`; compared as a string id. */
  replayAccountId: unknown;
}

export function SetupTab({ control, fieldError, schedules, accounts, scanMode, replayAccountId }: SetupTabProps) {
  return (
    <div className="flex flex-col gap-4">
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
                <>
                  <Input id="date_range_start" type="datetime-local" value={String(field.value ?? "")} onChange={field.onChange} onBlur={field.onBlur} aria-invalid={!!fieldError("date_range_start")} aria-describedby={fieldError("date_range_start") ? "date_range_start-error" : undefined} />
                  <UtcHint value={String(field.value ?? "")} />
                </>
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
                <>
                  <Input id="date_range_end" type="datetime-local" value={String(field.value ?? "")} onChange={field.onChange} onBlur={field.onBlur} aria-invalid={!!fieldError("date_range_end")} aria-describedby={fieldError("date_range_end") ? "date_range_end-error" : undefined} />
                  <UtcHint value={String(field.value ?? "")} />
                </>
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
            error={fieldError("scan_source.mode")}
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
                    aria-invalid={!!fieldError("scan_source.schedule_id")}
                    aria-describedby={fieldError("scan_source.schedule_id") ? "scan_source.schedule_id-error" : undefined}
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
                <span id="scan_source.schedule_id-error" className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("scan_source.schedule_id")}</span>
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
                    aria-invalid={!!fieldError("scan_source.replay_account_id")}
                    aria-describedby={fieldError("scan_source.replay_account_id") ? "scan_source.replay_account_id-error" : undefined}
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
                <span id="scan_source.replay_account_id-error" className="text-[0.72rem] text-[var(--neu-danger)]">{fieldError("scan_source.replay_account_id")}</span>
              ) : null}
              <span className="text-[0.72rem] text-[var(--neu-text-muted)]">
                Rebuilds this account's actual scanner trade ledger and keeps a
                candle-engine comparison beside it. The Date Range below bounds which trades are replayed;
                AI-Manager-closed and non-scanner trades are excluded. Replay infers
                starting balance from the first live cycle in the range.
              </span>
              {(() => {
                const acct = accounts.find((a) => a.id === replayAccountId);
                return acct?.ai_manager_state != null ? (
                  <span className="text-[0.72rem] text-[var(--neu-warning)]">
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
          ]} error={fieldError("simulation_interval")} />
          <NumberField control={control} name="fee_rate_pct" label="Fee Rate (%)" hint="Backtest-only · taker fee per side (Bybit ≈ 0.055)" error={fieldError("fee_rate_pct")} />
          <NumberField control={control} name="slippage_bps" label="Slippage (bps)" hint="Backtest-only · adverse fill slippage, basis points" error={fieldError("slippage_bps")} />
          <SelectField control={control} name="funding_rate_model" label="Funding Model" hint="Backtest-only · perpetual funding cost model" error={fieldError("funding_rate_model")} options={[
            { value: "none", label: "None" },
            { value: "fixed_8h", label: "Fixed (8h)" },
          ]} />
          <NumberField control={control} name="funding_rate_fixed_pct" label="Funding Rate (%/8h)" hint="Backtest-only · used when Funding Model = Fixed" error={fieldError("funding_rate_fixed_pct")} />
        </div>
      </Section>
    </div>
  );
}
