import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import {
  fetchAIManagerStatus,
  enableAIManager,
  disableAIManager,
  pauseAIManager,
  resumeAIManager,
  killAIManager,
  resetKillSwitch,
  globalKill,
} from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface AIManagerCardProps {
  accountId: string;
}

const STATE_COLORS: Record<string, string> = {
  sleeping: "text-gray-400",
  monitoring: "text-blue-400",
  analyzing: "text-yellow-400",
  executing: "text-green-400",
  paused: "text-orange-400",
  error: "text-red-400",
};

export function AIManagerCard({ accountId }: AIManagerCardProps) {
  const dispatch = useAppDispatch();
  const status = useAppSelector((s: RootState) => s.aiManager.statusByAccount[accountId]);
  const loading = useAppSelector((s: RootState) => s.aiManager.loading);

  useEffect(() => {
    dispatch(fetchAIManagerStatus(accountId));
  }, [dispatch, accountId]);

  if (!status) {
    return (
      <div className="rounded-lg border p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">AI Manager</h3>
          <Button
            size="sm"
            variant="outline"
            disabled={loading["enable"]}
            onClick={() => dispatch(enableAIManager(accountId))}
          >
            Enable
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">Not configured for this account.</p>
      </div>
    );
  }

  const stateColor = STATE_COLORS[status.state] || "text-gray-400";

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">AI Manager</h3>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono ${stateColor}`}>{status.state}</span>
          {status.enabled ? (
            <Button
              size="sm"
              variant="destructive"
              disabled={loading["disable"]}
              onClick={() => dispatch(disableAIManager(accountId))}
            >
              Disable
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={loading["enable"]}
              onClick={() => dispatch(enableAIManager(accountId))}
            >
              Enable
            </Button>
          )}
        </div>
      </div>

      {status.kill_switch && (
        <div className="rounded bg-red-900/20 border border-red-500/30 px-3 py-2 text-xs text-red-400 flex items-center justify-between">
          <span>Kill switch active</span>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading["resetKill"]}
            onClick={() => dispatch(resetKillSwitch(accountId))}
          >
            Reset
          </Button>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-muted-foreground">Actions</span>
          <p className="font-mono">{status.actions_today}</p>
        </div>
        <div>
          <span className="text-muted-foreground">Budget</span>
          <p className="font-mono">{status.budget_remaining.actions}</p>
        </div>
        <div>
          <span className="text-muted-foreground">Circuit</span>
          <p className={`font-mono ${status.circuit_breaker.active ? "text-red-400" : ""}`}>
            {status.circuit_breaker.count}{status.circuit_breaker.active ? " ⚠" : ""}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground">Degradation</span>
          <p className="font-mono">Tier {status.degradation_tier ?? 0}</p>
        </div>
        <div className="col-span-2">
          <span className="text-muted-foreground">Last Analysis</span>
          <p className="font-mono">
            {status.last_analysis_at
              ? new Date(status.last_analysis_at).toLocaleTimeString()
              : "—"}
          </p>
        </div>
      </div>

      {status.enabled && (
        <div className="flex gap-2">
          {status.state === "paused" ? (
            <Button size="sm" variant="outline" disabled={loading["resume"]} onClick={() => dispatch(resumeAIManager(accountId))}>
              Resume
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={loading["pause"]} onClick={() => dispatch(pauseAIManager(accountId))}>
              Pause
            </Button>
          )}
          <Button size="sm" variant="destructive" disabled={loading["kill"]} onClick={() => dispatch(killAIManager(accountId))}>
            Kill
          </Button>
          <Button
            size="sm"
            variant="destructive"
            className="ml-auto"
            disabled={loading["globalKill"]}
            onClick={() => { if (confirm("Kill ALL AI managers across all accounts?")) dispatch(globalKill()); }}
          >
            Global Kill
          </Button>
        </div>
      )}
    </div>
  );
}
