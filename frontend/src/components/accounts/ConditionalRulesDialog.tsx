import { useState, useEffect, useRef, useCallback } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { CloseRule, TriggerType, UpdateCloseRuleData } from "@/api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
  onSave: () => void;
}

const TRIGGER_LABELS: Record<TriggerType, string> = {
  BALANCE_BELOW: "Balance Below",
  BALANCE_ABOVE: "Balance Above",
  EQUITY_DROP_PCT: "Equity Drop %",
  EQUITY_RISE_PCT: "Equity Rise %",
  PNL_BELOW: "PnL Loss (Unrealized)",
  PNL_ABOVE: "PnL Profit (Unrealized)",
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

  useEffect(() => {
    if (!open) {
      setRules([]);
      setLoading(true);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    api.getCloseRules(accountId, controller.signal)
      .then(setRules)
      .catch((e) => { if (!controller.signal.aborted) toast.error("Failed to load rules"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, accountId]);

  if (!open) return null;

  const handleAddRule = async () => {
    if (actionRef.current) return;
    actionRef.current = true;
    setSaving("new");
    try {
      const rule = await api.createCloseRule(accountId, {
        trigger_type: "BALANCE_BELOW",
        threshold_value: "100",
      });
      setRules((prev) => [rule, ...prev]);
      toast.success("Rule created");
      onSave();
    } catch (err: any) {
      if (err?.status === 409) {
        toast.error("Maximum rules reached for this account");
      } else {
        toast.error(err?.detail || "Failed to create rule");
      }
    } finally {
      actionRef.current = false;
      setSaving(null);
    }
  };

  const handleUpdateRule = async (ruleId: string, updates: UpdateCloseRuleData) => {
    try {
      const updated = await api.updateCloseRule(accountId, ruleId, updates);
      setRules((prev) => prev.map((r) => (r.id === ruleId ? updated : r)));
    } catch (err: any) {
      toast.error(err?.detail || "Failed to update rule");
    }
  };

  const handleToggleStatus = async (rule: CloseRule) => {
    const newStatus = rule.status === "active" ? "paused" : "active";
    try {
      const updated = await api.updateCloseRule(accountId, rule.id, { status: newStatus });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      onSave();
    } catch (err: any) {
      toast.error(err?.detail || "Failed to update rule");
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (actionRef.current) return;
    actionRef.current = true;
    setSaving(ruleId);
    try {
      await api.deleteCloseRule(accountId, ruleId);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
      toast.success("Rule deleted");
      onSave();
    } catch (err: any) {
      toast.error(err?.detail || "Failed to delete rule");
    } finally {
      actionRef.current = false;
      setSaving(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => !saving && onOpenChange(false)}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-popover border border-border/50 rounded-2xl shadow-2xl shadow-black/30 max-w-lg w-full mx-4 max-h-[80vh] flex flex-col animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/30">
          <div>
            <h3 className="font-semibold text-base">Conditional Close Rules</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{accountLabel} — evaluated every 30s</p>
          </div>
          <button
            className="p-1.5 rounded-lg hover:bg-muted/30 text-muted-foreground transition-colors"
            onClick={() => onOpenChange(false)}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : rules.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-sm text-muted-foreground">No rules set</p>
              <p className="text-xs text-muted-foreground/60 mt-1">Add a rule to automatically close positions when conditions are met</p>
            </div>
          ) : (
            rules.map((rule) => (
              <RuleRow
                key={rule.id}
                rule={rule}
                saving={saving === rule.id}
                onUpdate={handleUpdateRule}
                onToggle={() => handleToggleStatus(rule)}
                onDelete={() => handleDeleteRule(rule.id)}
              />
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border/30">
          <button
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm rounded-lg border border-dashed border-border/50 hover:border-border hover:bg-muted/20 text-muted-foreground transition-colors disabled:opacity-50"
            onClick={handleAddRule}
            disabled={saving === "new" || rules.filter((r) => r.status !== "triggered" && r.status !== "executed").length >= 10}
          >
            {saving === "new" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Add Rule
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
  const isTerminal = isTriggered || isExecuted;
  const isActive = rule.status === "active";

  const [localThreshold, setLocalThreshold] = useState(rule.threshold_value);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    setLocalThreshold(rule.threshold_value);
  }, [rule.threshold_value]);

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
    <div className={`rounded-xl border p-3.5 space-y-2.5 transition-colors ${
      isTerminal
        ? "border-amber-500/30 bg-amber-500/[0.03]"
        : isActive
          ? "border-border/50 bg-card/50"
          : "border-border/20 bg-muted/[0.02] opacity-60"
    }`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <select
            className="bg-muted/30 border border-border/30 rounded-lg px-2.5 py-1.5 text-xs flex-1 min-w-0"
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
              <option key={t} value={t}>{TRIGGER_LABELS[t]}</option>
            ))}
          </select>

          <div className="relative">
            <input
              type="text"
              className={`bg-muted/30 border border-border/30 rounded-lg py-1.5 text-xs w-24 tabular-nums ${
                isPct ? "px-2.5 pr-6" : "pl-5 pr-2.5"
              }`}
              value={localThreshold}
              onChange={(e) => handleThresholdChange(e.target.value)}
              disabled={isTerminal}
            />
            {isPct && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/50">%</span>
            )}
            {!isPct && (
              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/50">$</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {isTerminal ? (
            <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
              isExecuted ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-400"
            }`}>
              {isExecuted ? "Executed" : "Triggered"}
            </span>
          ) : (
            <button
              className={`w-9 h-5 rounded-full transition-colors relative ${
                isActive ? "bg-emerald-500" : "bg-muted-foreground/20"
              }`}
              onClick={onToggle}
              aria-label={isActive ? "Pause rule" : "Activate rule"}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                isActive ? "left-[18px]" : "left-0.5"
              }`} />
            </button>
          )}

          <button
            className="p-1 rounded-lg text-muted-foreground/40 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            onClick={onDelete}
            disabled={saving}
            aria-label="Delete rule"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {isPct && rule.reference_value && (
        <p className="text-[10px] text-muted-foreground/50">
          Reference: ${parseFloat(rule.reference_value).toFixed(2)} equity at rule creation
        </p>
      )}
    </div>
  );
}
