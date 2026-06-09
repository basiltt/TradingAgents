import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type AutoTradeConfig } from "@/api/client";
import { NeuSwitch } from "@/design-system/neumorphism";
import { RECOMMENDED_PRESET, RECOMMENDED_BLOCKED_HOURS } from "./regimeStrategyPreset";

// AI-CONTEXT: RECOMMENDED_PRESET lives in ./regimeStrategyPreset so this file
// exports only the component (React Fast Refresh / react-refresh/only-export-components).
// Tests import the preset from ./regimeStrategyPreset directly.

const SECTION_CLASS =
  "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4 border-none shadow-[var(--shadow-card)]";

interface Props {
  config: AutoTradeConfig;
  onChange: (partial: Partial<AutoTradeConfig>) => void;
  /** "manual" | "scheduled" — affects helper copy only. */
  context?: "manual" | "scheduled";
}

/**
 * Regime Multi-Strategy config (F1 session/regime filter, F2 mean-reversion,
 * F3 strategy cohort). All controls default-off so an untouched form preserves
 * current behavior. Mounted in the shared AutoTradeSection => appears on BOTH the
 * manual Market Scan and the Scheduled Market Scan forms.
 */
export function RegimeStrategyFields({ config, onChange }: Props) {
  const f1On = !!config.regime_filter_enabled;
  const mrOn = !!config.mean_reversion_enabled;
  const longOn = !!config.mr_long_enabled;
  const blocked = config.session_blocked_hours_utc ?? [];

  const toggleHour = (h: number) => {
    const set = new Set(blocked);
    if (set.has(h)) set.delete(h);
    else set.add(h);
    onChange({ session_blocked_hours_utc: Array.from(set).sort((a, b) => a - b) });
  };

  return (
    <div className={SECTION_CLASS}>
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        Market Regime &amp; Strategy
      </div>
      <p className="mb-3 text-[11px] leading-5 text-[var(--neu-text-muted)]">
        Adapt entries and strategy to market regime. All off by default — see the
        2026-06-07 profitability report (Asian-session bleed, 21-account correlation).
      </p>

      <button
        type="button"
        data-testid="apply-recommended-preset"
        onClick={() => onChange({ ...RECOMMENDED_PRESET })}
        className="mb-3 text-[11px] font-medium px-2.5 py-1 rounded-full border border-sky-500/30 bg-sky-500/[0.08] text-sky-400 hover:bg-sky-500/[0.14]"
      >
        Apply research-recommended preset
      </button>

      {/* ── F1: Regime/Session Entry Filter ── */}
      <div className="flex items-start gap-3 mb-2">
        <NeuSwitch
          checked={f1On}
          onChange={(v: boolean) => onChange({ regime_filter_enabled: v })}
          className="p-0 gap-0 shrink-0 mt-0.5"
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-[var(--neu-text-strong)]">Regime / Session Filter (F1)</p>
          <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">
            Suppress new entries during choppy UTC sessions and/or low BTC volatility.
          </p>
        </div>
      </div>
      {f1On && (
        <div className="ml-9 mb-3 space-y-3">
          <div className="flex items-center gap-2">
            <NeuSwitch checked={!!config.session_filter_enabled}
              onChange={(v: boolean) => onChange({ session_filter_enabled: v })} className="p-0 gap-0 shrink-0" />
            <span className="text-[12px] text-[var(--neu-text-strong)]">Block UTC hours</span>
            <button type="button"
              className="text-[11px] underline text-[var(--neu-accent)]"
              onClick={() => onChange({ session_blocked_hours_utc: [...RECOMMENDED_BLOCKED_HOURS] })}>
              Apply recommended (01, 06–12)
            </button>
          </div>
          {config.session_filter_enabled && (
            <div className="grid grid-cols-12 gap-1" role="group" aria-label="UTC hours to block">
              {Array.from({ length: 24 }, (_, h) => (
                <button key={h} type="button" aria-pressed={blocked.includes(h)}
                  onClick={() => toggleHour(h)}
                  className={`h-7 rounded text-[10px] font-mono border-none ${
                    blocked.includes(h)
                      ? "bg-[var(--neu-danger)] text-white"
                      : "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)]"
                  }`}>
                  {String(h).padStart(2, "0")}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            <NeuSwitch checked={!!config.btc_vol_filter_enabled}
              onChange={(v: boolean) => onChange({ btc_vol_filter_enabled: v })} className="p-0 gap-0 shrink-0" />
            <span className="text-[12px] text-[var(--neu-text-strong)]">BTC volatility band (ATR ratio)</span>
          </div>
          {config.btc_vol_filter_enabled && (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-[10px] uppercase text-muted-foreground">Min</Label>
                <Input type="number" step={0.1} value={config.btc_vol_min_threshold ?? ""}
                  onChange={(e) => onChange({ btc_vol_min_threshold: e.target.value ? +e.target.value : null })} />
              </div>
              <div>
                <Label className="text-[10px] uppercase text-muted-foreground">Max</Label>
                <Input type="number" step={0.1} value={config.btc_vol_max_threshold ?? ""}
                  onChange={(e) => onChange({ btc_vol_max_threshold: e.target.value ? +e.target.value : null })} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── F3: Strategy Cohort ── */}
      <div className="mb-3">
        <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Strategy cohort (F3)</Label>
        <div className="mt-2 grid grid-cols-3 gap-1.5">
          {([
            [null, "Inherit"],
            ["trend", "Trend"],
            ["mean_reversion", "Mean-Rev"],
          ] as const).map(([value, label]) => {
            const selected = (config.strategy_cohort ?? null) === value;
            return (
              <button key={label} type="button"
                className={`min-h-9 rounded px-2 py-2 text-[11px] font-bold uppercase tracking-wider border-none ${
                  selected
                    ? "bg-[var(--neu-surface-base)] text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-raised-soft)]"
                    : "text-[var(--neu-text-muted)]"
                }`}
                onClick={() => onChange({ strategy_cohort: value })}>
                {label}
              </button>
            );
          })}
        </div>
        <p className="mt-1 text-[10px] leading-4 text-[var(--neu-text-muted)]">
          Inherit uses the account's saved cohort (set in Accounts → Fleet). Pick Trend or
          Mean-Rev to override just this scan.
        </p>
      </div>

      {/* ── F2: Mean-Reversion Strategy ── */}
      <div className="flex items-start gap-3 mb-2">
        <NeuSwitch checked={mrOn}
          onChange={(v: boolean) => onChange({ mean_reversion_enabled: v })} className="p-0 gap-0 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-[var(--neu-text-strong)]">Mean-Reversion Strategy (F2)</p>
          <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">
            In ranging regime, fade extremes to the mean with tight, fast exits.
          </p>
        </div>
      </div>
      {mrOn && (
        <div className="ml-9 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label className="text-[10px] uppercase text-muted-foreground">Leverage</Label>
              <Input type="number" min={1} max={125} value={config.mr_leverage ?? 10}
                onChange={(e) => onChange({ mr_leverage: Math.min(125, Math.max(1, +e.target.value || 1)) })} />
            </div>
            <div>
              <Label className="text-[10px] uppercase text-muted-foreground">Capital %</Label>
              <Input type="number" min={0.1} max={100} step={0.1} value={config.mr_capital_pct ?? 2}
                onChange={(e) => onChange({ mr_capital_pct: Math.min(100, Math.max(0.1, +e.target.value || 1)) })} />
            </div>
            <div>
              <Label className="text-[10px] uppercase text-muted-foreground">Time-stop (min)</Label>
              <Input type="number" min={5} max={1440} value={config.mr_time_stop_minutes ?? 120}
                onChange={(e) => onChange({ mr_time_stop_minutes: Math.min(1440, Math.max(5, +e.target.value || 5)) })} />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <NeuSwitch checked={longOn}
              onChange={(v: boolean) => onChange({ mr_long_enabled: v, mr_long_ack_requested: v ? config.mr_long_ack_requested : false })}
              className="p-0 gap-0 shrink-0" />
            <span className="text-[12px] text-[var(--neu-text-strong)]">Enable long side</span>
          </div>
          {longOn && (
            <div className="rounded-md border border-[color-mix(in_oklch,var(--neu-danger)_40%,transparent)] bg-[color-mix(in_oklch,var(--neu-danger)_8%,var(--neu-surface-base))] p-3">
              <p className="text-[11px] font-semibold text-[var(--neu-danger)]">⚠ Long mean-reversion has NEGATIVE expectancy</p>
              <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">
                Research shows longs lose money on average (55% win rate, −$0.57/trade). Longs are
                rejected at trade time unless you acknowledge the risk for this account via the
                F2-long acknowledgement (server-enforced).
              </p>
              <label className="mt-2 flex items-center gap-2 text-[11px] text-[var(--neu-text-strong)]">
                <input type="checkbox" checked={!!config.mr_long_ack_requested}
                  onChange={(e) => onChange({ mr_long_ack_requested: e.target.checked })} />
                I understand long mean-reversion has negative expectancy
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
