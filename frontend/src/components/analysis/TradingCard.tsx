import { memo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TradeCardData } from "./parseTradeCard";

const ACTION_STYLES: Record<string, { bg: string; text: string; ring: string }> = {
  Buy:  { bg: "bg-emerald-500/15", text: "text-emerald-400", ring: "ring-emerald-500/30" },
  Sell: { bg: "bg-red-500/15",     text: "text-red-400",     ring: "ring-red-500/30" },
  Hold: { bg: "bg-amber-500/15",   text: "text-amber-400",   ring: "ring-amber-500/30" },
};

const RATING_STYLES: Record<string, string> = {
  Buy:         "text-emerald-400",
  Overweight:  "text-emerald-300",
  Hold:        "text-amber-400",
  Underweight: "text-orange-400",
  Sell:        "text-red-400",
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value * 10));
  const color = value >= 7 ? "bg-emerald-500" : value >= 4 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex-1 h-2 rounded-full bg-muted/40 overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold text-foreground/70 tabular-nums min-w-[3rem] text-right">{value}/10</span>
    </div>
  );
}

function PriceLevel({ label, value, color, icon }: { label: string; value: number; color: string; icon: string }) {
  return (
    <div className={cn("flex items-center gap-3 px-4 py-3 rounded-lg bg-muted/20 border border-border/20")}>
      <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", color.replace("text-", "bg-").replace(/\d00/, "500/15"))}>
        <svg className={cn("w-4 h-4", color)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground/50 font-medium">{label}</p>
        <p className={cn("text-sm font-semibold tabular-nums", color)}>{formatPrice(value)}</p>
      </div>
    </div>
  );
}

function formatPrice(n: number): string {
  if (n >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return n.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 8 });
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3.5 py-2 rounded-lg bg-muted/20 border border-border/20">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground/50 font-medium">{label}</p>
      <p className="text-sm font-medium text-foreground/80 mt-0.5">{value}</p>
    </div>
  );
}

export const TradingCard = memo(function TradingCard({ data }: { data: TradeCardData }) {
  const actionStyle = ACTION_STYLES[data.action ?? ""] ?? ACTION_STYLES.Hold;
  const ratingColor = RATING_STYLES[data.rating ?? ""] ?? "text-muted-foreground";

  const tpLevels = [data.takeProfit1, data.takeProfit2, data.takeProfit3].filter((v): v is number => v != null);
  const slLevels = [data.stopLoss, data.stopLoss2].filter((v): v is number => v != null);
  const hasPriceLevels = data.entryPrice != null || tpLevels.length > 0 || slLevels.length > 0;
  const hasMetrics = data.riskRewardRatio != null || data.positionSizing != null || data.timeHorizon != null;

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        {/* Header */}
        <div className="px-6 py-5 flex flex-wrap items-center gap-4 border-b border-border/30">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold tracking-tight">Trade Setup</h2>
          </div>

          <div className="flex items-center gap-2.5 ml-auto">
            {data.action && (
              <Badge className={cn("text-sm font-bold px-3.5 py-1 ring-1", actionStyle.bg, actionStyle.text, actionStyle.ring)}>
                {data.action.toUpperCase()}
              </Badge>
            )}
            {data.rating && data.rating !== data.action && (
              <Badge variant="outline" className={cn("text-xs font-medium", ratingColor)}>
                {data.rating}
              </Badge>
            )}
          </div>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Confidence */}
          {data.confidence != null && (
            <div>
              <p className="text-xs font-medium text-muted-foreground/60 mb-2 uppercase tracking-wider">Confidence</p>
              <ConfidenceBar value={data.confidence} />
            </div>
          )}

          {/* Price Levels */}
          {hasPriceLevels && (
            <div>
              <p className="text-xs font-medium text-muted-foreground/60 mb-3 uppercase tracking-wider">Price Levels</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                {data.entryPrice != null && (
                  <PriceLevel label="Entry" value={data.entryPrice} color="text-blue-400" icon="M12 4v16m0-16l-4 4m4-4l4 4" />
                )}
                {slLevels.map((sl, i) => (
                  <PriceLevel
                    key={`sl-${i}`}
                    label={slLevels.length > 1 ? `Stop Loss ${i + 1}` : "Stop Loss"}
                    value={sl}
                    color="text-red-400"
                    icon="M19 14l-7 7m0 0l-7-7m7 7V3"
                  />
                ))}
                {tpLevels.map((tp, i) => (
                  <PriceLevel
                    key={`tp-${i}`}
                    label={tpLevels.length > 1 ? `Take Profit ${i + 1}` : "Take Profit"}
                    value={tp}
                    color="text-emerald-400"
                    icon="M5 10l7-7m0 0l7 7m-7-7v18"
                  />
                ))}
              </div>
            </div>
          )}

          {/* Metrics */}
          {hasMetrics && (
            <div className="flex flex-wrap gap-2.5">
              {data.riskRewardRatio != null && (
                <MetricPill label="Risk/Reward" value={`1:${data.riskRewardRatio}`} />
              )}
              {data.positionSizing && (
                <MetricPill label="Position Size" value={data.positionSizing} />
              )}
              {data.timeHorizon && (
                <MetricPill label="Time Horizon" value={data.timeHorizon} />
              )}
            </div>
          )}

          {/* Summary */}
          {data.executiveSummary && (
            <div className="rounded-lg bg-muted/15 border border-border/20 px-4 py-3.5">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground/50 font-medium mb-1.5">Executive Summary</p>
              <p className="text-sm text-foreground/70 leading-relaxed">{data.executiveSummary}</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
