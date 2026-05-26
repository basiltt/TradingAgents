import { useEffect, useState } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { fetchPerformance } from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface PerformancePanelProps {
  accountId: string;
}

const PERIODS = ["1d", "7d", "30d"] as const;

export function PerformancePanel({ accountId }: PerformancePanelProps) {
  const dispatch = useAppDispatch();
  const [period, setPeriod] = useState<string>("7d");
  const perf = useAppSelector((s: RootState) => s.aiManager.performanceByAccount[accountId]);
  const loading = useAppSelector((s: RootState) => s.aiManager.loading["performance"]);

  useEffect(() => {
    dispatch(fetchPerformance({ accountId, period }));
  }, [dispatch, accountId, period]);

  if (!perf && !loading) {
    return <p className="text-xs text-muted-foreground py-4">No performance data.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        {PERIODS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={period === p ? "default" : "ghost"}
            onClick={() => setPeriod(p)}
          >
            {p}
          </Button>
        ))}
      </div>

      {perf && (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <span className="text-muted-foreground">Total Decisions</span>
            <p className="text-lg font-mono">{perf.total_decisions}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Win Rate</span>
            <p className="text-lg font-mono">{(perf.win_rate * 100).toFixed(1)}%</p>
          </div>
          <div>
            <span className="text-muted-foreground">Total PnL</span>
            <p className={`text-lg font-mono ${perf.net_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {perf.net_pnl >= 0 ? "+" : ""}{perf.net_pnl.toFixed(2)}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Wins / Losses</span>
            <p className="text-lg font-mono">{perf.wins} / {perf.losses}</p>
          </div>
        </div>
      )}
    </div>
  );
}
