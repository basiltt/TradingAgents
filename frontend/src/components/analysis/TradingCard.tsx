import { memo, useState, useCallback } from "react";
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

function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const el = document.createElement("textarea");
    el.value = text;
    el.style.cssText = "position:fixed;top:0;left:0;opacity:0;font-size:16px;";
    document.body.appendChild(el);
    el.focus();
    el.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    if (ok) { resolve(); } else { reject(new Error("execCommand failed")); }
  });
}

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

function formatPrice(n: number): string {
  if (n >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return n.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 8 });
}

function CopyCheckIcon() {
  return (
    <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

function PriceLevel({
  label, value, color, icon, copied, onCopy,
}: {
  label: string;
  value: number;
  color: string;
  icon: string;
  copied: boolean;
  onCopy: (raw: number) => void;
}) {
  const formatted = formatPrice(value);
  return (
    <div className={cn("flex items-center gap-3 px-4 py-3.5 rounded-xl bg-muted/20 border border-border/20 backdrop-blur-sm shadow-sm transition-all duration-300 hover:bg-muted/30")}>
      <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border border-current/10 shadow-inner", color.replace("text-", "bg-").replace(/\d00/, "500/15"))}>
        <svg className={cn("w-4.5 h-4.5", color)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[9px] uppercase tracking-wider text-muted-foreground/60 font-bold">{label}</p>
        <button
          type="button"
          onClick={() => onCopy(value)}
          title="Tap to copy"
          className={cn(
            "text-sm font-black tabular-nums transition-all duration-150 rounded px-1 -mx-1 active:scale-95 flex items-center gap-1.5 cursor-pointer mt-0.5",
            copied ? "text-emerald-400" : cn(color, "hover:opacity-75"),
          )}
        >
          {copied && <CopyCheckIcon />}
          {formatted}
        </button>
      </div>
    </div>
  );
}

function MetricPill({
  label, value, copied, onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: (v: string) => void;
}) {
  return (
    <div className="px-4 py-3 rounded-xl bg-muted/20 border border-border/25 backdrop-blur-sm shadow-sm hover:bg-muted/30 transition-all duration-300">
      <p className="text-[9px] uppercase tracking-wider text-muted-foreground/60 font-bold">{label}</p>
      <button
        type="button"
        onClick={() => onCopy(value)}
        title="Tap to copy"
        className={cn(
          "text-xs font-extrabold mt-1 transition-all duration-150 rounded px-1 -mx-1 active:scale-95 flex items-center gap-1 cursor-pointer",
          copied ? "text-emerald-400" : "text-foreground/90 hover:text-foreground",
        )}
      >
        {copied && <CopyCheckIcon />}
        {value}
      </button>
    </div>
  );
}

export const TradingCard = memo(function TradingCard({ data }: { data: TradeCardData }) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const handleCopy = useCallback((key: string, text: string) => {
    copyToClipboard(text).then(() => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    });
  }, []);

  const actionStyle = ACTION_STYLES[data.action ?? ""] ?? ACTION_STYLES.Hold;
  const ratingColor = RATING_STYLES[data.rating ?? ""] ?? "text-muted-foreground";

  const tpLevels = [data.takeProfit1, data.takeProfit2, data.takeProfit3].filter((v): v is number => v != null);
  const slLevels = [data.stopLoss, data.stopLoss2].filter((v): v is number => v != null);
  const hasPriceLevels = data.entryPrice != null || tpLevels.length > 0 || slLevels.length > 0;
  const hasMetrics = data.riskRewardRatio != null || data.positionSizing != null || data.timeHorizon != null;

  return (
    <div className="glass-card border border-border/50 bg-card/65 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 flex flex-wrap items-center justify-between gap-4 border-b border-border/30">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shadow-inner">
            <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1" />
            </svg>
          </div>
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Trade Order Configurator</h4>
            <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mt-0.5">Execution Parameters</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {data.action && (
            <span className={cn("text-[10px] font-black uppercase tracking-wider px-3.5 py-1 rounded-full border shadow-sm", actionStyle.bg, actionStyle.text, actionStyle.ring.replace("ring-", "border-"))}>
              {data.action.toUpperCase()}
            </span>
          )}
          {data.rating && data.rating !== data.action && (
            <span className={cn("text-[9px] font-black uppercase tracking-wider px-2.5 py-0.75 rounded-full border border-border/30 bg-muted/30 text-muted-foreground", ratingColor)}>
              {data.rating}
            </span>
          )}
        </div>
      </div>

      <div className="p-6 space-y-5">
        {/* Confidence */}
        {data.confidence != null && (
          <div>
            <p className="text-[9px] font-bold text-muted-foreground/60 mb-2 uppercase tracking-wider">Algorithmic Confidence</p>
            <ConfidenceBar value={data.confidence} />
          </div>
        )}

        {/* Price Levels */}
        {hasPriceLevels && (
          <div>
            <p className="text-[9px] font-bold text-muted-foreground/60 mb-3.5 uppercase tracking-wider">Targets & Boundaries</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {data.entryPrice != null && (
                <PriceLevel
                  label="Entry Window"
                  value={data.entryPrice}
                  color="text-blue-400"
                  icon="M12 4v16m0-16l-4 4m4-4l4 4"
                  copied={copiedKey === "entry"}
                  onCopy={(v) => handleCopy("entry", String(v))}
                />
              )}
              {slLevels.map((sl, i) => (
                <PriceLevel
                  key={`sl-${i}`}
                  label={slLevels.length > 1 ? `Stop Loss ${i + 1}` : "Stop Loss"}
                  value={sl}
                  color="text-red-400"
                  icon="M19 14l-7 7m0 0l-7-7m7 7V3"
                  copied={copiedKey === `sl-${i}`}
                  onCopy={(v) => handleCopy(`sl-${i}`, String(v))}
                />
              ))}
              {tpLevels.map((tp, i) => (
                <PriceLevel
                  key={`tp-${i}`}
                  label={tpLevels.length > 1 ? `Take Profit ${i + 1}` : "Take Profit"}
                  value={tp}
                  color="text-emerald-400"
                  icon="M5 10l7-7m0 0l7 7m-7-7v18"
                  copied={copiedKey === `tp-${i}`}
                  onCopy={(v) => handleCopy(`tp-${i}`, String(v))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Metrics */}
        {hasMetrics && (
          <div>
            <p className="text-[9px] font-bold text-muted-foreground/60 mb-2.5 uppercase tracking-wider">Sizing & Ratios</p>
            <div className="flex flex-wrap gap-3.5">
              {data.riskRewardRatio != null && (
                <MetricPill
                  label="Risk/Reward Ratio"
                  value={`1:${data.riskRewardRatio}`}
                  copied={copiedKey === "rr"}
                  onCopy={(v) => handleCopy("rr", v)}
                />
              )}
              {data.positionSizing && (
                <MetricPill
                  label="Position Size Allocation"
                  value={data.positionSizing}
                  copied={copiedKey === "pos"}
                  onCopy={(v) => handleCopy("pos", v)}
                />
              )}
              {data.timeHorizon && (
                <MetricPill
                  label="Time Horizon"
                  value={data.timeHorizon}
                  copied={copiedKey === "th"}
                  onCopy={(v) => handleCopy("th", v)}
                />
              )}
            </div>
          </div>
        )}

        {/* Summary */}
        {data.executiveSummary && (
          <div className="rounded-2xl bg-muted/15 border border-border/20 p-5 shadow-inner">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground/50 font-bold mb-1.5">Executive Summary</p>
            <p className="text-xs text-foreground/80 leading-relaxed font-medium">{data.executiveSummary}</p>
          </div>
        )}
      </div>
    </div>
  );
});
