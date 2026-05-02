import { memo } from "react";
import { Card, CardContent } from "@/components/ui/card";

interface Stats {
  tokens_in: number;
  tokens_out: number;
  llm_calls: number;
  tool_calls: number;
}

interface StatsBarProps {
  stats: Stats | null;
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

export const StatsBar = memo(function StatsBar({ stats }: StatsBarProps) {
  return (
    <Card>
      <CardContent className="pt-4">
        {stats === null ? (
          <p className="text-sm text-muted-foreground">Waiting for stats…</p>
        ) : (
          <div className="flex flex-wrap gap-4 text-sm">
            <span>Tokens In: <strong>{formatNumber(stats.tokens_in)}</strong></span>
            <span>Tokens Out: <strong>{formatNumber(stats.tokens_out)}</strong></span>
            <span>LLM Calls: <strong>{stats.llm_calls}</strong></span>
            <span>Tool Calls: <strong>{stats.tool_calls}</strong></span>
          </div>
        )}
      </CardContent>
    </Card>
  );
});
