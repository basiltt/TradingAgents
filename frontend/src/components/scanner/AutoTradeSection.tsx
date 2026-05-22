/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, TriangleAlert } from "lucide-react";
import { accountsApi, type TradingAccount, type AutoTradeConfig } from "@/api/client";
import { Badge } from "@/components/ui/badge";
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
  fill_to_max_trades: false,
  close_on_profit_pct: null,
};

const SEGMENT_CONTAINER_CLASS = "grid grid-cols-2 gap-2 rounded-[calc(var(--radius)*1.2)] border border-border/55 bg-background/50 p-1.5 shadow-[var(--shadow-soft)] backdrop-blur-sm";
const SEGMENT_BUTTON_CLASS = "inline-flex min-h-11 items-center justify-center rounded-[calc(var(--radius)*1.05)] border border-transparent px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] transition-all duration-200";
const SECTION_CLASS = "surface-lift rounded-[calc(var(--radius)*1.35)] p-4 sm:p-4.5";

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

interface ToggleRowProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: string;
  description: string;
  trailing?: ReactNode;
}

function ToggleRow({ checked, onChange, title, description, trailing }: ToggleRowProps) {
  return (
    <div className="group flex items-start gap-3 rounded-[calc(var(--radius)*1.15)] border border-border/55 bg-card/55 px-3.5 py-3.5 shadow-[var(--shadow-soft)] transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/18 hover:bg-card/72">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 flex h-7 w-12 shrink-0 items-center rounded-full border p-1 shadow-[var(--shadow-soft)] transition-colors",
          checked
            ? "border-primary/30 bg-primary/20"
            : "border-border/60 bg-muted/55",
        )}
      >
        <span
          className={cn(
            "block size-5 rounded-full bg-background shadow-[var(--shadow-soft)] transition-transform",
            checked && "translate-x-5",
          )}
        />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{description}</p>
      </div>
      {trailing ? <div className="pt-0.5">{trailing}</div> : null}
    </div>
  );
}

