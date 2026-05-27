import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { fetchDecisions } from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { Button } from "@/components/ui/button";

interface DecisionLogProps {
  accountId: string;
}

export function DecisionLog({ accountId }: DecisionLogProps) {
  const dispatch = useAppDispatch();
  const decisions = useAppSelector((s: RootState) => s.aiManager.decisionsByAccount[accountId] || []);
  const cursor = useAppSelector((s: RootState) => s.aiManager.decisionCursors[accountId]);
  const loading = useAppSelector((s: RootState) => s.aiManager.loading["decisions"]);

  useEffect(() => {
    dispatch(fetchDecisions({ accountId, limit: 20 }));
  }, [dispatch, accountId]);

  if (!decisions.length && !loading) {
    return <p className="text-xs text-muted-foreground py-4">No decisions yet.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left py-1 pr-2">Time</th>
              <th className="text-left py-1 pr-2">Action</th>
              <th className="text-left py-1 pr-2">Symbol</th>
              <th className="text-right py-1 pr-2">Conf</th>
              <th className="text-left py-1 pr-2">Outcome</th>
              <th className="text-left py-1">Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.id} className="border-b border-border/50">
                <td className="py-1 pr-2 font-mono whitespace-nowrap">
                  {new Date(d.timestamp).toLocaleTimeString()}
                </td>
                <td className="py-1 pr-2">{d.action_taken?.action}</td>
                <td className="py-1 pr-2 font-mono">{d.action_taken?.symbol}</td>
                <td className="py-1 pr-2 text-right font-mono">{((d.confidence ?? 0) * 100).toFixed(0)}%</td>
                <td className={`py-1 pr-2 font-mono ${
                  d.outcome_label === "win" ? "text-green-400" :
                  d.outcome_label === "loss" ? "text-red-400" : "text-muted-foreground"
                }`}>
                  {d.outcome_label || "—"}
                </td>
                <td className="py-1 truncate max-w-[200px]">{d.reasoning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cursor && (
        <Button
          size="sm"
          variant="ghost"
          disabled={loading}
          onClick={() => dispatch(fetchDecisions({ accountId, limit: 20, cursor, append: true }))}
        >
          Load more
        </Button>
      )}
    </div>
  );
}
