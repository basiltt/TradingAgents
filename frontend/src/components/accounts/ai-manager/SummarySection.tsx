import { useMemo } from "react";
import { useAppSelector } from "@/store";
import { makeSelectInsights } from "@/store/ai-manager-selectors";
import { Activity } from "lucide-react";

interface SummarySectionProps { accountId: string; }

const STATE_LABELS: Record<string, string> = {
  sleeping: "AI is sleeping",
  monitoring: "AI is actively monitoring",
  analyzing: "AI is analyzing positions",
  executing: "AI is executing a trade",
  paused: "AI is paused",
  error: "AI encountered an error",
};

const SCORE_PILLS: Record<string, string> = {
  good: "bg-emerald-500/20 text-emerald-400",
  neutral: "bg-sky-500/20 text-sky-400",
  caution: "bg-amber-500/20 text-amber-400",
  danger: "bg-red-500/20 text-red-400",
};

export default function SummarySection({ accountId }: SummarySectionProps) {
  const selectInsights = useMemo(() => makeSelectInsights(accountId), [accountId]);
  const insights = useAppSelector(selectInsights);
  const status = useAppSelector(s => s.aiManager.statusByAccount[accountId]);

  const heartbeatAge = useMemo(() => {
    if (!status?.last_analysis_at) return null;
    return Math.floor((Date.now() - new Date(status.last_analysis_at).getTime()) / 1000);
  }, [status?.last_analysis_at]);

  const heartbeatColor = heartbeatAge == null ? "bg-zinc-500" : heartbeatAge < 30 ? "bg-emerald-400" : heartbeatAge < 60 ? "bg-amber-400" : "bg-red-400";

  const tokenPct = status?.token_budget?.pct ?? 0;

  return (
    <div className="rounded-2xl p-4 space-y-3" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
      {/* Row 1: Day score + State */}
      <div className="flex items-center gap-3">
        {insights?.day_score_label && (
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${SCORE_PILLS[insights.day_score_label] || SCORE_PILLS.neutral}`}>
            {insights.day_score}
          </span>
        )}
        <span className="text-xs text-muted-foreground/70">{STATE_LABELS[status?.state || "sleeping"] || "Unknown state"}</span>
      </div>

      {/* Row 2: Positions + UPnL */}
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground/50">
        {status?.live_positions && (
          <>
            <span>{status.live_positions.length} position{status.live_positions.length !== 1 ? "s" : ""}</span>
            <span>UPnL: {status.live_positions.reduce((sum, p) => sum + p.current_upnl, 0).toFixed(2)}</span>
          </>
        )}
      </div>

      {/* Row 3: Token budget + Heartbeat */}
      <div className="flex items-center gap-3">
        <div className="flex-1 h-1.5 rounded-full bg-muted/20 overflow-hidden">
          <div className="h-full rounded-full bg-violet-500/60 transition-all" style={{ width: `${Math.min(100, tokenPct)}%` }} />
        </div>
        <span className="text-[9px] text-muted-foreground/40">{tokenPct.toFixed(0)}%</span>
        <div className="flex items-center gap-1">
          <Activity className="w-3 h-3 text-muted-foreground/40" />
          <div className={`w-2 h-2 rounded-full ${heartbeatColor} ${heartbeatAge != null && heartbeatAge < 30 ? "animate-pulse" : ""}`} />
        </div>
      </div>
    </div>
  );
}
