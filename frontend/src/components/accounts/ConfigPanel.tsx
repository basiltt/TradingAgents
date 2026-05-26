import { useState } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { patchAIManagerConfig } from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface ConfigPanelProps {
  accountId: string;
}

export function ConfigPanel({ accountId }: ConfigPanelProps) {
  const dispatch = useAppDispatch();
  const loading = useAppSelector((s: RootState) => s.aiManager.loading["config"]);

  const [confidence, setConfidence] = useState("0.7");
  const [maxLoss, setMaxLoss] = useState("5.0");
  const [interval, setInterval_] = useState("30");
  const [risk, setRisk] = useState("moderate");
  const [dryRun, setDryRun] = useState(false);

  const handleSave = () => {
    const updates: Record<string, unknown> = {};
    const c = parseFloat(confidence);
    if (!isNaN(c) && c >= 0 && c <= 1) updates.confidence_threshold = c;
    const l = parseFloat(maxLoss);
    if (!isNaN(l) && l >= 0.5 && l <= 50) updates.max_daily_loss_pct = l;
    const i = parseFloat(interval);
    if (!isNaN(i) && i >= 5 && i <= 600) updates.evaluation_interval_s = i;
    if (risk) updates.risk_tolerance = risk;
    updates.dry_run = dryRun;
    if (Object.keys(updates).length > 0) {
      dispatch(patchAIManagerConfig({ accountId, updates }));
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Confidence Threshold</span>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Max Daily Loss %</span>
          <input
            type="number"
            step="0.5"
            min="0.5"
            max="50"
            value={maxLoss}
            onChange={(e) => setMaxLoss(e.target.value)}
            className="w-full rounded border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Eval Interval (s)</span>
          <input
            type="number"
            step="5"
            min="5"
            max="600"
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
      </div>
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
