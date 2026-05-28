import { useMemo, useEffect } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { fetchInsights } from "@/store/ai-manager-slice";
import { makeSelectInsights } from "@/store/ai-manager-selectors";
import { TrendingUp } from "lucide-react";

interface MarketInsightsPanelProps { accountId: string; }

const SCORE_COLORS: Record<string, string> = {
  good: "text-emerald-400 bg-emerald-500/10",
  neutral: "text-sky-400 bg-sky-500/10",
  caution: "text-amber-400 bg-amber-500/10",
  danger: "text-red-400 bg-red-500/10",
};

export default function MarketInsightsPanel({ accountId }: MarketInsightsPanelProps) {
  const dispatch = useAppDispatch();
  const selectInsights = useMemo(() => makeSelectInsights(accountId), [accountId]);
  const insights = useAppSelector(selectInsights);
  const fsmState = useAppSelector(s => s.aiManager.statusByAccount[accountId]?.state);

  useEffect(() => {
    if (fsmState && fsmState !== "sleeping") {
      dispatch(fetchInsights(accountId));
    }
  }, [dispatch, accountId, fsmState]);

  if (fsmState === "sleeping") {
    return (
      <div className="rounded-2xl p-5 text-center text-muted-foreground/50" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
        <TrendingUp className="w-6 h-6 mx-auto mb-2 opacity-40" />
        <p className="text-xs">No market insights — AI is sleeping</p>
      </div>
    );
  }

  const scoreColor = insights?.day_score_label ? SCORE_COLORS[insights.day_score_label] || SCORE_COLORS.neutral : SCORE_COLORS.neutral;

  return (
    <div className="rounded-2xl p-5 space-y-4" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
      <div className="flex items-center gap-2">
        <TrendingUp className="w-4 h-4 text-emerald-400" />
        <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">Market Insights</h4>
      </div>

      {/* Day Score */}
      <div className="flex items-center gap-4">
        <div className={`rounded-xl px-4 py-2 ${scoreColor}`}>
          <span className="text-2xl font-bold">{insights?.day_score ?? "—"}</span>
          <span className="text-xs ml-1 opacity-70">/100</span>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium capitalize">{insights?.day_score_label || "Unknown"} day</p>
          {insights?.day_score_justification && (
            <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">{insights.day_score_justification}</p>
          )}
        </div>
      </div>

      {/* Commentary */}
      {insights?.latest_commentary && (
        <div className="rounded-lg p-3" style={{ background: "var(--neu-surface-deep)", boxShadow: "var(--neu-shadow-inset)" }}>
          <div className="flex items-center gap-2 mb-1">
            {insights.session && <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-400">{insights.session}</span>}
            <span className="text-[10px] text-muted-foreground/40">
              {new Date(insights.latest_commentary.generated_at).toLocaleTimeString()}
            </span>
          </div>
          <p className="text-xs text-muted-foreground/80 leading-relaxed">{insights.latest_commentary.summary_text}</p>
        </div>
      )}

      {/* Quick Stats */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground/50">
        {insights?.correlation_heat != null && (
          <span>Correlation: {(insights.correlation_heat * 100).toFixed(0)}%</span>
        )}
        {insights?.active_sweeps && insights.active_sweeps.length > 0 && (
          <span className="text-amber-400">{insights.active_sweeps.length} active sweep{insights.active_sweeps.length > 1 ? "s" : ""}</span>
        )}
      </div>
    </div>
  );
}
