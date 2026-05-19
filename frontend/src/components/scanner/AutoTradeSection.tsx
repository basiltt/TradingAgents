import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, type TradingAccount, type AutoTradeConfig } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "tradingagents_auto_trade_configs";

const DEFAULT_CONFIG: Omit<AutoTradeConfig, "account_id"> = {
  direction: "straight",
  leverage: 20,
  capital_pct: 5,
  take_profit_pct: 150,
  stop_loss_pct: 100,
  min_score: 3,
  confidence_filter: "any",
  signal_sides: "both",
  max_trades: 10,
  max_drawdown_pct: 50,
  target_goal_type: null,
  target_goal_value: null,
  execution_mode: "immediate",
};

function loadConfigs(): AutoTradeConfig[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveConfigs(configs: AutoTradeConfig[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(configs));
}

interface AutoTradeSectionProps {
  value: AutoTradeConfig[];
  onChange: (configs: AutoTradeConfig[]) => void;
}

export function AutoTradeSection({ value, onChange }: AutoTradeSectionProps) {
  const [expanded, setExpanded] = useState(value.length > 0);

  useEffect(() => {
    if (value.length > 0) setExpanded(true);
  }, [value.length]);

  const { data: allAccounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(),
    staleTime: 60_000,
  });
  const accounts = allAccounts.filter((a) => a.is_active);

  const addConfig = () => {
    const firstAvailableAccount = accounts.find(
      (a) => !value.some((c) => c.account_id === a.id)
    );
    const newConfig: AutoTradeConfig = {
      ...DEFAULT_CONFIG,
      account_id: firstAvailableAccount?.id ?? "",
    };
    const updated = [...value, newConfig];
    onChange(updated);
    saveConfigs(updated);
    setExpanded(true);
  };

  const duplicateConfig = (index: number) => {
    const source = value[index];
    const newConfig = { ...source, account_id: "" };
    const updated = [...value, newConfig];
    onChange(updated);
    saveConfigs(updated);
  };

  const removeConfig = (index: number) => {
    const updated = value.filter((_, i) => i !== index);
    onChange(updated);
    saveConfigs(updated);
  };

  const updateConfig = (index: number, partial: Partial<AutoTradeConfig>) => {
    const updated = value.map((c, i) => (i === index ? { ...c, ...partial } : c));
    onChange(updated);
    saveConfigs(updated);
  };

  return (
    <div className="rounded-xl border border-border/50 bg-card/50 p-4 space-y-3">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <svg className={cn("w-4 h-4 transition-transform", expanded && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-sm font-semibold">⚡ Auto-Trade Accounts</span>
        {value.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">{value.length} account{value.length > 1 ? "s" : ""}</span>
        )}
      </button>

      {expanded && (
        <div className="space-y-4 pt-2">
          {value.map((config, idx) => (
            <AutoTradeCard
              key={idx}
              config={config}
              index={idx}
              accounts={accounts}
              onChange={(partial) => updateConfig(idx, partial)}
              onDuplicate={() => duplicateConfig(idx)}
              onRemove={() => removeConfig(idx)}
            />
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addConfig} className="w-full border-dashed">
            + Add Trading Account
          </Button>
        </div>
      )}
    </div>
  );
}

interface CardProps {
  config: AutoTradeConfig;
  index: number;
  accounts: TradingAccount[];
  onChange: (partial: Partial<AutoTradeConfig>) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}

function AutoTradeCard({ config, index, accounts, onChange, onDuplicate, onRemove }: CardProps) {
  const selectedAccount = accounts.find((a) => a.id === config.account_id);

  return (
    <div className="rounded-lg border border-border/40 bg-background/50 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">Account #{index + 1}</span>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={onDuplicate} className="h-6 px-2 text-xs">
            Duplicate
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onRemove} className="h-6 px-2 text-xs text-red-400 hover:text-red-300">
            Remove
          </Button>
        </div>
      </div>

      {/* Account Selection */}
      <div>
        <Label className="text-xs">Account</Label>
        <Select value={config.account_id} onValueChange={(v) => v != null && onChange({ account_id: v })}>
          <SelectTrigger className="mt-1">
            <SelectValue placeholder="Select account..." />
          </SelectTrigger>
          <SelectContent>
            {accounts.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.label} ({a.account_type})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!config.account_id && (
          <p className="text-[10px] text-red-400 mt-1">Select an account — this config will be skipped otherwise</p>
        )}
        {selectedAccount?.account_type === "live" && (
          <p className="text-[10px] text-amber-400 mt-1">⚠ Live account — real funds at risk</p>
        )}
      </div>

      {/* Direction & Execution Mode */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Direction</Label>
          <div className="flex mt-1 rounded-lg overflow-hidden border border-border/50">
            <button
              type="button"
              className={cn("flex-1 py-1.5 text-xs font-medium transition-colors",
                config.direction === "straight" ? "bg-purple-600 text-white" : "bg-muted/30 hover:bg-muted/50")}
              onClick={() => onChange({ direction: "straight" })}
            >
              Straight
            </button>
            <button
              type="button"
              className={cn("flex-1 py-1.5 text-xs font-medium transition-colors",
                config.direction === "reverse" ? "bg-purple-600 text-white" : "bg-muted/30 hover:bg-muted/50")}
              onClick={() => onChange({ direction: "reverse" })}
            >
              Reverse
            </button>
          </div>
        </div>
        <div>
          <Label className="text-xs">Execution Mode</Label>
          <div className="flex mt-1 rounded-lg overflow-hidden border border-border/50">
            <button
              type="button"
              className={cn("flex-1 py-1.5 text-xs font-medium transition-colors",
                config.execution_mode === "immediate" ? "bg-purple-600 text-white" : "bg-muted/30 hover:bg-muted/50")}
              onClick={() => onChange({ execution_mode: "immediate" })}
            >
              Immediate
            </button>
            <button
              type="button"
              className={cn("flex-1 py-1.5 text-xs font-medium transition-colors",
                config.execution_mode === "batch" ? "bg-purple-600 text-white" : "bg-muted/30 hover:bg-muted/50")}
              onClick={() => onChange({ execution_mode: "batch" })}
            >
              Batch
            </button>
          </div>
        </div>
      </div>

      {/* Trade Settings */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">Leverage</Label>
          <Input
            type="number" min={1} max={125}
            value={config.leverage}
            onChange={(e) => onChange({ leverage: Math.min(125, Math.max(1, +e.target.value || 1)) })}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-xs">Capital %</Label>
          <Input
            type="number" min={0.1} max={100} step={0.1}
            value={config.capital_pct}
            onChange={(e) => onChange({ capital_pct: Math.min(100, Math.max(0.1, +e.target.value || 1)) })}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-xs">Max Trades</Label>
          <Input
            type="number" min={1} max={999}
            value={config.max_trades}
            onChange={(e) => onChange({ max_trades: Math.min(999, Math.max(1, +e.target.value || 1)) })}
            className="mt-1"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Take Profit %</Label>
          <Input
            type="number" min={0.1} max={1000} step={0.1}
            value={config.take_profit_pct}
            onChange={(e) => onChange({ take_profit_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
            className="mt-1"
          />
          <p className="text-[10px] text-muted-foreground mt-0.5">≈ {(config.take_profit_pct / config.leverage).toFixed(2)}% price move</p>
        </div>
        <div>
          <Label className="text-xs">Stop Loss %</Label>
          <Input
            type="number" min={0.1} max={1000} step={0.1}
            value={config.stop_loss_pct}
            onChange={(e) => onChange({ stop_loss_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
            className="mt-1"
          />
          <p className="text-[10px] text-muted-foreground mt-0.5">≈ {(config.stop_loss_pct / config.leverage).toFixed(2)}% price move</p>
        </div>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">Min Score</Label>
          <Input
            type="number" min={0} max={10} step={0.5}
            value={config.min_score}
            onChange={(e) => onChange({ min_score: Math.min(10, Math.max(0, +e.target.value || 0)) })}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-xs">Confidence</Label>
          <Select value={config.confidence_filter} onValueChange={(v) => v != null && onChange({ confidence_filter: v as AutoTradeConfig["confidence_filter"] })}>
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="moderate">Moderate+</SelectItem>
              <SelectItem value="low">Low+</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">Signal Sides</Label>
          <Select value={config.signal_sides} onValueChange={(v) => v != null && onChange({ signal_sides: v as AutoTradeConfig["signal_sides"] })}>
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="both">Both</SelectItem>
              <SelectItem value="buy">Buy Only</SelectItem>
              <SelectItem value="sell">Sell Only</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Risk Controls */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Max Drawdown %</Label>
          <Input
            type="number" min={1} max={100}
            value={config.max_drawdown_pct}
            onChange={(e) => onChange({ max_drawdown_pct: Math.min(100, Math.max(1, +e.target.value || 1)) })}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-xs">Target Goal</Label>
          <Select
            value={config.target_goal_type ?? "none"}
            onValueChange={(v) => onChange({ target_goal_type: v === "none" ? null : v as AutoTradeConfig["target_goal_type"] })}
          >
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">None</SelectItem>
              <SelectItem value="profit_pct">Profit %</SelectItem>
              <SelectItem value="profit_usdt">Profit USDT</SelectItem>
              <SelectItem value="trade_count">Trade Count</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {config.target_goal_type && (
        <div className="w-1/2">
          <Label className="text-xs">Goal Value</Label>
          <Input
            type="number" min={0.01} step={0.01}
            value={config.target_goal_value ?? ""}
            onChange={(e) => onChange({ target_goal_value: +e.target.value || null })}
            className="mt-1"
            placeholder={config.target_goal_type === "profit_pct" ? "e.g. 10" : config.target_goal_type === "profit_usdt" ? "e.g. 50" : "e.g. 5"}
          />
        </div>
      )}
    </div>
  );
}

export { loadConfigs, saveConfigs, DEFAULT_CONFIG };
