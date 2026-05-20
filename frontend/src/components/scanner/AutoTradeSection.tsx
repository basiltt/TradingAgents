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
  skip_if_positions_open: false,
};

function loadConfigs(): AutoTradeConfig[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const configs: AutoTradeConfig[] = JSON.parse(raw);
    return configs.map((c) => ({
      ...c,
      target_goal_type: c.target_goal_type === "trade_count" || c.target_goal_type === "profit_pct" ? c.target_goal_type : null,
      target_goal_value: (c.target_goal_type === "trade_count" || c.target_goal_type === "profit_pct") ? c.target_goal_value : null,
    }));
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

  const { data: allAccounts = [], isLoading: accountsLoading } = useQuery({
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
    <div className="rounded-2xl border border-border/40 bg-card">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-3 w-full text-left px-5 py-4"
      >
        <svg className={cn("w-4 h-4 text-muted-foreground transition-transform", expanded && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-sm font-semibold">Auto-Trade Execution</span>
        {value.length > 0 && (
          <span className="ml-auto text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full">
            {value.length} account{value.length > 1 ? "s" : ""}
          </span>
        )}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          {value.map((config, idx) => (
            <AutoTradeCard
              key={idx}
              config={config}
              index={idx}
              accounts={accounts}
              accountsLoading={accountsLoading}
              onChange={(partial) => updateConfig(idx, partial)}
              onDuplicate={() => duplicateConfig(idx)}
              onRemove={() => removeConfig(idx)}
            />
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addConfig} className="w-full border-dashed border-border/50 text-muted-foreground hover:text-foreground">
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
  accountsLoading: boolean;
  onChange: (partial: Partial<AutoTradeConfig>) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}

function AutoTradeCard({ config, index, accounts, accountsLoading, onChange, onDuplicate, onRemove }: CardProps) {
  const selectedAccount = accounts.find((a) => a.id === config.account_id);
  const leverageNum = config.leverage || 1;
  const capitalPctNum = config.capital_pct || 0;
  const tpPriceMove = (config.take_profit_pct / leverageNum).toFixed(2);
  const slPriceMove = (config.stop_loss_pct / leverageNum).toFixed(2);

  return (
    <div className="rounded-xl border border-border/30 bg-muted/20 p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Account #{index + 1}</span>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={onDuplicate} className="h-7 px-2.5 text-xs text-muted-foreground hover:text-foreground">
            Duplicate
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onRemove} className="h-7 px-2.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10">
            Remove
          </Button>
        </div>
      </div>

      {/* Account Selection */}
      <div>
        <Label className="text-xs text-muted-foreground">Trading Account</Label>
        <Select value={config.account_id} onValueChange={(v) => v != null && onChange({ account_id: v })}>
          <SelectTrigger className="mt-1.5">
            <SelectValue placeholder={accountsLoading ? "Loading accounts..." : "Select account..."}>
              {selectedAccount ? `${selectedAccount.label} (${selectedAccount.account_type})` : accountsLoading ? "Loading accounts..." : undefined}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {accounts.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.label} ({a.account_type})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!config.account_id && !accountsLoading && (
          <p className="text-[10px] text-red-400 mt-1">Required — this config will be skipped without an account</p>
        )}
        {selectedAccount?.account_type === "live" && (
          <p className="text-[10px] text-amber-400 mt-1">Live account — real funds at risk</p>
        )}
      </div>

      {/* Direction & Execution Mode */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label className="text-xs text-muted-foreground">Direction</Label>
          <div className="flex mt-1.5 rounded-lg overflow-hidden border border-border/40">
            <button
              type="button"
              className={cn("flex-1 py-2 text-xs font-medium transition-colors",
                config.direction === "straight" ? "bg-purple-600 text-white" : "bg-muted/30 text-muted-foreground hover:bg-muted/50")}
              onClick={() => onChange({ direction: "straight" })}
            >
              Straight
            </button>
            <button
              type="button"
              className={cn("flex-1 py-2 text-xs font-medium transition-colors",
                config.direction === "reverse" ? "bg-purple-600 text-white" : "bg-muted/30 text-muted-foreground hover:bg-muted/50")}
              onClick={() => onChange({ direction: "reverse" })}
            >
              Reverse
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground mt-1">
            {config.direction === "straight" ? "Trade follows signal direction" : "Trade opposite to signal direction"}
          </p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Execution Mode</Label>
          <div className="flex mt-1.5 rounded-lg overflow-hidden border border-border/40">
            <button
              type="button"
              className={cn("flex-1 py-2 text-xs font-medium transition-colors",
                config.execution_mode === "immediate" ? "bg-purple-600 text-white" : "bg-muted/30 text-muted-foreground hover:bg-muted/50")}
              onClick={() => onChange({ execution_mode: "immediate" })}
            >
              Immediate
            </button>
            <button
              type="button"
              className={cn("flex-1 py-2 text-xs font-medium transition-colors",
                config.execution_mode === "batch" ? "bg-purple-600 text-white" : "bg-muted/30 text-muted-foreground hover:bg-muted/50")}
              onClick={() => onChange({ execution_mode: "batch" })}
            >
              Batch
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground mt-1">
            {config.execution_mode === "immediate" ? "Execute as each signal arrives" : "Execute all after scan completes"}
          </p>
        </div>
      </div>

      {/* Trade Parameters */}
      <div className="space-y-3">
        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Trade Parameters</p>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground">Leverage</Label>
            <div className="flex items-center gap-1 mt-1.5">
              <Input
                type="number" min={1} max={125}
                value={config.leverage}
                onChange={(e) => onChange({ leverage: Math.min(125, Math.max(1, +e.target.value || 1)) })}
              />
              <span className="text-xs text-muted-foreground">x</span>
            </div>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Capital %</Label>
            <div className="flex items-center gap-1 mt-1.5">
              <Input
                type="number" min={0.1} max={100} step={0.1}
                value={config.capital_pct}
                onChange={(e) => onChange({ capital_pct: Math.min(100, Math.max(0.1, +e.target.value || 1)) })}
              />
              <span className="text-xs text-muted-foreground">%</span>
            </div>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Max Trades</Label>
            <Input
              type="number" min={1} max={999}
              value={config.max_trades}
              onChange={(e) => onChange({ max_trades: Math.min(999, Math.max(1, +e.target.value || 1)) })}
              className="mt-1.5"
            />
          </div>
        </div>
        <p className="text-[10px] text-muted-foreground">
          Each trade uses {capitalPctNum}% of captured balance at {leverageNum}x leverage. Max {config.max_trades} trades per scan.
        </p>
      </div>

      {/* TP / SL */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs text-muted-foreground">Take Profit %</Label>
          <Input
            type="number" min={0.1} max={1000} step={0.1}
            value={config.take_profit_pct}
            onChange={(e) => onChange({ take_profit_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
            className="mt-1.5"
          />
          <p className="text-[10px] text-muted-foreground mt-1">{"≈"} {tpPriceMove}% price move</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Stop Loss %</Label>
          <Input
            type="number" min={0.1} max={1000} step={0.1}
            value={config.stop_loss_pct}
            onChange={(e) => onChange({ stop_loss_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
            className="mt-1.5"
          />
          <p className="text-[10px] text-muted-foreground mt-1">{"≈"} {slPriceMove}% price move</p>
        </div>
      </div>

      {/* Signal Filters */}
      <div className="space-y-3">
        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Signal Filters</p>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground">Min Score</Label>
            <Input
              type="number" min={0} max={10} step={0.5}
              value={config.min_score}
              onChange={(e) => onChange({ min_score: Math.min(10, Math.max(0, +e.target.value || 0)) })}
              className="mt-1.5"
            />
            <p className="text-[10px] text-muted-foreground mt-1">0-10 scale</p>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Min Confidence</Label>
            <Select value={config.confidence_filter} onValueChange={(v) => v != null && onChange({ confidence_filter: v as AutoTradeConfig["confidence_filter"] })}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any</SelectItem>
                <SelectItem value="low">Low+</SelectItem>
                <SelectItem value="moderate">Moderate+</SelectItem>
                <SelectItem value="high">High only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Signal Sides</Label>
            <Select value={config.signal_sides} onValueChange={(v) => v != null && onChange({ signal_sides: v as AutoTradeConfig["signal_sides"] })}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="both">Both</SelectItem>
                <SelectItem value="buy">Buy only</SelectItem>
                <SelectItem value="sell">Sell only</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-[10px] text-muted-foreground">
          Signals below these thresholds are skipped. Higher filters = fewer but stronger trades.
        </p>
      </div>

      {/* Risk Management */}
      <div className="space-y-3">
        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Risk Management</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground">Max Drawdown %</Label>
            <Input
              type="number" min={1} max={100}
              value={config.max_drawdown_pct}
              onChange={(e) => onChange({ max_drawdown_pct: Math.min(100, Math.max(1, +e.target.value || 1)) })}
              className="mt-1.5"
            />
            <p className="text-[10px] text-muted-foreground mt-1">Close all positions if equity drops by this %</p>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Target Goal</Label>
            <Select
              value={config.target_goal_type ?? "none"}
              onValueChange={(v) => v != null && onChange({ target_goal_type: v === "none" ? null : v as AutoTradeConfig["target_goal_type"] })}
            >
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="trade_count">Trade Count</SelectItem>
                <SelectItem value="profit_pct">Profit %</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[10px] text-muted-foreground mt-1">
              {config.target_goal_type === "profit_pct" ? "Close all when equity rises by target %" : config.target_goal_type === "trade_count" ? "Stop after N trades are placed" : "No automatic stop target"}
            </p>
          </div>
        </div>

        {config.target_goal_type && (
          <div className="w-1/2">
            <Label className="text-xs text-muted-foreground">
              {config.target_goal_type === "profit_pct" ? "Target Profit %" : "Target Trade Count"}
            </Label>
            <Input
              type="number" min={0.01} step={0.01}
              value={config.target_goal_value ?? ""}
              onChange={(e) => onChange({ target_goal_value: +e.target.value || null })}
              className="mt-1.5"
              placeholder={config.target_goal_type === "profit_pct" ? "e.g. 15" : "e.g. 5"}
            />
          </div>
        )}

        {config.max_drawdown_pct < 100 && (
          <div className="rounded-lg bg-amber-500/5 border border-amber-500/10 px-3 py-2">
            <p className="text-[10px] text-amber-400">
              A {config.max_drawdown_pct}% equity drop rule will be created on the account when the scan starts. Visible in Account → Close Rules.
            </p>
          </div>
        )}
        {config.target_goal_type === "profit_pct" && config.target_goal_value && (
          <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 px-3 py-2">
            <p className="text-[10px] text-emerald-400">
              A {config.target_goal_value}% equity rise rule will be created on the account when the scan starts. Visible in Account → Close Rules.
            </p>
          </div>
        )}
      </div>

      {/* Safety Toggles */}
      <div className="space-y-3 pt-1 border-t border-border/20">
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              checked={config.skip_if_positions_open ?? false}
              onChange={(e) => onChange({ skip_if_positions_open: e.target.checked })}
              className="sr-only peer"
            />
            <div className="w-9 h-5 rounded-full bg-muted/50 border border-border/40 peer-checked:bg-purple-600 peer-checked:border-purple-600 transition-colors" />
            <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
          </div>
          <div>
            <span className="text-xs font-medium group-hover:text-foreground transition-colors">Skip if positions open</span>
            <p className="text-[10px] text-muted-foreground">Don't open new trades if this account already has active positions</p>
          </div>
        </label>
      </div>
    </div>
  );
}

export { loadConfigs, saveConfigs, DEFAULT_CONFIG };
