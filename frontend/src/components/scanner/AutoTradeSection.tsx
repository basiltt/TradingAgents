/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
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

const SEGMENT_CONTAINER_CLASS = "neu-surface-base neu-surface-inset flex min-h-12 items-center gap-1.5 rounded-[var(--neu-radius-md)] p-1.5";
const SEGMENT_BUTTON_CLASS = "neu-focus-ring flex-1 rounded-[calc(var(--neu-radius-md)-8px)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] transition-all";
const SECTION_CLASS = "rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_8%,var(--neu-surface-muted))] p-4";

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
    <div className="flex items-start gap-3 rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))] px-3.5 py-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "neu-focus-ring relative mt-0.5 flex h-7 w-12 shrink-0 items-center rounded-full border p-1 transition-colors",
          checked
            ? "border-[color:color-mix(in_oklch,var(--neu-accent)_24%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-surface-raised))]"
            : "border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_12%,var(--neu-surface-muted))]",
        )}
      >
        <span
          className={cn(
            "neu-surface-base neu-surface-raised block size-5 rounded-full transition-transform",
            checked && "translate-x-5",
          )}
        />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-[var(--neu-text-strong)]">{title}</p>
        <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">{description}</p>
      </div>
      {trailing ? <div className="pt-0.5">{trailing}</div> : null}
    </div>
  );
}

