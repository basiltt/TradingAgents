import { useState, useEffect, useRef, useCallback } from "react";
import { Loader2, Plus, Trash2, X, ShieldCheck, TrendingDown, TrendingUp, DollarSign, Percent, Activity } from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/api/client";
import { useAppSelector } from "@/store";
import type { CloseRule, TriggerType, UpdateCloseRuleData } from "@/api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
  onSave: () => void;
}

const TRIGGER_CONFIG: Record<TriggerType, { label: string; description: string; icon: typeof TrendingDown; color: string }> = {
  BALANCE_BELOW:   { label: "Balance Below",           description: "Close when account equity drops below threshold",    icon: TrendingDown, color: "text-red-400" },
  BALANCE_ABOVE:   { label: "Balance Above",           description: "Close when account equity exceeds threshold",        icon: TrendingUp,   color: "text-emerald-400" },
  EQUITY_DROP_PCT: { label: "Equity Drop %",           description: "Close when equity drops by percentage",              icon: Percent,      color: "text-red-400" },
  EQUITY_RISE_PCT: { label: "Equity Rise %",           description: "Close when equity rises by percentage",              icon: Percent,      color: "text-emerald-400" },
  PNL_BELOW:       { label: "PnL Loss (Unrealized)",   description: "Close when unrealized PnL falls below threshold",    icon: DollarSign,   color: "text-red-400" },
  PNL_ABOVE:       { label: "PnL Profit (Unrealized)", description: "Close when unrealized PnL exceeds threshold",        icon: DollarSign,   color: "text-emerald-400" },
};

const TRIGGER_OPTIONS: TriggerType[] = [
  "BALANCE_BELOW", "BALANCE_ABOVE", "EQUITY_DROP_PCT", "EQUITY_RISE_PCT", "PNL_BELOW", "PNL_ABOVE",
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => !saving && handleDialogClose()}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-popover border border-border/50 rounded-2xl shadow-2xl shadow-black/30 max-w-[95vw] sm:max-w-xl w-full mx-2 sm:mx-4 max-h-[85vh] flex flex-col animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start gap-3.5 px-6 pt-5 pb-4 border-b border-border/30">
          <div className="p-2.5 rounded-xl bg-blue-500/10 mt-0.5">
            <ShieldCheck className="w-5 h-5 text-blue-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-base leading-tight">Conditional Close Rules</h3>
            <p className="text-xs text-muted-foreground mt-1">{accountLabel}</p>
            <div className="flex items-center gap-1.5 mt-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              <span className="text-[10px] text-emerald-400/80 font-medium tracking-wide uppercase">Evaluating every 30s</span>
            </div>
          </div>
          <button
            className="p-1.5 rounded-lg hover:bg-muted/40 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
            onClick={() => handleDialogClose()}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : rules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4">
              <div className="relative mb-5">
                <div className="w-16 h-16 rounded-2xl bg-muted/30 border border-border/30 flex items-center justify-center">
                  <Activity className="w-7 h-7 text-muted-foreground/40" />
                </div>
                <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-blue-500/15 border border-blue-500/20 flex items-center justify-center">
                  <Plus className="w-3 h-3 text-blue-400" />
                </div>
              </div>
              <p className="text-sm font-medium text-muted-foreground">No rules configured</p>
              <p className="text-xs text-muted-foreground/50 mt-1.5 text-center max-w-xs leading-relaxed">
                Set up automated position closing based on balance, equity, or PnL thresholds
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
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

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border/30">
          <button
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/20 hover:border-blue-500/30 transition-all disabled:opacity-40 disabled:pointer-events-none"
            onClick={handleAddRule}
            disabled={saving === "new" || activeCount >= 10}
          >
            {saving === "new" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Add Rule
            {activeCount > 0 && <span className="text-[10px] text-blue-400/50 ml-1">({activeCount}/10)</span>}
          </button>
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
    return () => clearTimeout(debounceRef.current);
  }, []);

  return (
    <div className={`group rounded-xl border transition-all ${
      isExpired
        ? "border-border/20 bg-muted/[0.03] opacity-60"
        : isTerminal
          ? "border-amber-500/25 bg-amber-500/[0.04]"
          : isActive
            ? "border-border/40 bg-card/60 hover:border-border/60"
            : "border-border/20 bg-muted/[0.03] opacity-50 hover:opacity-70"
    }`}>
      {/* Main row */}
      <div className="flex items-center gap-3 px-3.5 py-3">
        {/* Icon */}
        <div className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
          isExpired ? "bg-muted/20" : isTerminal ? "bg-amber-500/10" : isActive ? "bg-muted/40" : "bg-muted/20"
        }`}>
          <Icon className={`w-3.5 h-3.5 ${isExpired ? "text-muted-foreground/40" : isTerminal ? "text-amber-400" : isActive ? config.color : "text-muted-foreground/50"}`} />
        </div>

        {/* Trigger select */}
        <select
          className="bg-transparent border-0 text-sm font-medium appearance-none cursor-pointer hover:text-foreground/80 transition-colors focus:outline-none flex-1 min-w-0 truncate disabled:cursor-default disabled:opacity-70"
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

        {/* Threshold input */}
        <div className="relative shrink-0">
          <input
            type="text"
            className={`bg-muted/30 border border-border/30 rounded-lg py-1.5 text-xs font-mono w-24 tabular-nums focus:border-blue-500/40 focus:ring-1 focus:ring-blue-500/20 focus:outline-none transition-all ${
              isPct ? "px-2.5 pr-7" : "pl-6 pr-2.5"
            } ${isTerminal ? "opacity-60" : ""}`}
            value={localThreshold}
            onChange={(e) => handleThresholdChange(e.target.value)}
            disabled={isTerminal}
          />
          {isPct ? (
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground/40 font-medium">%</span>
          ) : (
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground/40 font-medium">$</span>
          )}
        </div>

        {/* Status / Toggle */}
        <div className="flex items-center gap-2 shrink-0">
          {isTerminal ? (
            <span className={`text-[10px] px-2 py-1 rounded-md font-semibold tracking-wide uppercase ${
              isExecuted
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : isExpired
                  ? "bg-muted/20 text-muted-foreground/60 border border-border/30"
                  : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
            }`}>
              {isExecuted ? "Executed" : isExpired ? "Expired" : "Triggered"}
            </span>
          ) : (
            <button
              className={`w-10 h-[22px] rounded-full transition-colors relative shrink-0 ${
                isActive ? "bg-emerald-500" : "bg-muted-foreground/20 hover:bg-muted-foreground/30"
              }`}
              onClick={onToggle}
              aria-label={isActive ? "Pause rule" : "Activate rule"}
            >
              <span className={`absolute top-[3px] w-4 h-4 rounded-full bg-white shadow-sm transition-all duration-200 ${
                isActive ? "left-[22px]" : "left-[3px]"
              }`} />
            </button>
          )}

          {/* Delete */}
          <button
            className="p-1.5 rounded-lg text-muted-foreground/40 hover:text-red-400 hover:bg-red-500/10 transition-all"
            onClick={onDelete}
            disabled={saving}
            aria-label="Delete rule"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Reference value footer */}
      {isPct && rule.reference_value && (
        <div className="px-3.5 pb-2.5 -mt-1">
          <p className="text-[10px] text-muted-foreground/40 pl-11">
            Reference: ${parseFloat(rule.reference_value).toFixed(2)} equity at rule creation
          </p>
        </div>
      )}
    </div>
  );
}
