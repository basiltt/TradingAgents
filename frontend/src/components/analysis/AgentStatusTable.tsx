import { memo } from "react";
import { cn } from "@/lib/utils";
import { MobileCollapse } from "./MobileCollapse";

interface AgentStatusTableProps {
  agents: Record<string, string>;
  isLoading?: boolean;
  config?: Record<string, unknown>;
}

const DEEP_THINK_AGENTS = new Set(["Research Manager", "Portfolio Manager"]);

const AGENT_NAME_TO_KEY_STOCK: Record<string, string> = {
  "Market Analyst": "market",
  "Social Analyst": "social",
  "News Analyst": "news",
  "Fundamentals Analyst": "fundamentals",
  "Bull Researcher": "bull_researcher",
  "Bear Researcher": "bear_researcher",
  "Research Manager": "research_manager",
  "Trader": "trader",
  "Compliance Officer": "compliance_officer",
  "Execution Monitor": "execution_monitor",
  "Portfolio Manager": "portfolio_manager",
  "Aggressive Analyst": "aggressive_analyst",
  "Neutral Analyst": "neutral_analyst",
  "Conservative Analyst": "conservative_analyst",
};

const AGENT_NAME_TO_KEY_CRYPTO: Record<string, string> = {
  "Technical Analyst": "crypto_technical",
  "Derivatives Analyst": "crypto_derivatives",
  "Social Analyst": "crypto_social",
  "News Analyst": "crypto_news",
  "Fundamentals Analyst": "crypto_fundamentals",
  "Confluence Checker": "confluence_checker",
  "Bull Researcher": "bull_researcher",
  "Bear Researcher": "bear_researcher",
  "Research Manager": "research_manager",
  "Trader": "trader",
  "Compliance Officer": "compliance_officer",
  "Execution Monitor": "execution_monitor",
  "Bull Analyst": "bull_analyst",
  "Bear Analyst": "bear_analyst",
  "Portfolio Manager": "portfolio_manager",
};

/**
 * Canonical pipeline stage order — agents are displayed in this order
 * regardless of when their first status event arrives.
 * Agents not in this list are appended at the end in arrival order.
 */
const PIPELINE_ORDER: readonly string[] = [
  // Analysts (parallel)
  "Market Analyst",
  "Technical Analyst",
  "Derivatives Analyst",
  "Social Analyst",
  "News Analyst",
  "Fundamentals Analyst",
  // Confluence
  "Confluence Checker",
  // Research debate
  "Bull Researcher",
  "Bear Researcher",
  "Research Manager",
  // Trader
  "Trader",
  // Compliance gate
  "Compliance Officer",
  // Risk debate (stock 3-party)
  "Aggressive Analyst",
  "Conservative Analyst",
  "Neutral Analyst",
  // Risk debate (crypto 2-party)
  "Bull Analyst",
  "Bear Analyst",
  // Final decision
  "Portfolio Manager",
  "Execution Monitor",
] as const;

const _orderIndex = new Map(PIPELINE_ORDER.map((name, i) => [name, i]));

function sortedAgentEntries(agents: Record<string, string>): [string, string][] {
  return Object.entries(agents).sort(([a], [b]) => {
    const ai = _orderIndex.get(a) ?? 999;
    const bi = _orderIndex.get(b) ?? 999;
    return ai - bi;
  });
}



const STATUS_DOT_COLOR: Record<string, string> = {
  in_progress: "bg-primary animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-destructive",
};

const AgentsIcon = () => (
  <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
  </svg>
);

export const AgentStatusTable = memo(function AgentStatusTable({ agents, isLoading, config }: AgentStatusTableProps) {
  const entries = sortedAgentEntries(agents);
  const deepModel = config?.deep_think_llm ? String(config.deep_think_llm) : "";
  const quickModel = config?.quick_think_llm ? String(config.quick_think_llm) : "";

  const assetType = config?.asset_type ? String(config.asset_type) : "stock";
  const agentNameToKey = assetType === "crypto" ? AGENT_NAME_TO_KEY_CRYPTO : AGENT_NAME_TO_KEY_STOCK;
  const overrides = (config?.agent_model_overrides as Record<string, string>) || {};

  const body = isLoading ? (
    <div className="space-y-3">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="h-12 bg-muted/40 rounded-xl animate-pulse" />
      ))}
    </div>
  ) : (
    <>
      {entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center h-full">
          <div className="w-14 h-14 rounded-2xl bg-muted/50 flex items-center justify-center mb-4 border border-border/20 shadow-inner">
            <svg className="w-6 h-6 text-muted-foreground animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <p className="text-sm font-bold text-foreground/80">Waiting for agents...</p>
          <p className="text-xs text-muted-foreground mt-1">Agents will appear as they begin their pipeline tasks.</p>
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
          {entries.map(([name, status]) => {
            const isDeep = DEEP_THINK_AGENTS.has(name);
            const agentKey = agentNameToKey[name];
            const overrideModel = agentKey ? overrides[agentKey] : undefined;
            const model = overrideModel || (isDeep ? deepModel : quickModel);
            const isOverridden = !!overrideModel;
            return (
              <div
                key={name}
                className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-border/30 bg-muted/20 hover:bg-muted/40 hover:border-border/50 transition-all duration-300 shadow-sm"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`w-2 h-2 rounded-full shrink-0 shadow-sm ${STATUS_DOT_COLOR[status] ?? "bg-muted-foreground"}`} />
                  <span className="text-xs font-bold text-foreground truncate">{name}</span>
                  {model && (
                    <span className={`text-[9px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded truncate max-w-[120px] border ${isOverridden ? "bg-amber-500/10 border-amber-500/25 text-amber-500" : isDeep ? "bg-purple-500/10 border-purple-500/25 text-purple-500" : "bg-sky-500/10 border-sky-500/25 text-sky-500"}`}>
                      {model}
                    </span>
                  )}
                </div>
                <span className={cn(
                  "text-[9px] font-black uppercase tracking-wider px-2.5 py-0.75 rounded border shadow-sm shrink-0",
                  status === "in_progress" ? "bg-primary/10 border-primary/20 text-primary animate-pulse-slow" :
                  status === "completed" ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-500" :
                  "bg-destructive/10 border-destructive/20 text-destructive"
                )}>
                  {status.replace(/_/g, " ")}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </>
  );

  const countBadge = entries.length > 0 ? (
    <span className="inline-flex items-center text-[10px] font-black bg-muted/80 text-foreground px-2 py-0.5 rounded-full border border-border/30">
      {entries.length}
    </span>
  ) : null;

  return (
    <div className="h-full">
      {/* Mobile: collapsible */}
      <MobileCollapse
        defaultOpen
        storageKey="collapse:agents"
        className="md:hidden"
        title={
          <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-2">
            <AgentsIcon />
            Pipeline Pipeline
          </span>
        }
        badge={countBadge}
      >
        <div className="p-4 space-y-0">{body}</div>
      </MobileCollapse>

      {/* Desktop: Glass Card */}
      <div className="hidden md:flex flex-col h-full glass-card border border-border/50 rounded-2xl p-5 bg-card/65 shadow-sm min-h-[460px]">
        <div className="flex items-center justify-between pb-4 border-b border-border/30 mb-4 shrink-0">
          <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-2 text-foreground/90">
            <AgentsIcon />
            Active Agent Pipeline
          </h3>
          {countBadge}
        </div>
        <div className="flex-1 min-h-0 flex flex-col justify-center">
          <div className="h-full flex-1">
            {body}
          </div>
        </div>
      </div>
    </div>
  );
});
