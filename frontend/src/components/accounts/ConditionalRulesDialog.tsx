/* eslint-disable react-hooks/set-state-in-effect */
import { useState, useEffect, useRef, useCallback } from "react";
import {
  Activity,
  DollarSign,
  Loader2,
  Percent,
  Plus,
  ShieldCheck,
  Trash2,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useAppSelector } from "@/store";
import { cn } from "@/lib/utils";
import type { CloseRule, TriggerType, UpdateCloseRuleData } from "@/api/client";

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
    tone: "text-destructive",
    chip: "border-destructive/20 bg-destructive/10 text-destructive",
  },
  BALANCE_ABOVE: {
    label: "Balance Above",
    description: "Bank profits by closing exposure after balance exceeds a target.",
    icon: TrendingUp,
    tone: "text-success",
    chip: "border-success/20 bg-success/12 text-success",
  },
  EQUITY_DROP_PCT: {
    label: "Equity Drop %",
    description: "Trip the safeguard once equity falls from the starting reference.",
    icon: Percent,
    tone: "text-destructive",
    chip: "border-destructive/20 bg-destructive/10 text-destructive",
  },
  EQUITY_RISE_PCT: {
    label: "Equity Rise %",
    description: "Exit after the account reaches the configured growth target.",
    icon: Percent,
    tone: "text-success",
    chip: "border-success/20 bg-success/12 text-success",
  },
  PNL_BELOW: {
    label: "PnL Loss",
    description: "React to unrealized drawdown before losses deepen further.",
    icon: DollarSign,
    tone: "text-destructive",
    chip: "border-destructive/20 bg-destructive/10 text-destructive",
  },
  PNL_ABOVE: {
    label: "PnL Profit",
    description: "Take open profit automatically when unrealized gains reach target.",
    icon: DollarSign,
    tone: "text-success",
    chip: "border-success/20 bg-success/12 text-success",
  },
};

const TRIGGER_OPTIONS: TriggerType[] = [
  "BALANCE_BELOW",
  "BALANCE_ABOVE",
  "EQUITY_DROP_PCT",
  "EQUITY_RISE_PCT",
  "PNL_BELOW",
  "PNL_ABOVE",
];

