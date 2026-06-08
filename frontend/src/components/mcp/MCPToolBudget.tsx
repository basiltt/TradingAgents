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
import { ChevronDown, Lock, Zap, AlertTriangle, Info } from "lucide-react";

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
  onToggleDebug,
}: {
  registry: MCPRegistry;
  busy: boolean;
  onToggleTool: (toolName: string, next: boolean) => void;
  onApplyPreset: (preset: string) => void;
  onToggleDebug: (next: boolean) => void;
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

  // The set of currently-applied presets. Prefer the authoritative array;
  // fall back to the back-compat scalar so an older payload still highlights.
  const activePresets = useMemo(() => {
    if (registry.active_presets) return new Set(registry.active_presets);
    return new Set(registry.active_preset ? [registry.active_preset] : []);
  }, [registry.active_presets, registry.active_preset]);

  // Tools a preset INTENDS to enable but that stay dark at runtime — so a preset
  // that doesn't light up every tool is explained, not mysterious. Two causes:
  //   • exchange-facing/unavailable: never selectable here (cache_warmup etc.)
  //   • DEBUG tools while the allow_debug gate is off
  // Computed only when a preset is active (custom selections have no "intent").
  const heldBack = useMemo(
    () => (activePresets.size > 0 ? computeHeldBack(registry, activePresets) : []),
    [registry, activePresets],
  );

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

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 self-center text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
            Presets
          </span>
          {Object.keys(registry.presets).map((p) => {
            const active = activePresets.has(p);
            return (
              <Button
                key={p}
                // The applied preset(s) render as the primary (accent) variant so
                // there is a clear indication of what is active — fixing the "no
                // indication a preset is on" gap.
                variant={active ? "default" : "outline"}
                size="xs"
                disabled={busy}
                aria-pressed={active}
                onClick={() => onApplyPreset(p)}
              >
                {PRESET_LABELS[p] ?? p}
              </Button>
            );
          })}
          {activePresets.size === 0 ? (
            <span className="ml-1 self-center text-[11px] font-medium italic text-[var(--neu-text-muted)]">
              Custom selection
            </span>
          ) : null}
        </div>

        {activePresets.size > 1 ? (
          <p className="text-[11px] leading-relaxed text-[var(--neu-text-muted)]">
            These presets currently select the same tools, so all are highlighted.
            They diverge as more tools are added.
          </p>
        ) : null}

        {heldBack.length > 0 ? <HeldBackNotice tools={heldBack} /> : null}
      </div>

      <div className="mt-4 space-y-2.5">
        {byGroup.map(([group, tools]) => (
          <GroupSection
            key={group}
            group={group}
            tools={tools}
            busy={busy}
            allowDebug={registry.allow_debug ?? false}
            onToggleTool={onToggleTool}
            onToggleDebug={onToggleDebug}
          />
        ))}
      </div>
    </div>
  );
}

/** Tools a preset wants on but that are not actually advertised, with the reason.
 *  Drives the post-preset explanation so an incomplete-looking "Full" makes sense.
 *  `active` is the set of currently-applied presets (often one; several when they
 *  coincide) — we union their intended tools so the explanation is complete. */
function computeHeldBack(
  registry: MCPRegistry,
  active: Set<string>,
): { name: string; reason: string }[] {
  if (active.size === 0) return [];
  const intended = new Set<string>();
  for (const p of active) for (const name of registry.presets[p] ?? []) intended.add(name);
  const out: { name: string; reason: string }[] = [];
  for (const t of registry.tools) {
    if (!intended.has(t.name) || t.enabled) continue;
    // Order matters: the debug gate and exchange-facing are specific, known
    // reasons; `available` already folds in the capability-tier ceiling
    // (server sends available = service-present AND tier-ok), so it is the
    // correct catch-all and there is no separate "tier" branch to mislabel.
    const reason =
      t.group === "debug" && !(registry.allow_debug ?? false)
        ? "needs Debug forensics enabled"
        : t.exchange_facing
          ? "hits the live exchange (excluded for safety)"
          : !t.available
            ? "backing service unavailable or above the capability tier"
            : "not selected";
    out.push({ name: t.name, reason });
  }
  return out;
}

/** Explains why an applied preset left some tools off — so the count gap the user
 *  sees ("Full but 3 still off") is understood, not read as a bug. */
function HeldBackNotice({ tools }: { tools: { name: string; reason: string }[] }) {
  return (
    <div className="flex items-start gap-2.5 rounded-[var(--neu-radius-md)] border border-[var(--neu-stroke-soft)] bg-[var(--neu-surface-inset)] px-3.5 py-2.5">
      <Info className="mt-0.5 size-3.5 shrink-0 text-[var(--neu-text-muted)]" />
      <div className="text-[11px] leading-relaxed text-[var(--neu-text-muted)]">
        <span className="font-semibold text-[var(--neu-text-strong)]">
          {tools.length} tool{tools.length === 1 ? "" : "s"} stayed off by design.
        </span>{" "}
        Presets only enable tools that are safe and ready right now.
        <ul className="mt-1 space-y-0.5">
          {tools.map((t) => (
            <li key={t.name}>
              <code className="font-mono text-[var(--neu-text-strong)]">{t.name}</code>
              <span className="opacity-80"> — {t.reason}</span>
            </li>
          ))}
        </ul>
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
  allowDebug,
  onToggleTool,
  onToggleDebug,
}: {
  group: string;
  tools: MCPToolEntry[];
  busy: boolean;
  allowDebug: boolean;
  onToggleTool: (toolName: string, next: boolean) => void;
  onToggleDebug: (next: boolean) => void;
}) {
  const isDebug = group === "debug";
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
      {/* Header is a flex row (NOT a single button) so the Debug group can host
          its own gate switch beside the collapse control without nesting
          interactive elements. */}
      <div className="flex items-center gap-2 bg-[var(--neu-surface-flat)] pr-3.5 transition-colors hover:bg-[var(--neu-surface-inset)]">
        <button
          type="button"
          onClick={toggleOpen}
          className="flex flex-1 items-center justify-between gap-3 px-3.5 py-2.5 text-left neu-focus-ring"
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
        {isDebug ? (
          // A span (not a <label> wrapping the switch): the switch carries its own
          // aria-label, and a label forwarding a synthetic click to the contained
          // button can double-toggle. The title explains the gate on hover.
          <span
            className="flex shrink-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--neu-text-muted)]"
            title="Debug forensic tools expose internal decision traces. They stay hidden from the agent until you enable this gate, even when a preset selects them."
          >
            Forensics
            <ToggleSwitch
              checked={allowDebug}
              disabled={busy}
              onChange={onToggleDebug}
              label="Enable debug forensic tools"
            />
          </span>
        ) : null}
      </div>

      {open ? (
        <div className="divide-y divide-[var(--neu-stroke-soft)]">
          {tools.map((t) => (
            <ToolRow
              key={t.name}
              tool={t}
              busy={busy}
              gatedReason={isDebug && !allowDebug ? "Enable Forensics above to use this tool" : null}
              onToggle={onToggleTool}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ToolRow({
  tool,
  busy,
  gatedReason,
  onToggle,
}: {
  tool: MCPToolEntry;
  busy: boolean;
  /** When set, the tool is held off by a gate (e.g. Debug forensics) — show why
   *  and lock the switch, instead of a toggle that silently does nothing. */
  gatedReason: string | null;
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
        ) : gatedReason ? (
          <span
            title={gatedReason}
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
