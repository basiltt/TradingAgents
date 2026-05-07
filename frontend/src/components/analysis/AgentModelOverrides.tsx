import { useState, useMemo } from "react";
import { ModelSelect } from "@/components/ui/model-select";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "tradingagents_agent_model_overrides";

interface AgentDef {
  key: string;
  label: string;
  tier: "deep" | "quick";
}

const STOCK_AGENTS: AgentDef[] = [
  { key: "market", label: "Market Analyst", tier: "quick" },
  { key: "social", label: "Social Analyst", tier: "quick" },
  { key: "news", label: "News Analyst", tier: "quick" },
  { key: "fundamentals", label: "Fundamentals Analyst", tier: "quick" },
  { key: "bull_researcher", label: "Bull Researcher", tier: "quick" },
  { key: "bear_researcher", label: "Bear Researcher", tier: "quick" },
  { key: "research_manager", label: "Research Manager", tier: "deep" },
  { key: "trader", label: "Trader", tier: "quick" },
  { key: "compliance_officer", label: "Compliance Officer", tier: "quick" },
  { key: "aggressive_analyst", label: "Aggressive Analyst", tier: "quick" },
  { key: "neutral_analyst", label: "Neutral Analyst", tier: "quick" },
  { key: "conservative_analyst", label: "Conservative Analyst", tier: "quick" },
  { key: "portfolio_manager", label: "Portfolio Manager", tier: "deep" },
  { key: "execution_monitor", label: "Execution Monitor", tier: "quick" },
];

const CRYPTO_AGENTS: AgentDef[] = [
  { key: "crypto_technical", label: "Technical Analyst", tier: "quick" },
  { key: "crypto_derivatives", label: "Derivatives Analyst", tier: "quick" },
  { key: "crypto_news", label: "News Analyst", tier: "quick" },
  { key: "crypto_fundamentals", label: "Fundamentals Analyst", tier: "quick" },
  { key: "crypto_social", label: "Social Analyst", tier: "quick" },
  { key: "confluence_checker", label: "Confluence Checker", tier: "quick" },
  { key: "bull_researcher", label: "Bull Researcher", tier: "quick" },
  { key: "bear_researcher", label: "Bear Researcher", tier: "quick" },
  { key: "research_manager", label: "Research Manager", tier: "deep" },
  { key: "trader", label: "Trader", tier: "quick" },
  { key: "compliance_officer", label: "Compliance Officer", tier: "quick" },
  { key: "bull_analyst", label: "Bull Analyst", tier: "quick" },
  { key: "bear_analyst", label: "Bear Analyst", tier: "quick" },
  { key: "portfolio_manager", label: "Portfolio Manager", tier: "deep" },
  { key: "execution_monitor", label: "Execution Monitor", tier: "quick" },
];

function loadOverrides(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function saveOverrides(o: Record<string, string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(o));
}

interface Props {
  assetType: "stock" | "crypto";
  modelOptions: { label: string; value: string }[];
  overrides: Record<string, string>;
  onChange: (overrides: Record<string, string>) => void;
}

export function AgentModelOverrides({ assetType, modelOptions, overrides, onChange }: Props) {
  const [open, setOpen] = useState(false);

  const agents = assetType === "crypto" ? CRYPTO_AGENTS : STOCK_AGENTS;
  const overrideCount = useMemo(
    () => agents.filter((a) => overrides[a.key]).length,
    [overrides, agents],
  );

  function handleChange(key: string, value: string) {
    const next = { ...overrides };
    if (value) {
      next[key] = value;
    } else {
      delete next[key];
    }
    onChange(next);
    saveOverrides(next);
  }

  function handleReset() {
    onChange({});
    saveOverrides({});
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        <svg
          className={cn("w-4 h-4 transition-transform duration-200", open && "rotate-90")}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        Agent Model Overrides
        {overrideCount > 0 && (
          <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
            {overrideCount} override{overrideCount > 1 ? "s" : ""}
          </span>
        )}
      </button>

      {open && (
        <div className="mt-4 space-y-3 pl-1">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              Override the model used by individual agents. Empty = uses global Deep/Quick model.
            </p>
            {overrideCount > 0 && (
              <Button type="button" variant="ghost" size="sm" onClick={handleReset} className="text-xs h-7 px-2">
                Reset All
              </Button>
            )}
          </div>

          <div className="grid gap-3">
            {agents.map((agent) => (
              <div key={agent.key} className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <Label className="text-xs font-medium">{agent.label}</Label>
                  <span className={cn(
                    "text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide",
                    agent.tier === "deep"
                      ? "bg-violet-500/10 text-violet-400"
                      : "bg-sky-500/10 text-sky-400",
                  )}>
                    {agent.tier}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="flex-1">
                    <ModelSelect
                      options={modelOptions}
                      value={overrides[agent.key] ?? ""}
                      onChange={(v) => handleChange(agent.key, v)}
                      placeholder={`Default (${agent.tier})`}
                    />
                  </div>
                  {overrides[agent.key] && (
                    <button
                      type="button"
                      onClick={() => handleChange(agent.key, "")}
                      className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                      title="Reset to default"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export { STORAGE_KEY as AGENT_OVERRIDES_STORAGE_KEY, loadOverrides, saveOverrides };

export function filterOverridesForAssetType(
  overrides: Record<string, string>,
  assetType: "stock" | "crypto",
): Record<string, string> {
  const agents = assetType === "crypto" ? CRYPTO_AGENTS : STOCK_AGENTS;
  const validKeys = new Set(agents.map((a) => a.key));
  const filtered: Record<string, string> = {};
  for (const [key, value] of Object.entries(overrides)) {
    if (value && validKeys.has(key)) {
      filtered[key] = value;
    }
  }
  return filtered;
}