const PCT_TYPES = new Set<TriggerType>(["EQUITY_DROP_PCT", "EQUITY_RISE_PCT"]);

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4"
      onClick={() => !saving && handleDialogClose()}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,oklch(0.6_0.12_220_/_0.18),transparent_34%),rgba(3,8,20,0.78)] backdrop-blur-md" />
      <div
        className="glass-card relative flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-[calc(var(--radius)*2)] border border-border/70 bg-card/90 shadow-[0_44px_140px_-56px_rgba(0,0,0,0.82)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--primary)_48%,white),transparent)]" />

        <div className="border-b border-border/55 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-4">
              <div className="gradient-primary flex size-14 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.35)] text-primary-foreground shadow-[var(--shadow-accent)]">
                <ShieldCheck className="size-6" />
              </div>
              <div className="min-w-0">
                <p className="section-eyebrow">Automated risk governance</p>
                <h2 className="mt-1 text-xl font-semibold tracking-[-0.04em] text-foreground sm:text-[1.7rem]">
                  Conditional close rules
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                  Protect <span className="font-semibold text-foreground">{accountLabel}</span> with threshold-based exits that react to equity,
                  balance, and unrealized PnL without requiring manual intervention.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3 lg:justify-end">
              {[
                { label: "Configured", value: String(rules.length), tone: "accent" },
                { label: "Armed", value: String(armedCount), tone: armedCount ? "success" : "neutral" },
                { label: "Limit", value: `${activeCount}/10`, tone: activeCount >= 10 ? "warning" : "neutral" },
              ].map((item) => (
                <div
                  key={item.label}
                  data-tone={item.tone}
                  className="page-header-stat min-w-[8rem] rounded-[calc(var(--radius)*1.1)] border px-4 py-3"
                >
                  <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">{item.label}</div>
                  <div className="mt-2 text-lg font-semibold tracking-[-0.04em] text-foreground">{item.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <span className="inline-flex items-center gap-2 rounded-full border border-success/20 bg-success/10 px-3 py-1 text-success">
              <span className="relative flex size-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
                <span className="relative inline-flex size-2.5 rounded-full bg-current" />
              </span>
              Evaluation heartbeat every 30s
            </span>
            <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/55 px-3 py-1">
              <Activity className="size-3.5" />
              Live synced with account close executions
            </span>
          </div>
        </div>

        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.45fr)_20rem]">
          <div className="custom-scrollbar overflow-y-auto px-5 py-5 sm:px-6">
            {loading ? (
              <div className="flex min-h-[22rem] items-center justify-center">
                <div className="surface-lift flex items-center gap-3 rounded-[calc(var(--radius)*1.25)] px-5 py-4 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Loading close rules...
                </div>
              </div>
            ) : rules.length === 0 ? (
              <div className="flex min-h-[22rem] flex-col items-center justify-center rounded-[calc(var(--radius)*1.6)] border border-dashed border-border/60 bg-background/35 px-6 text-center">
                <div className="gradient-primary flex size-16 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <Plus className="size-6" />
                </div>
                <h3 className="mt-5 text-lg font-semibold tracking-tight text-foreground">No automated exits configured</h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
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
          </div>

          <aside className="border-t border-border/55 bg-background/24 px-5 py-5 sm:px-6 lg:border-l lg:border-t-0">
            <div className="space-y-4">
              <div className="surface-lift rounded-[calc(var(--radius)*1.25)] p-4">
                <p className="section-eyebrow">Rule strategy</p>
                <h3 className="mt-2 text-sm font-semibold text-foreground">Suggested setup</h3>
                <ul className="mt-3 space-y-2.5 text-sm leading-6 text-muted-foreground">
                  <li>• Pair one hard downside rule with one upside take-profit rule.</li>
                  <li>• Use percentage triggers for portable rules across account sizes.</li>
                  <li>• Keep “armed” rules below the limit to leave room for temporary overrides.</li>
                </ul>
              </div>

              <div className="rounded-[calc(var(--radius)*1.25)] border border-border/60 bg-card/55 p-4">
                <p className="section-eyebrow">Trigger types</p>
                <div className="mt-3 space-y-2">
                  {TRIGGER_OPTIONS.map((type) => {
                    const config = TRIGGER_CONFIG[type];
                    const Icon = config.icon;
                    return (
                      <div key={type} className="flex items-start gap-3 rounded-[calc(var(--radius)*1.05)] border border-border/50 bg-background/40 px-3 py-3">
                        <Icon className={cn("mt-0.5 size-4 shrink-0", config.tone)} />
                        <div>
                          <p className="text-sm font-semibold text-foreground">{config.label}</p>
                          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{config.description}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </aside>
        </div>

        <div className="flex flex-col gap-3 border-t border-border/55 px-5 py-4 sm:px-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Rules sync instantly after edits. Terminal states stay visible for audit context.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="button" variant="outline" onClick={() => handleDialogClose()}>
              <X className="size-4" />
              Close panel
            </Button>
            <Button
              type="button"
              onClick={handleAddRule}
              disabled={saving === "new" || activeCount >= 10}
            >
              {saving === "new" ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
              Add close rule
            </Button>
          </div>
        </div>
      </div>
    </div>
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
    setLocalThreshold(rule.threshold_value);
  }, [rule.threshold_value]);

  useEffect(() => {
    return () => clearTimeout(debounceRef.current);
  }, []);

  const statusLabel = isExecuted ? "Executed" : isTriggered ? "Triggered" : isExpired ? "Expired" : isActive ? "Armed" : "Paused";
  const statusClass = isExecuted
    ? "border-success/20 bg-success/12 text-success"
    : isTriggered
      ? "border-warning/20 bg-warning/12 text-warning"
      : isExpired
        ? "border-border/60 bg-muted/30 text-muted-foreground"
        : isActive
          ? "border-primary/20 bg-primary/12 text-primary"
          : "border-border/60 bg-background/65 text-muted-foreground";

  return (
    <article
      className={cn(
        "glass-card rounded-[calc(var(--radius)*1.4)] border p-4 sm:p-5",
        isTerminal && "opacity-85",
      )}
    >
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="surface-lift flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.1)] border border-border/60">
              <Icon className={cn("size-5", config.tone)} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold tracking-[-0.03em] text-foreground">{config.label}</h3>
                <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", config.chip)}>
                  {isPct ? "Percent trigger" : "Value trigger"}
                </span>
                <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", statusClass)}>
                  {statusLabel}
                </span>
              </div>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">{config.description}</p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1.15fr)_12rem_10rem]">
            <label className="surface-lift rounded-[calc(var(--radius)*1.1)] p-3.5">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Trigger type</div>
              <select
                className="mt-2 w-full bg-transparent text-sm font-semibold text-foreground outline-none"
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
                  <option key={t} value={t}>{TRIGGER_CONFIG[t].label}</option>
                ))}
              </select>
            </label>

            <label className="surface-lift rounded-[calc(var(--radius)*1.1)] p-3.5">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Threshold</div>
              <div className="mt-2 flex items-center gap-2">
                <span className="text-sm font-semibold text-muted-foreground">{isPct ? "%" : "$"}</span>
                <input
                  type="text"
                  className="w-full bg-transparent text-sm font-semibold tabular-nums text-foreground outline-none disabled:opacity-60"
                  value={localThreshold}
                  onChange={(e) => handleThresholdChange(e.target.value)}
                  disabled={isTerminal}
                />
              </div>
            </label>

            <div className="surface-lift flex items-center justify-between rounded-[calc(var(--radius)*1.1)] p-3.5">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Arm state</div>
                <div className="mt-2 text-sm font-semibold text-foreground">{isTerminal ? statusLabel : isActive ? "Live" : "Standby"}</div>
              </div>
              {isTerminal ? (
                <div className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", statusClass)}>
                  {statusLabel}
                </div>
              ) : (
                <button
                  type="button"
                  className={cn(
                    "relative h-7 w-12 rounded-full border p-1 transition-colors",
                    isActive ? "border-primary/30 bg-primary/20" : "border-border/60 bg-muted/40",
                  )}
                  onClick={onToggle}
                  aria-label={isActive ? "Pause rule" : "Activate rule"}
                >
                  <span
                    className={cn(
                      "block size-5 rounded-full bg-white shadow-[var(--shadow-soft)] transition-transform dark:bg-foreground",
                      isActive && "translate-x-5",
                    )}
                  />
                </button>
              )}
            </div>
          </div>

          {isPct && rule.reference_value ? (
            <div className="mt-3 rounded-[calc(var(--radius)*1.05)] border border-border/55 bg-background/35 px-3.5 py-2.5 text-[12px] text-muted-foreground">
              Reference equity snapshot: <span className="font-semibold text-foreground">${parseFloat(rule.reference_value).toFixed(2)}</span>
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2 xl:pl-4">
          {isPaused ? (
            <span className="inline-flex items-center rounded-full border border-border/60 bg-background/65 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Paused
            </span>
          ) : null}
          <Button type="button" variant="ghost" size="icon-sm" onClick={onDelete} disabled={saving} aria-label="Delete rule">
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
          </Button>
        </div>
      </div>
    </article>
  );
}
