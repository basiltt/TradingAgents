/**
 * MCPToolBudget — the context-budget tool manager.
 *
 * Directly serves the core requirement: "if we enable all the tools at the same
 * time the context size of the model will be full, so the user should be able to
 * enable and disable which group of tools or which individual tool needs to be
 * enabled." Each group is collapsible; each tool shows its token cost and can be
 * toggled individually. Presets give one-click safe selections. The TokenMeter
 * at the top shows the running total against a chosen context budget.
 *
 * Writes go through enabled_tools overrides (most-restrictive resolution on the
 * backend), so an individual OFF always wins over a group being on.
 */
import { useMemo, useState } from "react";
import { ChevronDown, Lock, Zap, AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { CONTEXT_BUDGETS, formatTokens } from "./tokenBudget";
import { TokenMeter } from "./TokenMeter";
import { GROUP_LABELS, PRESET_LABELS } from "./types";
import type { MCPRegistry, MCPToolEntry } from "./types";

export function MCPToolBudget({
  registry,
  busy,
  onToggleTool,
  onApplyPreset,
}: {
  registry: MCPRegistry;
  busy: boolean;
  onToggleTool: (toolName: string, next: boolean) => void;
  onApplyPreset: (preset: string) => void;
}) {
  const [budgetKey, setBudgetKey] = useState<string>("Comfortable (16k)");
  const budget = CONTEXT_BUDGETS[budgetKey];

  // Partition tools by group, preserving the backend's stable ordering.
  const byGroup = useMemo(() => {
    const m = new Map<string, MCPToolEntry[]>();
    for (const t of registry.tools) {
      const arr = m.get(t.group) ?? [];
      arr.push(t);
      m.set(t.group, arr);
    }
    return [...m.entries()];
  }, [registry.tools]);

  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold tracking-tight text-[var(--neu-text-strong)]">
              Tool budget
            </h3>
            <p className="mt-0.5 text-xs text-[var(--neu-text-muted)]">
              Enable only what the agent needs — each tool consumes the model's context window.
            </p>
          </div>
          <BudgetSelector value={budgetKey} onChange={setBudgetKey} />
        </div>

        <TokenMeter
          selected={registry.selected_est_tokens}
          total={registry.total_est_tokens}
          budget={budget}
        />

        <div className="flex flex-wrap gap-1.5">
          <span className="mr-1 self-center text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
            Presets
          </span>
          {Object.keys(registry.presets).map((p) => (
            <Button
              key={p}
              variant="outline"
              size="xs"
              disabled={busy}
              onClick={() => onApplyPreset(p)}
            >
              {PRESET_LABELS[p] ?? p}
            </Button>
          ))}
        </div>
      </div>

      <div className="mt-4 space-y-2.5">
        {byGroup.map(([group, tools]) => (
          <GroupSection
            key={group}
            group={group}
            tools={tools}
            busy={busy}
            onToggleTool={onToggleTool}
          />
        ))}
      </div>
    </div>
  );
}

function BudgetSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-inset)] p-1">
      {Object.keys(CONTEXT_BUDGETS).map((k) => (
        <button
          key={k}
          type="button"
          onClick={() => onChange(k)}
          className={cn(
            "rounded-[var(--neu-radius-sm)] px-2.5 py-1 text-[11px] font-semibold transition-colors neu-focus-ring",
            value === k
              ? "bg-[var(--neu-surface-raised)] text-[var(--neu-accent)] shadow-[var(--neu-shadow-soft)]"
              : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]",
          )}
        >
          {k.split(" ")[0]}
        </button>
      ))}
    </div>
  );
}

function GroupSection({
  group,
  tools,
  busy,
  onToggleTool,
}: {
  group: string;
  tools: MCPToolEntry[];
  busy: boolean;
  onToggleTool: (toolName: string, next: boolean) => void;
}) {
  const enabledCount = tools.filter((t) => t.enabled).length;
  const groupTokens = tools.reduce((sum, t) => sum + t.est_tokens, 0);
  const selectedTokens = tools.filter((t) => t.enabled).reduce((sum, t) => sum + t.est_tokens, 0);
  // `open` is DERIVED: a group with enabled tools auto-expands (so a preset that
  // enables tools in a collapsed group reveals them), unless the user has
  // explicitly overridden it. No setState-in-effect — override is null until a
  // click, then it wins. Tracking the override (not `open`) keeps it reactive to
  // enabledCount changes from presets.
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? enabledCount > 0;

  function toggleOpen() {
    setOverride(!open);
  }

  return (
    <div className="overflow-hidden rounded-[var(--neu-radius-md)] border border-[var(--neu-stroke-soft)]">
      <button
        type="button"
        onClick={toggleOpen}
        className="flex w-full items-center justify-between gap-3 bg-[var(--neu-surface-flat)] px-3.5 py-2.5 text-left transition-colors hover:bg-[var(--neu-surface-inset)] neu-focus-ring"
      >
        <div className="flex items-center gap-2.5">
          <ChevronDown className={cn("size-4 text-[var(--neu-text-muted)] transition-transform", !open && "-rotate-90")} />
          <span className="text-sm font-semibold text-[var(--neu-text-strong)]">
            {GROUP_LABELS[group] ?? group}
          </span>
          {enabledCount > 0 ? (
            <Badge variant="default" className="h-5 px-1.5 text-[10px]">
              {enabledCount}/{tools.length}
            </Badge>
          ) : (
            <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
              {tools.length}
            </Badge>
          )}
        </div>
        <span className="text-[11px] font-medium text-[var(--neu-text-muted)]">
          {formatTokens(selectedTokens)} / {formatTokens(groupTokens)} tok
        </span>
      </button>

      {open ? (
        <div className="divide-y divide-[var(--neu-stroke-soft)]">
          {tools.map((t) => (
            <ToolRow key={t.name} tool={t} busy={busy} onToggle={onToggleTool} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ToolRow({
  tool,
  busy,
  onToggle,
}: {
  tool: MCPToolEntry;
  busy: boolean;
  onToggle: (toolName: string, next: boolean) => void;
}) {
  const unavailable = !tool.available;
  return (
    <div className="flex items-center justify-between gap-3 bg-[var(--neu-surface-raised)] px-3.5 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <code className="truncate font-mono text-xs font-semibold text-[var(--neu-text-strong)]">
            {tool.name}
          </code>
          {tool.mutating ? (
            <span title="Mutating tool">
              <Zap className="size-3 text-warning" />
            </span>
          ) : null}
          {tool.safety_class === "live_money" ? (
            <span title="Live-money tool">
              <AlertTriangle className="size-3 text-destructive" />
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 line-clamp-1 text-[11px] text-[var(--neu-text-muted)]">{tool.description}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="text-[11px] font-medium tabular-nums text-[var(--neu-text-muted)]">
          {formatTokens(tool.est_tokens)}
        </span>
        {unavailable ? (
          <span
            title="Backing service unavailable or above the capability tier"
            className="flex items-center gap-1 text-[10px] font-medium text-[var(--neu-text-muted)]"
          >
            <Lock className="size-3" />
          </span>
        ) : (
          <ToggleSwitch
            checked={tool.enabled}
            disabled={busy}
            onChange={(next) => onToggle(tool.name, next)}
            label={`Toggle ${tool.name}`}
          />
        )}
      </div>
    </div>
  );
}

/** Minimal accessible switch built from a button (no Switch primitive exists). */
function ToggleSwitch({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 neu-focus-ring",
        checked ? "bg-[var(--neu-accent)]" : "bg-[var(--neu-surface-inset)]",
      )}
    >
      <span
        className={cn(
          "inline-block size-4 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
