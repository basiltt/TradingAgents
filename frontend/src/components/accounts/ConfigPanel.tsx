/**
 * @module ConfigPanel
 * @description AI Manager configuration form for a single account. Fetches the
 * current config from Redux, presents editable fields, validates inputs, and
 * dispatches a patch on save.
 */

import { useEffect, useState, useCallback } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { patchAIManagerConfig, fetchConfig } from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface ConfigPanelProps {
  accountId: string;
}

interface FormState {
  confidence: string;
  maxLoss: string;
  interval: string;
  risk: string;
  dryRun: boolean;
  maxDailyActions: string;
  maxHourlyActions: string;
  minPositionAge: string;
  gracePeriod: string;
  profitTarget: string;
  maxSingleLoss: string;
  excludedSymbols: string;
  lockedPositions: string;
}

const DEFAULT_FORM: FormState = {
  confidence: "0.7",
  maxLoss: "5.0",
  interval: "60",
  risk: "moderate",
  dryRun: false,
  maxDailyActions: "30",
  maxHourlyActions: "10",
  minPositionAge: "300",
  gracePeriod: "0",
  profitTarget: "",
  maxSingleLoss: "3.0",
  excludedSymbols: "",
  lockedPositions: "",
};

const VALID_RISK_LEVELS = ["conservative", "moderate", "aggressive"] as const;
const SYMBOL_PATTERN = /^[A-Z0-9]{1,20}$/;

/**
 * AI Manager configuration panel for a single account.
 *
 * @param props.accountId - The account to configure.
 */
