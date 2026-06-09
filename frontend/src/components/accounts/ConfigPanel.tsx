/**
 * @module ConfigPanel
 * @description AI Manager configuration form for a single account. Fetches the
 * current config from Redux, presents editable fields, validates inputs, and
 * dispatches a patch on save.
 */

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
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
 * Map a persisted AI-manager config object into editable form state.
 *
 * Every field is stringified (form inputs are controlled text) and falls back to
 * its DEFAULT_FORM value when absent. `excluded_symbols` / `locked_positions`
 * arrays are joined into comma-separated strings for the text inputs.
 *
 * @param saved - The persisted config (`Record<string, unknown>`), as stored in
 *   Redux. Shape is loosely typed because it mirrors a server JSON blob.
 * @returns A fully-populated {@link FormState} ready to seed the controlled inputs.
 *
 * @example
 * configToForm({ confidence_threshold: 0.8, dry_run: true });
 * // → { ...DEFAULT_FORM, confidence: "0.8", dryRun: true }
 */
function configToForm(saved: Record<string, unknown>): FormState {
  return {
    confidence: String(saved.confidence_threshold ?? DEFAULT_FORM.confidence),
    maxLoss: String(saved.max_daily_loss_pct ?? DEFAULT_FORM.maxLoss),
    interval: String(saved.evaluation_interval_s ?? DEFAULT_FORM.interval),
    risk: String(saved.risk_tolerance ?? DEFAULT_FORM.risk),
    dryRun: Boolean(saved.dry_run),
    maxDailyActions: String(saved.max_daily_actions ?? DEFAULT_FORM.maxDailyActions),
    maxHourlyActions: String(saved.max_hourly_actions ?? DEFAULT_FORM.maxHourlyActions),
    minPositionAge: String(saved.min_position_age_s ?? DEFAULT_FORM.minPositionAge),
    gracePeriod: String(saved.grace_period_s ?? DEFAULT_FORM.gracePeriod),
    profitTarget: saved.daily_profit_target_pct != null ? String(saved.daily_profit_target_pct) : "",
    maxSingleLoss: String(saved.max_single_decision_loss_pct ?? DEFAULT_FORM.maxSingleLoss),
    excludedSymbols: ((saved.excluded_symbols as string[]) || []).join(", "),
    lockedPositions: ((saved.locked_positions as string[]) || []).join(", "),
  };
}

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

  // AI-CONTEXT: Seed the editable form from the persisted config whenever a new
  // config object arrives from Redux. Implemented with React's "adjust state during
  // render when a dependency changes" pattern (tracking the previous savedConfig
  // reference) instead of a setState-in-effect (react-hooks/set-state-in-effect).
  // The slice replaces the object reference on each fetch, so identity comparison
  // correctly detects a fresh load. Local edits are preserved until the next fetch
  // swaps the reference again.
  const [seenConfig, setSeenConfig] = useState<Record<string, unknown> | null | undefined>(undefined);
  if (savedConfig !== seenConfig) {
    setSeenConfig(savedConfig);
    if (savedConfig) setForm(configToForm(savedConfig));
  }

  const handleSave = () => {
    const updates: Record<string, unknown> = {};
    const errors: string[] = [];

    // AI-CONTEXT: Validate-and-collect rather than silently drop. Previously each
    // out-of-range field was simply omitted from `updates`, the save "succeeded",
    // and the follow-up fetchConfig snapped the field back to its old value — so the
    // user believed an invalid entry saved when it was discarded with no feedback.
    // Now we accumulate human-readable errors and BLOCK the save (toast) if any
    // field is invalid, so the user can correct it.
    const num = (
      raw: string,
      label: string,
      min: number,
      max: number,
      parse: (s: string) => number,
      assign: (v: number) => void,
    ) => {
      const v = parse(raw);
      if (isNaN(v) || v < min || v > max) {
        errors.push(`${label} must be between ${min} and ${max}`);
      } else {
        assign(v);
      }
    };

    num(form.confidence, "Confidence threshold", 0.3, 0.95, parseFloat, (v) => (updates.confidence_threshold = v));
    num(form.maxLoss, "Max daily loss %", 1.0, 25, parseFloat, (v) => (updates.max_daily_loss_pct = v));
    num(form.interval, "Eval interval", 30, 300, parseFloat, (v) => (updates.evaluation_interval_s = v));
    if (form.risk && VALID_RISK_LEVELS.includes(form.risk as typeof VALID_RISK_LEVELS[number])) {
      updates.risk_tolerance = form.risk;
    } else {
      errors.push("Risk tolerance must be conservative, moderate, or aggressive");
    }
    updates.dry_run = form.dryRun;

    num(form.maxDailyActions, "Max daily actions", 5, 100, parseInt, (v) => (updates.max_daily_actions = v));
    num(form.maxHourlyActions, "Max hourly actions", 2, 30, parseInt, (v) => (updates.max_hourly_actions = v));
    num(form.minPositionAge, "Min position age (s)", 60, 3600, parseInt, (v) => (updates.min_position_age_s = v));
    num(form.gracePeriod, "Grace period (s)", 0, 30, parseInt, (v) => (updates.grace_period_s = v));
    num(form.maxSingleLoss, "Max single-decision loss %", 0.5, 10, parseFloat, (v) => (updates.max_single_decision_loss_pct = v));

    if (form.profitTarget.trim()) {
      const pt = parseFloat(form.profitTarget);
      if (isNaN(pt) || pt <= 0 || pt > 100) {
        errors.push("Daily profit target % must be between 0 (exclusive) and 100");
      } else {
        updates.daily_profit_target_pct = pt;
      }
    } else {
      updates.daily_profit_target_pct = null;
    }

    // Surface symbols that were rejected by the format pattern instead of dropping
    // them silently (a dropped symbol means the AI manager may trade it unexpectedly).
    const splitSymbols = (raw: string) =>
      raw.split(",").map((s) => s.trim().toUpperCase()).filter((s) => s.length > 0);
    const excludedRaw = splitSymbols(form.excludedSymbols);
    const excluded = excludedRaw.filter((s) => SYMBOL_PATTERN.test(s));
    const excludedRejected = excludedRaw.filter((s) => !SYMBOL_PATTERN.test(s));
    if (excludedRejected.length > 0) errors.push(`Invalid excluded symbols: ${excludedRejected.join(", ")}`);
    updates.excluded_symbols = excluded;

    const lockedRaw = splitSymbols(form.lockedPositions);
    const locked = lockedRaw.filter((s) => SYMBOL_PATTERN.test(s));
    const lockedRejected = lockedRaw.filter((s) => !SYMBOL_PATTERN.test(s));
    if (lockedRejected.length > 0) errors.push(`Invalid locked positions: ${lockedRejected.join(", ")}`);
    updates.locked_positions = locked;

    if (errors.length > 0) {
      toast.error(`Cannot save — fix ${errors.length} field${errors.length === 1 ? "" : "s"}`, {
        description: errors.join("; "),
      });
      return;
    }

    dispatch(patchAIManagerConfig({ accountId, updates })).then(() => {
      dispatch(fetchConfig(accountId));
    });
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