function Notice({
  tone,
  icon,
  children,
}: {
  tone: "warning" | "success" | "danger";
  icon: ReactNode;
  children: ReactNode;
}) {
  const toneClass = {
    warning: "border-[color:color-mix(in_oklch,var(--warning)_45%,transparent)] bg-[color:color-mix(in_oklch,var(--warning)_12%,transparent)] text-[color:color-mix(in_oklch,var(--warning)_72%,var(--foreground))]",
    success: "border-[color:color-mix(in_oklch,var(--success)_44%,transparent)] bg-[color:color-mix(in_oklch,var(--success)_12%,transparent)] text-[color:color-mix(in_oklch,var(--success)_74%,var(--foreground))]",
    danger: "border-[color:color-mix(in_oklch,var(--destructive)_42%,transparent)] bg-[color:color-mix(in_oklch,var(--destructive)_12%,transparent)] text-[color:color-mix(in_oklch,var(--destructive)_74%,var(--foreground))]",
  }[tone];

  return (
    <div className={cn("flex items-start gap-3 rounded-[calc(var(--radius)*1.15)] border px-3.5 py-3 text-[11px] leading-5 shadow-[var(--shadow-soft)]", toneClass)}>
      <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-background/70">
        {icon}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function MetricChip({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "accent" | "success" | "danger" }) {
  const toneClass = {
    neutral: "border-border/55 bg-background/55 text-foreground",
    accent: "border-primary/25 bg-primary/10 text-primary",
    success: "border-[color:color-mix(in_oklch,var(--success)_42%,transparent)] bg-[color:color-mix(in_oklch,var(--success)_12%,transparent)] text-[var(--success)]",
    danger: "border-[color:color-mix(in_oklch,var(--destructive)_42%,transparent)] bg-[color:color-mix(in_oklch,var(--destructive)_12%,transparent)] text-destructive",
  }[tone];

  return (
    <div className={cn("rounded-[calc(var(--radius)*1.05)] border px-3 py-2 shadow-[var(--shadow-soft)]", toneClass)}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold tracking-[-0.03em]">{value}</div>
    </div>
  );
}

export function AutoTradeSection({ value, onChange }: AutoTradeSectionProps) {
  const [expanded, setExpanded] = useState(value.length > 0);

  useEffect(() => {
    if (value.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- keep the section expanded once configs exist
      setExpanded(true);
    }
  }, [value.length]);

  const { data: allAccounts = [], isLoading: accountsLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(),
    staleTime: 60_000,
  });
  const accounts = allAccounts.filter((a) => a.is_active);

  const addConfig = () => {
    const firstAvailableAccount = accounts.find(
      (a) => !value.some((c) => c.account_id === a.id),
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
    <section className="glass-card overflow-hidden rounded-[calc(var(--radius)*1.75)] border border-border/60 bg-card/72 shadow-[var(--shadow-card)]">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left"
      >
        <span className="inline-flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.1)] border border-primary/20 bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
          <svg className={cn("size-4 transition-transform duration-200", expanded && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-[-0.03em] text-foreground">Auto-trade execution</div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Account rules, safeguards, and execution plans</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge variant={value.length > 0 ? "default" : "secondary"} className="px-3 py-1 text-[10px] tracking-[0.16em]">
            {value.length} account{value.length === 1 ? "" : "s"}
          </Badge>
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-border/55 px-5 pb-5 pt-4">
          <div className="mb-4 grid gap-3 xl:grid-cols-[1.3fr_1fr]">
            <div className="surface-lift rounded-[calc(var(--radius)*1.4)] p-4">
              <div className="flex items-start gap-3">
                <span className="gradient-primary inline-flex size-10 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.05)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <Sparkles className="size-4.5" />
                </span>
                <div className="min-w-0 space-y-1">
                  <p className="section-eyebrow">Execution intelligence</p>
                  <h3 className="text-base font-semibold tracking-[-0.04em] text-foreground">Design routing rules like a prime broker control panel</h3>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Each account card defines direction, risk, entry filters, and automation safeguards while preserving the current trading engine.
                  </p>
                </div>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1 xl:auto-rows-fr">
              <MetricChip label="Active accounts" value={String(accounts.length)} tone="accent" />
              <MetricChip label="Configured lanes" value={String(value.length)} tone={value.length > 0 ? "success" : "neutral"} />
              <MetricChip label="Coverage" value={value.length === 0 ? "Idle" : `${Math.min(100, Math.round((value.length / Math.max(accounts.length, 1)) * 100))}%`} tone={value.length > accounts.length ? "danger" : "neutral"} />
            </div>
          </div>

          <div className="space-y-4">
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
          </div>

          <Button type="button" variant="outline" size="sm" onClick={addConfig} className="mt-4 w-full justify-center uppercase tracking-[0.14em]">
            <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add trading account
          </Button>
        </div>
      ) : null}
    </section>
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
    <article className="glass-card rounded-[calc(var(--radius)*1.55)] border border-border/60 bg-card/64 p-5 shadow-[var(--shadow-card)] backdrop-blur-sm">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Account {index + 1}
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground">
            {selectedAccount ? selectedAccount.label : "Configure account routing"}
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {selectedAccount ? (
            <Badge variant={selectedAccount.account_type === "live" ? "destructive" : "secondary"} className="px-3 py-1 text-[10px] tracking-[0.16em] uppercase">
              {selectedAccount.account_type}
            </Badge>
          ) : null}
          <Button type="button" variant="ghost" size="xs" onClick={onDuplicate} className="uppercase tracking-[0.14em]">
            Duplicate
          </Button>
          <Button type="button" variant="destructive" size="xs" onClick={onRemove} className="uppercase tracking-[0.14em]">
            Remove
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricChip label="Leverage" value={`${leverageNum}x`} tone="accent" />
        <MetricChip label="Capital" value={`${capitalPctNum}%`} />
        <MetricChip label="TP move" value={`${tpPriceMove}%`} tone="success" />
        <MetricChip label="SL move" value={`${slPriceMove}%`} tone="danger" />
      </div>

      <div className="mt-5 space-y-4">
        <div className={SECTION_CLASS}>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Account routing</div>
              <p className="mt-1 text-sm text-muted-foreground">Assign the execution lane used when a signal passes approval.</p>
            </div>
            <span className="inline-flex size-9 items-center justify-center rounded-[calc(var(--radius)*1.05)] border border-primary/20 bg-primary/10 text-primary">
              <ShieldCheck className="size-4.5" />
            </span>
          </div>
          <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Trading account</Label>
          <Select value={config.account_id} onValueChange={(v) => v != null && onChange({ account_id: v })}>
            <SelectTrigger className="mt-2 w-full">
              <SelectValue placeholder={accountsLoading ? "Loading accounts..." : "Select account"} />
            </SelectTrigger>
            <SelectContent>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.label} ({a.account_type})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!config.account_id && !accountsLoading ? (
            <p className="mt-2 text-[11px] text-destructive">Required. This configuration is skipped until an account is assigned.</p>
          ) : null}
          {selectedAccount?.account_type === "live" ? (
            <p className="mt-2 text-[11px] text-[color:color-mix(in_oklch,var(--warning)_76%,var(--foreground))]">Live account selected. Orders route to real funds.</p>
          ) : null}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className={SECTION_CLASS}>
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Direction logic</div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Direction</Label>
            <div className={cn(SEGMENT_CONTAINER_CLASS, "mt-2")}>
              {(["straight", "reverse"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={cn(
                    SEGMENT_BUTTON_CLASS,
                    config.direction === value
                      ? "border-primary/20 bg-primary text-primary-foreground shadow-[var(--shadow-accent)]"
                      : "text-muted-foreground hover:border-border/60 hover:bg-background/80 hover:text-foreground",
                  )}
                  onClick={() => onChange({ direction: value })}
                >
                  {value === "straight" ? "Straight" : "Reverse"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
              {config.direction === "straight" ? "Trades follow the scanner signal direction." : "Trades invert the scanner signal direction."}
            </p>
          </div>

          <div className={SECTION_CLASS}>
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Execution cadence</div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Execution mode</Label>
            <div className={cn(SEGMENT_CONTAINER_CLASS, "mt-2")}>
              {(["immediate", "batch"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={cn(
                    SEGMENT_BUTTON_CLASS,
                    config.execution_mode === value
                      ? "border-primary/20 bg-primary text-primary-foreground shadow-[var(--shadow-accent)]"
                      : "text-muted-foreground hover:border-border/60 hover:bg-background/80 hover:text-foreground",
                  )}
                  onClick={() => onChange({ execution_mode: value })}
                >
                  {value}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
              {config.execution_mode === "immediate" ? "Orders route as each approved signal arrives." : "Orders wait until the scan finishes, then route together."}
            </p>
          </div>
        </div>

        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Trade parameters</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Leverage</Label>
              <div className="mt-2 flex items-center gap-2">
                <Input
                  type="number"
                  min={1}
                  max={125}
                  value={config.leverage}
                  onChange={(e) => onChange({ leverage: Math.min(125, Math.max(1, +e.target.value || 1)) })}
                />
                <span className="text-sm text-muted-foreground">x</span>
              </div>
            </div>
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Capital %</Label>
              <div className="mt-2 flex items-center gap-2">
                <Input
                  type="number"
                  min={0.1}
                  max={100}
                  step={0.1}
                  value={config.capital_pct}
                  onChange={(e) => onChange({ capital_pct: Math.min(100, Math.max(0.1, +e.target.value || 1)) })}
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Max trades</Label>
              <Input
                type="number"
                min={1}
                max={999}
                value={config.max_trades}
                onChange={(e) => onChange({ max_trades: Math.min(999, Math.max(1, +e.target.value || 1)) })}
                className="mt-2"
              />
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Take profit %</Label>
              <Input
                type="number"
                min={0.1}
                max={1000}
                step={0.1}
                value={config.take_profit_pct}
                onChange={(e) => onChange({ take_profit_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
                className="mt-2"
              />
              <p className="mt-2 text-[11px] text-muted-foreground">≈ {tpPriceMove}% price move</p>
            </div>
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Stop loss %</Label>
              <Input
                type="number"
                min={0.1}
                max={1000}
                step={0.1}
                value={config.stop_loss_pct}
                onChange={(e) => onChange({ stop_loss_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
                className="mt-2"
              />
              <p className="mt-2 text-[11px] text-muted-foreground">≈ {slPriceMove}% price move</p>
            </div>
          </div>

          <p className="mt-4 text-[11px] leading-5 text-muted-foreground">
            Each trade uses {capitalPctNum}% of captured balance at {leverageNum}x leverage, capped at {config.max_trades} total positions per scan.
          </p>
        </div>

        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Signal filters</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Min score</Label>
              <Input
                type="number"
                min={0}
                max={10}
                step={0.5}
                value={config.min_score}
                onChange={(e) => onChange({ min_score: Math.min(10, Math.max(0, +e.target.value || 0)) })}
                className="mt-2"
              />
              <p className="mt-2 text-[11px] text-muted-foreground">0 to 10 conviction threshold</p>
            </div>
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Min confidence</Label>
              <Select value={config.confidence_filter} onValueChange={(v) => v != null && onChange({ confidence_filter: v as AutoTradeConfig["confidence_filter"] })}>
                <SelectTrigger className="mt-2 w-full">
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
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Signal sides</Label>
              <Select value={config.signal_sides} onValueChange={(v) => v != null && onChange({ signal_sides: v as AutoTradeConfig["signal_sides"] })}>
                <SelectTrigger className="mt-2 w-full">
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

          <p className="mt-4 text-[11px] leading-5 text-muted-foreground">
            Higher thresholds reduce noise and route fewer, stronger trades.
          </p>
        </div>

        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Risk controls</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Max drawdown %</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={config.max_drawdown_pct}
                onChange={(e) => onChange({ max_drawdown_pct: Math.min(100, Math.max(1, +e.target.value || 1)) })}
                className="mt-2"
              />
              <p className="mt-2 text-[11px] text-muted-foreground">Close all positions if equity falls by this percentage.</p>
            </div>
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Target goal</Label>
              <Select
                value={config.target_goal_type ?? "none"}
                onValueChange={(v) => v != null && onChange({ target_goal_type: v === "none" ? null : v as AutoTradeConfig["target_goal_type"], ...(v === "none" ? { target_goal_value: null } : {}) })}
              >
                <SelectTrigger className="mt-2 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="trade_count">Trade count</SelectItem>
                  <SelectItem value="profit_pct">Profit %</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {config.target_goal_type === "profit_pct" ? "Close all once equity rises by the target percentage." : config.target_goal_type === "trade_count" ? "Stop after a fixed number of routed trades." : "No automatic target stop."}
              </p>
            </div>
          </div>

          {config.target_goal_type ? (
            <div className="mt-4 sm:w-1/2">
              <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {config.target_goal_type === "profit_pct" ? "Target profit %" : "Target trade count"}
              </Label>
              <Input
                type="number"
                min={0.01}
                step={0.01}
                value={config.target_goal_value ?? ""}
                onChange={(e) => onChange({ target_goal_value: +e.target.value || null })}
                className="mt-2"
                placeholder={config.target_goal_type === "profit_pct" ? "e.g. 15" : "e.g. 5"}
              />
            </div>
          ) : null}

          <div className="mt-4 space-y-3">
            {config.max_drawdown_pct < 100 ? (
              <Notice tone="warning" icon={<TriangleAlert className="size-4 text-current" />}>
                A {config.max_drawdown_pct}% equity drop rule is created on this account when the scan starts. Review it later in Account → Close Rules.
              </Notice>
            ) : null}
            {config.target_goal_type === "profit_pct" && config.target_goal_value ? (
              <Notice tone="success" icon={<ShieldCheck className="size-4 text-current" />}>
                A {config.target_goal_value}% equity rise rule is created when the scan starts and becomes visible in Account → Close Rules.
              </Notice>
            ) : null}
          </div>
        </div>

        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Safety automation</div>
          <div className="space-y-3">
            <ToggleRow
              checked={config.skip_if_positions_open ?? false}
              onChange={(checked) => onChange({ skip_if_positions_open: checked })}
              title="Skip if positions are already open"
              description="Prevents stacking new positions on accounts that are already holding active trades."
            />
            <ToggleRow
              checked={config.fill_to_max_trades ?? false}
              onChange={(checked) => onChange({ fill_to_max_trades: checked })}
              title="Fill to max trades"
              description="If not enough signals pass the filters, fill the remaining slots with the next-best available setups."
            />
            <ToggleRow
              checked={config.close_on_profit_pct != null && config.close_on_profit_pct > 0}
              onChange={(checked) => onChange({ close_on_profit_pct: checked ? 50 : null })}
              title="Close and re-trade on profit"
              description="Closes existing positions once part of the target goal is reached, then allows the next wave of trades."
              trailing={
                config.close_on_profit_pct != null && config.close_on_profit_pct > 0 ? (
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min={1}
                      max={100}
                      step={5}
                      value={config.close_on_profit_pct}
                      onChange={(e) => onChange({ close_on_profit_pct: parseFloat(e.target.value) || 50 })}
                      className="h-10 w-20 text-center"
                    />
                    <span className="text-[11px] text-muted-foreground">%</span>
                  </div>
                ) : null
              }
            />
          </div>

          {config.close_on_profit_pct != null && config.close_on_profit_pct > 0 && !config.target_goal_value ? (
            <div className="mt-4">
              <Notice tone="danger" icon={<TriangleAlert className="size-4 text-current" />}>
                Close and re-trade requires a profit target goal above so the automation has a reference threshold.
              </Notice>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export { loadConfigs, saveConfigs, DEFAULT_CONFIG };
