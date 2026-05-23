/* eslint-disable react-hooks/set-state-in-effect */
import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  Clock,
  DollarSign,
  Loader2,
  Percent,
  Plus,
  ShieldCheck,
  Timer,
  Trash2,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/api/client";
import { useAppSelector } from "@/store";
import { cn } from "@/lib/utils";
import type { CloseRule, TriggerType, UpdateCloseRuleData } from "@/api/client";
import { NeuThemeScope } from "@/design-system/neumorphism/foundation";
import { NeuButton } from "@/design-system/neumorphism/inputs";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
  onSave: () => void;
}

const TRIGGER_CONFIG: Record<TriggerType, { label: string; description: string; icon: typeof TrendingDown; tone: string; chip: string }> = {
  BALANCE_BELOW: {
    label: "Balance Below",
    description: "Close when account equity drops below a fixed cash threshold.",
    icon: TrendingDown,
    tone: "text-[var(--neu-danger)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-danger)_12%,var(--neu-surface-raised))] text-[var(--neu-danger)] shadow-[var(--neu-shadow-pill)]",
  },
  BALANCE_ABOVE: {
    label: "Balance Above",
    description: "Bank profits by closing exposure after balance exceeds a target.",
    icon: TrendingUp,
    tone: "text-[var(--neu-success)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-success)_12%,var(--neu-surface-raised))] text-[var(--neu-success)] shadow-[var(--neu-shadow-pill)]",
  },
  EQUITY_DROP_PCT: {
    label: "Equity Drop %",
    description: "Trip the safeguard once equity falls from the starting reference.",
    icon: Percent,
    tone: "text-[var(--neu-danger)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-danger)_12%,var(--neu-surface-raised))] text-[var(--neu-danger)] shadow-[var(--neu-shadow-pill)]",
  },
  EQUITY_RISE_PCT: {
    label: "Equity Rise %",
    description: "Exit after the account reaches the configured growth target.",
    icon: Percent,
    tone: "text-[var(--neu-success)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-success)_12%,var(--neu-surface-raised))] text-[var(--neu-success)] shadow-[var(--neu-shadow-pill)]",
  },
  PNL_BELOW: {
    label: "PnL Loss",
    description: "React to unrealized drawdown before losses deepen further.",
    icon: DollarSign,
    tone: "text-[var(--neu-danger)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-danger)_12%,var(--neu-surface-raised))] text-[var(--neu-danger)] shadow-[var(--neu-shadow-pill)]",
  },
  PNL_ABOVE: {
    label: "PnL Profit",
    description: "Take open profit automatically when unrealized gains reach target.",
    icon: DollarSign,
    tone: "text-[var(--neu-success)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-success)_12%,var(--neu-surface-raised))] text-[var(--neu-success)] shadow-[var(--neu-shadow-pill)]",
  },
  BREAKEVEN_TIMEOUT: {
    label: "Breakeven Timeout",
    description: "Close positions if P&L hasn't moved past breakeven within the time window.",
    icon: Timer,
    tone: "text-[var(--neu-warning)]",
    chip: "border-transparent bg-[color-mix(in_oklch,var(--neu-warning)_12%,var(--neu-surface-raised))] text-[var(--neu-warning)] shadow-[var(--neu-shadow-pill)]",
  },
  MAX_DURATION: {
    label: "Max Duration",
    description: "Force-close all positions after a maximum hold time regardless of P&L.",
    icon: Clock,
    tone: "text-[var(--neu-text-muted)]",
    chip: "border-transparent bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] shadow-[var(--neu-shadow-pill)]",
  },
};

const TRIGGER_OPTIONS: TriggerType[] = [
  "BALANCE_BELOW",
  "BALANCE_ABOVE",
  "EQUITY_DROP_PCT",
  "EQUITY_RISE_PCT",
  "PNL_BELOW",
  "PNL_ABOVE",
  "BREAKEVEN_TIMEOUT",
  "MAX_DURATION",
];

const PCT_TYPES = new Set<TriggerType>(["EQUITY_DROP_PCT", "EQUITY_RISE_PCT"]);
const TIME_TYPES = new Set<TriggerType>(["BREAKEVEN_TIMEOUT", "MAX_DURATION"]);

