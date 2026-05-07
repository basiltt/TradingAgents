import { memo } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MobileCollapse } from "./MobileCollapse";

interface AgentStatusTableProps {
  agents: Record<string, string>;
  isLoading?: boolean;
  config?: Record<string, unknown>;
}

const DEEP_THINK_AGENTS = new Set(["Research Manager", "Portfolio Manager"]);

const AGENT_NAME_TO_KEY: Record<string, string> = {
  "Market Analyst": "market",
  "Social Analyst": "social",
  "News Analyst": "news",
  "Fundamentals Analyst": "fundamentals",
  "Technical Analyst": "crypto_technical",
  "Derivatives Analyst": "crypto_derivatives",
  "Bull Researcher": "bull_researcher",
  "Bear Researcher": "bear_researcher",
  "Research Manager": "research_manager",
  "Trader": "trader",
  "Compliance Officer": "compliance_officer",
  "Execution Monitor": "execution_monitor",
  "Confluence Checker": "confluence_checker",
  "Bull Analyst": "bull_analyst",
  "Bear Analyst": "bear_analyst",
  "Portfolio Manager": "portfolio_manager",
  "Aggressive Analyst": "aggressive_analyst",
  "Neutral Analyst": "neutral_analyst",
  "Conservative Analyst": "conservative_analyst",
};

/**
 * Canonical pipeline stage order — agents are displayed in this order
 * regardless of when their first status event arrives.
 * Agents not in this list are appended at the end in arrival order.
 */
const PIPELINE_ORDER: readonly string[] = [
  // Analysts (parallel)
  "Market Analyst",
  "Social Analyst",
  "News Analyst",
  "Fundamentals Analyst",
  "Crypto Fundamentals Analyst",
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
  // Risk debate (crypto 2-party — same position as stock risk)
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

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  in_progress: "default",
  completed: "secondary",
  failed: "destructive",
};

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

  const overrides = (config?.agent_model_overrides as Record<string, string>) || {};

  const body = isLoading ? (
    <div className="space-y-2">
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-10 rounded-lg" />
      ))}
    </div>
  ) : (
    <>
      {entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 min-h-[12rem] text-center">
          <div className="w-12 h-12 rounded-xl bg-muted/80 flex items-center justify-center mb-3 ring-1 ring-border/50">
            <svg className="w-6 h-6 text-muted-foreground animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <p className="text-sm font-medium text-muted-foreground">Waiting for agents...</p>
          <p className="text-xs text-muted-foreground/60 mt-1">Agents will appear here as they start</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map(([name, status]) => {
            const isDeep = DEEP_THINK_AGENTS.has(name);
            const agentKey = AGENT_NAME_TO_KEY[name];
            const overrideModel = agentKey ? overrides[agentKey] : undefined;
            const model = overrideModel || (isDeep ? deepModel : quickModel);
            const isOverridden = !!overrideModel;
            return (
            <div
              key={name}
              className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT_COLOR[status] ?? "bg-muted-foreground"}`} />
                <span className="text-sm font-medium truncate">{name}</span>
                {model && (
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded truncate max-w-[140px] ${isOverridden ? "bg-amber-500/15 text-amber-400" : isDeep ? "bg-purple-500/15 text-purple-400" : "bg-sky-500/15 text-sky-400"}`}>
                    {model}
                  </span>
                )}
              </div>
              <Badge variant={STATUS_VARIANT[status] ?? "outline"} className="text-xs shrink-0">
                {status.replace(/_/g, " ")}
              </Badge>
            </div>
            );
          })}
        </div>
      )}
    </>
  );

  const countBadge = entries.length > 0
    ? <Badge variant="secondary" className="text-xs">{entries.length}</Badge>
    : null;

  return (
    <div className="md:min-h-[28rem]">
      {/* Mobile: collapsible */}
      <MobileCollapse
        defaultOpen
        storageKey="collapse:agents"
        className="md:hidden"
        title={
          <span className="text-sm font-semibold flex items-center gap-2">
            <AgentsIcon />
            Agents
          </span>
        }
        badge={countBadge}
      >
        <div className="p-3 space-y-0">{body}</div>
      </MobileCollapse>

      {/* Desktop: original Card */}
      <Card className="hidden md:block h-full">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <AgentsIcon />
            Agents
            {countBadge && <div className="ml-auto">{countBadge}</div>}
          </CardTitle>
        </CardHeader>
        <CardContent>{body}</CardContent>
      </Card>
    </div>
  );
});
