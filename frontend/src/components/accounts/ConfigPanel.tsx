import { useEffect, useState } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { patchAIManagerConfig, fetchConfig } from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface ConfigPanelProps {
  accountId: string;
}

export function ConfigPanel({ accountId }: ConfigPanelProps) {
  const dispatch = useAppDispatch();
  const loading = useAppSelector((s: RootState) => s.aiManager.loading["patchConfig"] || s.aiManager.loading["fetchConfig"]);
  const savedConfig = useAppSelector((s: RootState) => s.aiManager.configByAccount[accountId]);

  const [confidence, setConfidence] = useState("0.7");
  const [maxLoss, setMaxLoss] = useState("5.0");
  const [interval, setInterval_] = useState("60");
  const [risk, setRisk] = useState("moderate");
  const [dryRun, setDryRun] = useState(false);
  const [maxDailyActions, setMaxDailyActions] = useState("30");
  const [maxHourlyActions, setMaxHourlyActions] = useState("10");
  const [minPositionAge, setMinPositionAge] = useState("300");
  const [gracePeriod, setGracePeriod] = useState("0");
  const [profitTarget, setProfitTarget] = useState("");
  const [maxSingleLoss, setMaxSingleLoss] = useState("3.0");
  const [excludedSymbols, setExcludedSymbols] = useState("");
  const [lockedPositions, setLockedPositions] = useState("");

  useEffect(() => {
    dispatch(fetchConfig(accountId));
  }, [dispatch, accountId]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (savedConfig) {
      setConfidence(String(savedConfig.confidence_threshold ?? "0.7"));
      setMaxLoss(String(savedConfig.max_daily_loss_pct ?? "5.0"));
      setInterval_(String(savedConfig.evaluation_interval_s ?? "60"));
      setRisk(String(savedConfig.risk_tolerance ?? "moderate"));
      setDryRun(Boolean(savedConfig.dry_run));
      setMaxDailyActions(String(savedConfig.max_daily_actions ?? "30"));
      setMaxHourlyActions(String(savedConfig.max_hourly_actions ?? "10"));
      setMinPositionAge(String(savedConfig.min_position_age_s ?? "300"));
      setGracePeriod(String(savedConfig.grace_period_s ?? "0"));
      setProfitTarget(savedConfig.daily_profit_target_pct != null ? String(savedConfig.daily_profit_target_pct) : "");
      setMaxSingleLoss(String(savedConfig.max_single_decision_loss_pct ?? "3.0"));
      setExcludedSymbols((savedConfig.excluded_symbols as string[] || []).join(", "));
      setLockedPositions((savedConfig.locked_positions as string[] || []).join(", "));
    }
  }, [savedConfig]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleSave = () => {
    const updates: Record<string, unknown> = {};

    const c = parseFloat(confidence);
    if (!isNaN(c) && c >= 0.3 && c <= 0.95) updates.confidence_threshold = c;
    const l = parseFloat(maxLoss);
    if (!isNaN(l) && l >= 1.0 && l <= 25) updates.max_daily_loss_pct = l;
    const i = parseFloat(interval);
    if (!isNaN(i) && i >= 30 && i <= 300) updates.evaluation_interval_s = i;
    if (risk) updates.risk_tolerance = risk;
    updates.dry_run = dryRun;

    const da = parseInt(maxDailyActions);
    if (!isNaN(da) && da >= 5 && da <= 100) updates.max_daily_actions = da;
    const ha = parseInt(maxHourlyActions);
    if (!isNaN(ha) && ha >= 2 && ha <= 30) updates.max_hourly_actions = ha;
    const mpa = parseInt(minPositionAge);
    if (!isNaN(mpa) && mpa >= 60 && mpa <= 3600) updates.min_position_age_s = mpa;
    const gp = parseInt(gracePeriod);
    if (!isNaN(gp) && gp >= 0 && gp <= 30) updates.grace_period_s = gp;
    const msl = parseFloat(maxSingleLoss);
    if (!isNaN(msl) && msl >= 0.5 && msl <= 10) updates.max_single_decision_loss_pct = msl;

    if (profitTarget.trim()) {
      const pt = parseFloat(profitTarget);
      if (!isNaN(pt) && pt > 0 && pt <= 100) updates.daily_profit_target_pct = pt;
    } else {
      updates.daily_profit_target_pct = null;
    }

    const excluded = excludedSymbols.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    updates.excluded_symbols = excluded;
    const locked = lockedPositions.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
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
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
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
            value={maxLoss}
            onChange={(e) => setMaxLoss(e.target.value)}
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
            value={interval}
            onChange={(e) => setInterval_(e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Risk Tolerance</span>
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
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
            value={maxDailyActions}
            onChange={(e) => setMaxDailyActions(e.target.value)}
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
            value={maxHourlyActions}
            onChange={(e) => setMaxHourlyActions(e.target.value)}
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
            value={minPositionAge}
            onChange={(e) => setMinPositionAge(e.target.value)}
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
            value={gracePeriod}
            onChange={(e) => setGracePeriod(e.target.value)}
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
            value={maxSingleLoss}
            onChange={(e) => setMaxSingleLoss(e.target.value)}
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
            value={profitTarget}
            onChange={(e) => setProfitTarget(e.target.value)}
            placeholder="None"
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
      </div>

      <label className="space-y-1 block">
        <span className="text-xs text-muted-foreground">Excluded Symbols (comma-separated)</span>
        <input
          type="text"
          value={excludedSymbols}
          onChange={(e) => setExcludedSymbols(e.target.value)}
          placeholder="e.g. BTCUSDT, ETHUSDT"
          className="w-full rounded border bg-background px-2 py-1 text-sm"
        />
      </label>

      <label className="space-y-1 block">
        <span className="text-xs text-muted-foreground">Locked Positions (comma-separated)</span>
        <input
          type="text"
          value={lockedPositions}
          onChange={(e) => setLockedPositions(e.target.value)}
          placeholder="e.g. SOLUSDT"
          className="w-full rounded border bg-background px-2 py-1 text-sm"
        />
      </label>

      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
        Dry Run (log only, no execution)
      </label>
      <Button size="sm" disabled={loading} onClick={handleSave}>
        Save Config
      </Button>
    </div>
  );
}
