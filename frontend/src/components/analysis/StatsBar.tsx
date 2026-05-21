import { memo } from "react";
import { MobileCollapse } from "./MobileCollapse";

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
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString();
}

function StatCard({ label, value, icon, iconColor }: { label: string; value: string; icon: React.ReactNode; iconColor?: string }) {
  return (
    <div className="glass-card border border-border/40 bg-card/65 rounded-2xl p-4 shadow-sm flex items-center gap-3.5 transition-all duration-300 hover:scale-[1.02] hover:border-border/60 hover:bg-card/85">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-inner ${iconColor ?? "bg-muted text-muted-foreground"}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xl font-black leading-none tracking-tight text-foreground tabular-nums">{value}</p>
        <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider mt-1">{label}</p>
      </div>
    </div>
  );
}

const STAT_LABELS = ["Tokens In", "Tokens Out", "LLM Calls", "Tool Calls"];

export const StatsBar = memo(function StatsBar({ stats }: StatsBarProps) {
  const grid = (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3.5">
      {stats === null ? (
        STAT_LABELS.map((label) => (
          <div key={label} className="glass-card border border-border/30 bg-card/45 rounded-2xl p-4 shadow-sm flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-muted animate-pulse shrink-0" />
            <div className="space-y-1.5 flex-1">
              <div className="h-5 w-12 bg-muted rounded animate-pulse text-transparent select-none">--</div>
              <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">{label}</p>
            </div>
          </div>
        ))
      ) : (
        <>
          <StatCard
            label="Tokens In"
            value={formatNumber(stats.tokens_in)}
            iconColor="bg-blue-500/10 text-blue-500 border border-blue-500/15"
            icon={
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
              </svg>
            }
          />
          <StatCard
            label="Tokens Out"
            value={formatNumber(stats.tokens_out)}
            iconColor="bg-emerald-500/10 text-emerald-500 border border-emerald-500/15"
            icon={
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
              </svg>
            }
          />
          <StatCard
            label="LLM Calls"
            value={formatNumber(stats.llm_calls)}
            iconColor="bg-primary/10 text-primary border border-primary/15"
            icon={
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            }
          />
          <StatCard
            label="Tool Calls"
            value={formatNumber(stats.tool_calls)}
            iconColor="bg-amber-500/10 text-amber-500 border border-amber-500/15"
            icon={
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
          />
        </>
      )}
    </div>
  );

  return (
    <MobileCollapse
      defaultOpen={true}
      storageKey="collapse:stats"
      title={
        <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-2">
          <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          Resource Statistics
        </span>
      }
    >
      <div className="p-3 md:p-0">{grid}</div>
    </MobileCollapse>
  );
});