function Notice({
  tone,
  children,
}: {
  tone: "warning" | "success" | "danger";
  children: ReactNode;
}) {
  const toneClass = {
    warning: "text-[var(--neu-warning)] border-[color:color-mix(in_oklch,var(--neu-warning)_22%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-raised))]",
    success: "text-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_22%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-raised))]",
    danger: "text-[var(--neu-danger)] border-[color:color-mix(in_oklch,var(--neu-danger)_22%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-raised))]",
  }[tone];

  return (
    <div className={cn("rounded-[var(--neu-radius-md)] border px-3.5 py-3 text-[11px] leading-5", toneClass)}>
      {children}
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
    <section className="neu-surface-base neu-surface-raised overflow-hidden rounded-[var(--neu-radius-lg)]">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left"
      >
        <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
          <svg className={cn("size-4 transition-transform duration-200", expanded && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">Auto-trade execution</div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Account rules, safeguards, and execution plans</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge variant={value.length > 0 ? "default" : "secondary"} className="px-3 py-1 text-[10px] tracking-[0.16em]">
            {value.length} account{value.length === 1 ? "" : "s"}
          </Badge>
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-[color:var(--neu-stroke-soft)]/80 px-5 pb-5 pt-4">
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
    <article className="neu-surface-base neu-surface-inset space-y-5 rounded-[var(--neu-radius-lg)] p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">
            Account {index + 1}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--neu-text-strong)]">
            {selectedAccount ? selectedAccount.label : "Configure account routing"}
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {selectedAccount ? (
            <Badge variant={selectedAccount.account_type === "live" ? "destructive" : "secondary"} className="px-3 py-1 text-[10px] tracking-[0.16em]">
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

      <div className={SECTION_CLASS}>
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Account routing</div>
        <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Trading account</Label>
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
          <p className="mt-2 text-[11px] text-[var(--neu-danger)]">Required. This configuration is skipped until an account is assigned.</p>
        ) : null}
        {selectedAccount?.account_type === "live" ? (
          <p className="mt-2 text-[11px] text-[var(--neu-warning)]">Live account selected. Orders route to real funds.</p>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Direction logic</div>
          <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Direction</Label>
          <div className={cn(SEGMENT_CONTAINER_CLASS, "mt-2")}>
            {(["straight", "reverse"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={cn(
                  SEGMENT_BUTTON_CLASS,
                  config.direction === value
                    ? "neu-surface-base neu-surface-raised text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-pill)]"
                    : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]",
                )}
                onClick={() => onChange({ direction: value })}
              >
                {value === "straight" ? "Straight" : "Reverse"}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">
            {config.direction === "straight" ? "Trades follow the scanner signal direction." : "Trades invert the scanner signal direction."}
          </p>
        </div>

        <div className={SECTION_CLASS}>
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Execution cadence</div>
          <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Execution mode</Label>
          <div className={cn(SEGMENT_CONTAINER_CLASS, "mt-2")}>
            {(["immediate", "batch"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={cn(
                  SEGMENT_BUTTON_CLASS,
                  config.execution_mode === value
                    ? "neu-surface-base neu-surface-raised text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-pill)]"
                    : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]",
                )}
                onClick={() => onChange({ execution_mode: value })}
              >
                {value}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">
            {config.execution_mode === "immediate" ? "Orders route as each approved signal arrives." : "Orders wait until the scan finishes, then route together."}
          </p>
        </div>
      </div>

      <div className={SECTION_CLASS}>
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Trade parameters</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Leverage</Label>
            <div className="mt-2 flex items-center gap-2">
              <Input
                type="number"
                min={1}
                max={125}
                value={config.leverage}
                onChange={(e) => onChange({ leverage: Math.min(125, Math.max(1, +e.target.value || 1)) })}
              />
              <span className="text-sm text-[var(--neu-text-muted)]">x</span>
            </div>
          </div>
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Capital %</Label>
            <div className="mt-2 flex items-center gap-2">
              <Input
                type="number"
                min={0.1}
                max={100}
                step={0.1}
                value={config.capital_pct}
                onChange={(e) => onChange({ capital_pct: Math.min(100, Math.max(0.1, +e.target.value || 1)) })}
              />
              <span className="text-sm text-[var(--neu-text-muted)]">%</span>
            </div>
          </div>
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Max trades</Label>
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
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Take profit %</Label>
            <Input
              type="number"
              min={0.1}
              max={1000}
              step={0.1}
              value={config.take_profit_pct}
              onChange={(e) => onChange({ take_profit_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
              className="mt-2"
            />
            <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">≈ {tpPriceMove}% price move</p>
          </div>
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Stop loss %</Label>
            <Input
              type="number"
              min={0.1}
              max={1000}
              step={0.1}
              value={config.stop_loss_pct}
              onChange={(e) => onChange({ stop_loss_pct: Math.min(1000, Math.max(0.1, +e.target.value || 1)) })}
              className="mt-2"
            />
            <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">≈ {slPriceMove}% price move</p>
          </div>
        </div>

        <p className="mt-4 text-[11px] leading-5 text-[var(--neu-text-muted)]">
          Each trade uses {capitalPctNum}% of captured balance at {leverageNum}x leverage, capped at {config.max_trades} total positions per scan.
        </p>
      </div>

      <div className={SECTION_CLASS}>
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Signal filters</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Min score</Label>
            <Input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={config.min_score}
              onChange={(e) => onChange({ min_score: Math.min(10, Math.max(0, +e.target.value || 0)) })}
              className="mt-2"
            />
            <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">0 to 10 conviction threshold</p>
          </div>
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Min confidence</Label>
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
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Signal sides</Label>
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

        <p className="mt-4 text-[11px] leading-5 text-[var(--neu-text-muted)]">
          Higher thresholds reduce noise and route fewer, stronger trades.
        </p>
      </div>

      <div className={SECTION_CLASS}>
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Risk controls</div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Max drawdown %</Label>
            <Input
              type="number"
              min={1}
              max={100}
              value={config.max_drawdown_pct}
              onChange={(e) => onChange({ max_drawdown_pct: Math.min(100, Math.max(1, +e.target.value || 1)) })}
              className="mt-2"
            />
            <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">Close all positions if equity falls by this percentage.</p>
          </div>
          <div>
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Target goal</Label>
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
            <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">
              {config.target_goal_type === "profit_pct" ? "Close all once equity rises by the target percentage." : config.target_goal_type === "trade_count" ? "Stop after a fixed number of routed trades." : "No automatic target stop."}
            </p>
          </div>
        </div>

        {config.target_goal_type ? (
          <div className="mt-4 sm:w-1/2">
            <Label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
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
            <Notice tone="warning">
              A {config.max_drawdown_pct}% equity drop rule is created on this account when the scan starts. Review it later in Account → Close Rules.
            </Notice>
          ) : null}
          {config.target_goal_type === "profit_pct" && config.target_goal_value ? (
            <Notice tone="success">
              A {config.target_goal_value}% equity rise rule is created when the scan starts and becomes visible in Account → Close Rules.
            </Notice>
          ) : null}
        </div>
      </div>

      <div className={SECTION_CLASS}>
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Safety automation</div>
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
                  <span className="text-[11px] text-[var(--neu-text-muted)]">%</span>
                </div>
              ) : null
            }
          />
        </div>

        {config.close_on_profit_pct != null && config.close_on_profit_pct > 0 && !config.target_goal_value ? (
          <div className="mt-4">
            <Notice tone="danger">Close and re-trade requires a profit target goal above so the automation has a reference threshold.</Notice>
          </div>
        ) : null}
      </div>
    </article>
  );
}

export { loadConfigs, saveConfigs, DEFAULT_CONFIG };