export function ConfigPanel({ accountId }: ConfigPanelProps) {
  const dispatch = useAppDispatch();
  const loading = useAppSelector((s: RootState) => s.aiManager.loading["patchConfig"] || s.aiManager.loading["fetchConfig"]);
  const savedConfig = useAppSelector((s: RootState) => s.aiManager.configByAccount[accountId]);

  const [form, setForm] = useState<FormState>(DEFAULT_FORM);

  const updateField = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  }, []);

  useEffect(() => {
    dispatch(fetchConfig(accountId));
  }, [dispatch, accountId]);

  useEffect(() => {
    if (savedConfig) {
      setForm({
        confidence: String(savedConfig.confidence_threshold ?? "0.7"),
        maxLoss: String(savedConfig.max_daily_loss_pct ?? "5.0"),
        interval: String(savedConfig.evaluation_interval_s ?? "60"),
        risk: String(savedConfig.risk_tolerance ?? "moderate"),
        dryRun: Boolean(savedConfig.dry_run),
        maxDailyActions: String(savedConfig.max_daily_actions ?? "30"),
        maxHourlyActions: String(savedConfig.max_hourly_actions ?? "10"),
        minPositionAge: String(savedConfig.min_position_age_s ?? "300"),
        gracePeriod: String(savedConfig.grace_period_s ?? "0"),
        profitTarget: savedConfig.daily_profit_target_pct != null ? String(savedConfig.daily_profit_target_pct) : "",
        maxSingleLoss: String(savedConfig.max_single_decision_loss_pct ?? "3.0"),
        excludedSymbols: (savedConfig.excluded_symbols as string[] || []).join(", "),
        lockedPositions: (savedConfig.locked_positions as string[] || []).join(", "),
      });
    }
  }, [savedConfig]);

  const handleSave = () => {
    const updates: Record<string, unknown> = {};

    const c = parseFloat(form.confidence);
    if (!isNaN(c) && c >= 0.3 && c <= 0.95) updates.confidence_threshold = c;
    const l = parseFloat(form.maxLoss);
    if (!isNaN(l) && l >= 1.0 && l <= 25) updates.max_daily_loss_pct = l;
    const i = parseFloat(form.interval);
    if (!isNaN(i) && i >= 30 && i <= 300) updates.evaluation_interval_s = i;
    if (form.risk && VALID_RISK_LEVELS.includes(form.risk as typeof VALID_RISK_LEVELS[number])) {
      updates.risk_tolerance = form.risk;
    }
    updates.dry_run = form.dryRun;

    const da = parseInt(form.maxDailyActions);
    if (!isNaN(da) && da >= 5 && da <= 100) updates.max_daily_actions = da;
    const ha = parseInt(form.maxHourlyActions);
    if (!isNaN(ha) && ha >= 2 && ha <= 30) updates.max_hourly_actions = ha;
    const mpa = parseInt(form.minPositionAge);
    if (!isNaN(mpa) && mpa >= 60 && mpa <= 3600) updates.min_position_age_s = mpa;
    const gp = parseInt(form.gracePeriod);
    if (!isNaN(gp) && gp >= 0 && gp <= 30) updates.grace_period_s = gp;
    const msl = parseFloat(form.maxSingleLoss);
    if (!isNaN(msl) && msl >= 0.5 && msl <= 10) updates.max_single_decision_loss_pct = msl;

    if (form.profitTarget.trim()) {
      const pt = parseFloat(form.profitTarget);
      if (!isNaN(pt) && pt > 0 && pt <= 100) updates.daily_profit_target_pct = pt;
    } else {
      updates.daily_profit_target_pct = null;
    }

    const excluded = form.excludedSymbols.split(",").map(s => s.trim().toUpperCase()).filter(s => SYMBOL_PATTERN.test(s));
    updates.excluded_symbols = excluded;
    const locked = form.lockedPositions.split(",").map(s => s.trim().toUpperCase()).filter(s => SYMBOL_PATTERN.test(s));
    updates.locked_positions = locked;

    if (Object.keys(updates).length > 0) {
      dispatch(patchAIManagerConfig({ accountId, updates })).then(() => {
        dispatch(fetchConfig(accountId));
      });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Confidence Threshold (0.3–0.95)</span>
          <input
            type="number"
            step="0.05"
            min="0.3"
            max="0.95"
            value={form.confidence}
            onChange={(e) => updateField("confidence", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Max Daily Loss % (1–25)</span>
          <input
            type="number"
            step="0.5"
            min="1.0"
            max="25"
            value={form.maxLoss}
            onChange={(e) => updateField("maxLoss", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Eval Interval (30–300s)</span>
          <input
            type="number"
            step="5"
            min="30"
            max="300"
            value={form.interval}
            onChange={(e) => updateField("interval", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Risk Tolerance</span>
          <select
            value={form.risk}
            onChange={(e) => updateField("risk", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          >
            <option value="conservative">Conservative</option>
            <option value="moderate">Moderate</option>
            <option value="aggressive">Aggressive</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Max Daily Actions (5–100)</span>
          <input
            type="number"
            step="1"
            min="5"
            max="100"
            value={form.maxDailyActions}
            onChange={(e) => updateField("maxDailyActions", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Max Hourly Actions (2–30)</span>
          <input
            type="number"
            step="1"
            min="2"
            max="30"
            value={form.maxHourlyActions}
            onChange={(e) => updateField("maxHourlyActions", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Min Position Age (60–3600s)</span>
          <input
            type="number"
            step="30"
            min="60"
            max="3600"
            value={form.minPositionAge}
            onChange={(e) => updateField("minPositionAge", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Grace Period (0–30s)</span>
          <input
            type="number"
            step="1"
            min="0"
            max="30"
            value={form.gracePeriod}
            onChange={(e) => updateField("gracePeriod", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Max Single Loss % (0.5–10)</span>
          <input
            type="number"
            step="0.5"
            min="0.5"
            max="10"
            value={form.maxSingleLoss}
            onChange={(e) => updateField("maxSingleLoss", e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Daily Profit Target % (optional)</span>
          <input
            type="number"
            step="1"
            min="1"
            max="100"
            value={form.profitTarget}
            onChange={(e) => updateField("profitTarget", e.target.value)}
            placeholder="None"
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
      </div>

      <label className="space-y-1 block">
        <span className="text-xs text-muted-foreground">Excluded Symbols (comma-separated)</span>
        <input
          type="text"
          value={form.excludedSymbols}
          onChange={(e) => updateField("excludedSymbols", e.target.value)}
          placeholder="e.g. BTCUSDT, ETHUSDT"
          className="w-full rounded border bg-background px-2 py-1 text-sm"
        />
      </label>

      <label className="space-y-1 block">
        <span className="text-xs text-muted-foreground">Locked Positions (comma-separated)</span>
        <input
          type="text"
          value={form.lockedPositions}
          onChange={(e) => updateField("lockedPositions", e.target.value)}
          placeholder="e.g. SOLUSDT"
          className="w-full rounded border bg-background px-2 py-1 text-sm"
        />
      </label>

      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={form.dryRun} onChange={(e) => updateField("dryRun", e.target.checked)} />
        Dry Run (log only, no execution)
      </label>
      <Button size="sm" disabled={loading} onClick={handleSave}>
        Save Config
      </Button>
    </div>
  );
}
