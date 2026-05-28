/* eslint-disable react-refresh/only-export-components */
import { useState, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
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
  { key: "ai_account_manager", label: "AI Account Manager", tier: "deep" },
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
  { key: "ai_account_manager", label: "AI Account Manager", tier: "deep" },
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
    <div className="space-y-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="glass-card flex w-full items-center gap-3 rounded-[calc(var(--radius)*1.4)] px-4 py-4 text-left shadow-[var(--shadow-soft)]"
      >
        <span className="inline-flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.05)] border border-primary/20 bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
          <svg
            className={cn("size-4 transition-transform duration-200", open && "rotate-90")}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-[-0.03em] text-foreground">Agent model overrides</div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Per-role routing for specialist research agents</div>
        </div>
        <Badge variant={overrideCount > 0 ? "default" : "secondary"} className="ml-auto px-3 py-1 text-[10px] tracking-[0.16em]">
          {overrideCount} override{overrideCount === 1 ? "" : "s"}
        </Badge>
      </button>

      {open ? (
        <div className="glass-card space-y-4 rounded-[calc(var(--radius)*1.5)] border border-border/60 bg-card/72 p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <p className="max-w-2xl text-[12px] leading-6 text-muted-foreground">
              Override individual agent models when a specific analyst, trader, or portfolio role should use a different model than the global deep or quick setting.
            </p>
            {overrideCount > 0 ? (
              <Button type="button" variant="ghost" size="xs" onClick={handleReset} className="uppercase tracking-[0.14em]">
                Reset all
              </Button>
            ) : null}
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {agents.map((agent) => (
              <div
                key={agent.key}
                className="rounded-[calc(var(--radius)*1.15)] border border-border/55 bg-background/65 px-4 py-3.5 shadow-[var(--shadow-soft)]"
              >
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Label className="text-sm font-semibold text-foreground">{agent.label}</Label>
                  <Badge
                    variant={agent.tier === "deep" ? "default" : "secondary"}
                    className={cn(
                      "px-2.5 py-0.5 text-[10px] tracking-[0.16em] uppercase",
                      agent.tier === "deep" && "bg-primary/12 text-primary"
                    )}
                  >
                    {agent.tier}
                  </Badge>
                </div>

                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <ModelSelect
                      options={modelOptions}
                      value={overrides[agent.key] ?? ""}
                      onChange={(v) => handleChange(agent.key, v)}
                      placeholder={`Default (${agent.tier})`}
                    />
                  </div>

                  {overrides[agent.key] ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => handleChange(agent.key, "")}
                      aria-label={`Reset ${agent.label} override`}
                    >
                      <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
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