export function ConditionalRulesDialog({ open, onOpenChange, accountId, accountLabel, onSave }: Props) {
  const [rules, setRules] = useState<CloseRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const actionRef = useRef(false);
  const closeExecSeq = useAppSelector((s) => s.accounts.closeExecutionSeq);

  useEffect(() => {
    if (!open) {
      return;
    }
    const controller = new AbortController();
    accountsApi.getCloseRules(accountId, controller.signal)
      .then(setRules)
      .catch(() => { if (!controller.signal.aborted) toast.error("Failed to load rules"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, accountId, closeExecSeq]);

  const handleDialogClose = () => {
    setRules([]);
    setLoading(true);
    onOpenChange(false);
  };

  if (!open) return null;

  const handleAddRule = async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    setSaving("new");
    try {
      const rule = await accountsApi.createCloseRule(accountId, {
        trigger_type: "BALANCE_BELOW",
        threshold_value: "100",
      });
      setRules((prev) => [rule, ...prev]);
      toast.success("Rule created");
      onSave();
    } catch (err: unknown) {
      const e = err as { status?: number; detail?: string };
      if (e?.status === 409) {
        toast.error("Maximum rules reached for this account");
      } else {
        toast.error(e?.detail || "Failed to create rule");
      }
    } finally {
      actionRef.current = false;
      setSaving(null);
    }
  };

  const handleUpdateRule = async (ruleId: string, updates: UpdateCloseRuleData) => {
    try {
      const updated = await accountsApi.updateCloseRule(accountId, ruleId, updates);
      setRules((prev) => prev.map((r) => (r.id === ruleId ? updated : r)));
    } catch (err: unknown) {
      toast.error((err as { detail?: string })?.detail || "Failed to update rule");
    }
  };

  const handleToggleStatus = async (rule: CloseRule) => {
    const newStatus = rule.status === "active" ? "paused" : "active";
    try {
      const updated = await accountsApi.updateCloseRule(accountId, rule.id, { status: newStatus });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      onSave();
    } catch (err: unknown) {
      toast.error((err as { detail?: string })?.detail || "Failed to update rule");
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (actionRef.current) return;
    actionRef.current = true;
    setSaving(ruleId);
    try {
      await accountsApi.deleteCloseRule(accountId, ruleId);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
      toast.success("Rule deleted");
      onSave();
    } catch (err: unknown) {
      toast.error((err as { detail?: string })?.detail || "Failed to delete rule");
    } finally {
      actionRef.current = false;
      setSaving(null);
    }
  };

  const activeCount = rules.filter((r) => r.status === "active" || r.status === "paused").length;
  const armedCount = rules.filter((r) => r.status === "active").length;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6 sm:p-8"
      onClick={() => !saving && handleDialogClose()}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,oklch(0.6_0.12_220_/_0.18),transparent_34%),rgba(3,8,20,0.78)] backdrop-blur-md" />
      <div
        className="relative flex max-h-[calc(100vh-3rem)] sm:max-h-[calc(100vh-4rem)] w-full max-w-5xl flex-col overflow-hidden rounded-[var(--neu-radius-lg)] border-0 shadow-[var(--neu-shadow-float)]"
        onClick={(e) => e.stopPropagation()}
      >
        <NeuThemeScope className="flex flex-col flex-1 w-full p-0 overflow-hidden rounded-[var(--neu-radius-lg)] bg-[var(--neu-surface-base)]">
          {/* Header */}
          <div className="shrink-0 border-b border-[color:var(--neu-stroke-strong)]/20 px-4 py-4 sm:px-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-[var(--neu-radius-md)] bg-[var(--neu-accent)] text-[var(--neu-accent-ink)] shadow-[var(--neu-shadow-pill)]">
                  <ShieldCheck className="size-5" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold tracking-[-0.02em] text-[var(--neu-text-strong)] sm:text-lg">
                    Conditional close rules
                  </h2>
                  <p className="mt-1 text-xs leading-5 text-[var(--neu-text-muted)] sm:text-sm">
                    Protect <span className="font-semibold text-[var(--neu-text-strong)]">{accountLabel}</span> with threshold-based exits that react to equity, balance, and unrealized PnL.
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 sm:shrink-0">
                {[
                  { label: "Configured", value: String(rules.length), tone: "accent" },
                  { label: "Armed", value: String(armedCount), tone: armedCount ? "success" : "neutral" },
                  { label: "Limit", value: `${activeCount}/10`, tone: activeCount >= 10 ? "warning" : "neutral" },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="neu-input-base relative overflow-hidden rounded-[var(--neu-radius-sm)] px-3 py-2 text-left"
                  >
                    <span className={cn(
                      "absolute left-0 top-0 bottom-0 w-0.5",
                      item.tone === "accent" && "bg-[var(--neu-accent)]",
                      item.tone === "success" && "bg-[var(--neu-success)]",
                      item.tone === "warning" && "bg-[var(--neu-warning)]",
                      item.tone === "neutral" && "bg-[var(--neu-text-muted)] opacity-35"
                    )} />
                    <div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">{item.label}</div>
                    <div className="mt-0.5 text-base font-bold text-[var(--neu-text-strong)]">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--neu-text-muted)]">
              <span className="inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] px-2.5 py-0.5 text-[var(--neu-success)] bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-raised))] border border-[color:color-mix(in_oklch,var(--neu-success)_18%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]">
                <span className="relative flex size-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
                  <span className="relative inline-flex size-2 rounded-full bg-current" />
                </span>
                Heartbeat 30s
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] px-2.5 py-0.5 text-[var(--neu-text-muted)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-pill)]">
                <Activity className="size-3" />
                Live synced
              </span>
            </div>
          </div>

          {/* Content: scrollable */}
          <div className="flex-1 overflow-y-auto neu-scrollbar px-4 py-4 sm:px-6">
            {/* Rules list */}
            {loading ? (
              <div className="flex min-h-[8rem] items-center justify-center">
                <div className="flex items-center gap-3 text-sm text-[var(--neu-text-muted)]">
                  <Loader2 className="size-4 animate-spin text-[var(--neu-accent)]" />
                  Loading close rules...
                </div>
              </div>
            ) : rules.length === 0 ? (
              <div className="flex min-h-[8rem] flex-col items-center justify-center rounded-[var(--neu-radius-md)] border-2 border-dashed border-[color:var(--neu-stroke-strong)]/40 px-4 py-8 text-center">
                <button
                  type="button"
                  onClick={handleAddRule}
                  disabled={saving === "new" || activeCount >= 10}
                  className="flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-raised)] text-[var(--neu-text-muted)] shadow-[var(--neu-shadow-pill)] hover:shadow-[var(--neu-shadow-raised-soft)] hover:text-[var(--neu-accent)] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving === "new" ? <Loader2 className="size-5 animate-spin" /> : <Plus className="size-5" />}
                </button>
                <h3 className="mt-3 text-sm font-semibold text-[var(--neu-text-strong)]">No automated exits configured</h3>
                <p className="mt-1 max-w-sm text-xs leading-5 text-[var(--neu-text-muted)]">
                  Create rules to automatically flatten the account when drawdown, profit, or equity thresholds are reached.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {rules.map((rule) => (
                  <RuleRow
                    key={rule.id}
                    rule={rule}
                    saving={saving === rule.id}
                    onUpdate={handleUpdateRule}
                    onToggle={() => handleToggleStatus(rule)}
                    onDelete={() => handleDeleteRule(rule.id)}
                  />
                ))}
              </div>
            )}

            {/* Info section - horizontal on desktop, stacked on mobile */}
            <div className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_1.8fr]">
              <div className="rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] p-3 shadow-[var(--neu-shadow-pill)]">
                <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Rule strategy</p>
                <h3 className="mt-1 text-xs font-semibold text-[var(--neu-text-strong)]">Suggested setup</h3>
                <ul className="mt-2 space-y-1 text-xs leading-5 text-[var(--neu-text-muted)]">
                  <li>* Pair one hard downside rule with one upside take-profit rule.</li>
                  <li>* Use percentage triggers for portable rules across account sizes.</li>
                  <li>* Keep armed rules below the limit for temporary overrides.</li>
                </ul>
              </div>

              <div className="rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] p-3 shadow-[var(--neu-shadow-pill)]">
                <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Trigger types</p>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                  {TRIGGER_OPTIONS.map((type) => {
                    const config = TRIGGER_CONFIG[type];
                    const Icon = config.icon;
                    return (
                      <div key={type} className="flex items-start gap-1.5">
                        <Icon className={cn("mt-0.5 size-3 shrink-0", config.tone)} />
                        <div>
                          <p className="text-[11px] font-semibold text-[var(--neu-text-strong)]">{config.label}</p>
                          <p className="text-[10px] leading-3.5 text-[var(--neu-text-muted)]">{config.description}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="shrink-0 flex items-center justify-between gap-3 border-t border-[color:var(--neu-stroke-strong)]/20 px-4 py-3 sm:px-6">
            <p className="hidden sm:block text-xs text-[var(--neu-text-muted)]">
              Rules sync instantly after edits.
            </p>
            <div className="flex gap-2 ml-auto">
              <NeuButton type="button" variant="secondary" size="sm" onClick={() => handleDialogClose()}>
                <X className="size-3.5" />
                Close
              </NeuButton>
              <NeuButton
                type="button"
                variant="primary"
                size="sm"
                onClick={handleAddRule}
                disabled={saving === "new" || activeCount >= 10}
              >
                {saving === "new" ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-3.5" />}
                Add close rule
              </NeuButton>
            </div>
          </div>
        </NeuThemeScope>
      </div>
    </div>,
    document.body
  );
}

function RuleRow({
  rule,
  saving,
  onUpdate,
  onToggle,
  onDelete,
}: {
  rule: CloseRule;
  saving: boolean;
  onUpdate: (id: string, updates: UpdateCloseRuleData) => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const isPct = PCT_TYPES.has(rule.trigger_type);
  const isTime = TIME_TYPES.has(rule.trigger_type);
  const isTriggered = rule.status === "triggered";
  const isExecuted = rule.status === "executed";
  const isExpired = rule.status === "expired";
  const isTerminal = isTriggered || isExecuted || isExpired;
  const isActive = rule.status === "active";
  const isPaused = rule.status === "paused";
  const config = TRIGGER_CONFIG[rule.trigger_type];
  const Icon = config.icon;

  const [localThreshold, setLocalThreshold] = useState(rule.threshold_value);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleThresholdChange = useCallback((value: string) => {
    setLocalThreshold(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onUpdate(rule.id, { threshold_value: value });
    }, 500);
  }, [rule.id, onUpdate]);

  useEffect(() => {
    if (rule.threshold_value) {
      const parsed = parseFloat(rule.threshold_value);
      setLocalThreshold(isNaN(parsed) ? rule.threshold_value : String(parsed));
    } else {
      setLocalThreshold("");
    }
  }, [rule.threshold_value]);

  useEffect(() => {
    return () => clearTimeout(debounceRef.current);
  }, []);

  const statusLabel = isExecuted ? "Executed" : isTriggered ? "Triggered" : isExpired ? "Expired" : isActive ? "Armed" : "Paused";

  return (
    <article
      className={cn(
        "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4 sm:p-5 transition-all duration-300",
        isTerminal && "opacity-80",
      )}
    >
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="neu-surface-base neu-surface-raised flex size-11 items-center justify-center rounded-[var(--neu-radius-md)] shadow-[var(--neu-shadow-pill)]">
              <Icon className={cn("size-5", config.tone)} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">{config.label}</h3>
                <span className={cn("inline-flex items-center rounded-[var(--neu-radius-pill)] border border-transparent shadow-[var(--neu-shadow-pill)] px-2.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.18em]",
                  isPct ? "bg-[color-mix(in_oklch,var(--neu-accent)_12%,var(--neu-surface-raised))] text-[var(--neu-accent)]" : "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)]"
                )}>
                  {isPct ? "Percent trigger" : "Value trigger"}
                </span>
                <span className={cn("inline-flex items-center rounded-[var(--neu-radius-pill)] border border-transparent shadow-[var(--neu-shadow-pill)] px-2.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.18em]",
                  isExecuted ? "bg-[color-mix(in_oklch,var(--neu-success)_12%,var(--neu-surface-raised))] text-[var(--neu-success)]" :
                  isTriggered ? "bg-[color-mix(in_oklch,var(--neu-warning)_12%,var(--neu-surface-raised))] text-[var(--neu-warning)]" :
                  isActive ? "bg-[color-mix(in_oklch,var(--neu-accent)_12%,var(--neu-surface-raised))] text-[var(--neu-accent)]" :
                  "bg-[var(--neu-surface-muted)] text-[var(--neu-text-soft)]"
                )}>
                  {statusLabel}
                </span>
              </div>
              <p className="mt-1 text-sm leading-6 text-[var(--neu-text-muted)]">{config.description}</p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1.15fr)_12rem_10rem]">
            <div className="neu-input-base rounded-[var(--neu-radius-md)] p-3.5 transition-all duration-200 focus-within:ring-2 focus-within:ring-[var(--neu-accent)]">
              <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Trigger type</span>
              <select
                className="mt-1.5 w-full bg-transparent text-sm font-semibold text-[var(--neu-text-strong)] outline-none border-none cursor-pointer"
                value={rule.trigger_type}
                onChange={(e) => {
                  clearTimeout(debounceRef.current);
                  const newType = e.target.value as TriggerType;
                  const wasPct = PCT_TYPES.has(rule.trigger_type);
                  const isPctNow = PCT_TYPES.has(newType);
                  const updates: UpdateCloseRuleData = { trigger_type: newType };
                  if (wasPct !== isPctNow) {
                    updates.threshold_value = isPctNow ? "5" : "100";
                    setLocalThreshold(updates.threshold_value);
                  }
                  onUpdate(rule.id, updates);
                }}
                disabled={isTerminal}
              >
                {TRIGGER_OPTIONS.map((t) => (
                  <option key={t} value={t} className="bg-[var(--neu-surface-raised)] text-[var(--neu-text-strong)]">
                    {TRIGGER_CONFIG[t].label}
                  </option>
                ))}
              </select>
            </div>

            <div className="neu-input-base rounded-[var(--neu-radius-md)] p-3.5 transition-all duration-200 focus-within:ring-2 focus-within:ring-[var(--neu-accent)]">
              <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">{isTime ? "Minutes" : "Threshold"}</span>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="text-sm font-semibold text-[var(--neu-text-muted)]">{isTime ? "min" : isPct ? "%" : "$"}</span>
                <input
                  type="text"
                  className="w-full bg-transparent text-sm font-bold tabular-nums text-[var(--neu-text-strong)] outline-none disabled:opacity-60 border-none"
                  value={localThreshold}
                  onChange={(e) => handleThresholdChange(e.target.value)}
                  disabled={isTerminal}
                />
              </div>
            </div>

            <div className="neu-input-base flex items-center justify-between rounded-[var(--neu-radius-md)] p-3.5">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">Arm state</div>
                <div className="mt-1.5 text-sm font-semibold text-[var(--neu-text-strong)]">{isTerminal ? statusLabel : isActive ? "Live" : "Standby"}</div>
              </div>
              {isTerminal ? (
                <div className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] border border-transparent shadow-[var(--neu-shadow-pill)]",
                  isExecuted ? "bg-[color-mix(in_oklch,var(--neu-success)_15%,var(--neu-surface-raised))] text-[var(--neu-success)]" :
                  isTriggered ? "bg-[color-mix(in_oklch,var(--neu-warning)_15%,var(--neu-surface-raised))] text-[var(--neu-warning)]" :
                  "bg-[var(--neu-surface-muted)] text-[var(--neu-text-soft)]"
                )}>
                  {statusLabel}
                </div>
              ) : (
                <button
                  type="button"
                  role="switch"
                  aria-checked={isActive}
                  className={cn(
                    "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-all duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--neu-accent)] border-none shadow-[var(--neu-shadow-inset)]",
                    isActive ? "bg-[color-mix(in_oklch,var(--neu-surface-muted)_70%,var(--neu-shadow))]" : "bg-[var(--neu-surface-muted)]"
                  )}
                  onClick={onToggle}
                  aria-label={isActive ? "Pause rule" : "Activate rule"}
                >
                  <span
                    className={cn(
                      "pointer-events-none block size-5 rounded-full bg-[var(--neu-surface-raised)] ring-0 transition duration-300 [transition-timing-function:cubic-bezier(0.34,1.56,0.64,1)] transform",
                      isActive ? "translate-x-[24px] shadow-[var(--neu-shadow-raised-soft)]" : "translate-x-[4px] shadow-[var(--neu-shadow-pill)]"
                    )}
                  />
                </button>
              )}
            </div>
          </div>

          {isPct && rule.reference_value ? (
            <div className="neu-input-base mt-3 rounded-[var(--neu-radius-sm)] px-3.5 py-2.5 text-[12px] text-[var(--neu-text-muted)]">
              Reference equity snapshot: <span className="font-semibold text-[var(--neu-text-strong)]">${parseFloat(rule.reference_value).toFixed(2)}</span>
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2 xl:pl-4 shrink-0">
          {isPaused ? (
            <span className="inline-flex items-center rounded-full border border-transparent shadow-[var(--neu-shadow-pill)] bg-[var(--neu-surface-muted)] px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">
              Paused
            </span>
          ) : null}
          <NeuButton
            type="button"
            variant="ghost"
            size="icon"
            className="size-9 text-[var(--neu-danger)] hover:text-[var(--neu-danger)] hover:bg-[color-mix(in_oklch,var(--neu-danger)_8%,transparent)] shrink-0 flex items-center justify-center"
            onClick={onDelete}
            disabled={!!saving}
            aria-label="Delete rule"
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
          </NeuButton>
        </div>
      </div>
    </article>
  );
}
