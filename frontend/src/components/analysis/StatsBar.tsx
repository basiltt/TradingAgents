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
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString();
}

function StatCard({ label, value, icon, iconColor }: { label: string; value: string; icon: React.ReactNode; iconColor?: string }) {
  return (
    <Card className="shadow-sm">
      <CardContent className="pt-4 pb-3">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${iconColor ?? "bg-muted text-muted-foreground"}`}>
            {icon}
          </div>
          <div>
            <p className="text-lg font-bold leading-tight tracking-tight">{value}</p>
            <p className="text-[11px] text-muted-foreground font-medium">{label}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export const StatsBar = memo(function StatsBar({ stats }: StatsBarProps) {
  if (stats === null) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {["Tokens In", "Tokens Out", "LLM Calls", "Tool Calls"].map((label) => (
          <Card key={label}>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-muted animate-pulse" />
                <div>
                  <p className="text-lg font-bold leading-tight text-muted-foreground">--</p>
                  <p className="text-[11px] text-muted-foreground font-medium">{label}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard
        label="Tokens In"
        value={formatNumber(stats.tokens_in)}
        iconColor="bg-blue-500/10 text-blue-600 dark:text-blue-400"
        icon={
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
        }
      />
      <StatCard
        label="Tokens Out"
        value={formatNumber(stats.tokens_out)}
        iconColor="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
        icon={
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
          </svg>
        }
      />
      <StatCard
        label="LLM Calls"
        value={formatNumber(stats.llm_calls)}
        iconColor="bg-primary/10 text-primary"
        icon={
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        }
      />
      <StatCard
        label="Tool Calls"
        value={formatNumber(stats.tool_calls)}
        iconColor="bg-amber-500/10 text-amber-600 dark:text-amber-400"
        icon={
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        }
      />
    </div>
  );
});
