import { TriangleAlert } from "lucide-react";
import type { AIManagerCapabilities } from "@/api/client";
import { NeuSwitch } from "@/design-system/neumorphism";
import {
  AI_MANAGER_CAPABILITIES,
  allCapabilitiesOn,
  type AICapabilityKey,
} from "./aiManagerCapabilities";

interface AICapabilityPanelProps {
  value: AIManagerCapabilities;
  onChange: (next: AIManagerCapabilities) => void;
}

// Capabilities whose disablement changes the AI Manager's protective behavior.
// Each carries its own message because the effect differs: turning emergency_close
// off removes the fast crash-close; turning sweep_defense off makes the manager MORE
// willing to close into stop-hunts/liquidity sweeps. Keyed only (titles resolved from
// AI_MANAGER_CAPABILITIES) so labels never drift from the toggle metadata.
const SAFETY_WARNINGS: Partial<Record<AICapabilityKey, string>> = {
  emergency_close:
    "won't fast-close positions on sharp adverse moves (crash protection off)",
  sweep_defense:
    "may close into stop-hunts / liquidity sweeps instead of riding them out",
};
const SAFETY_KEYS = Object.keys(SAFETY_WARNINGS) as AICapabilityKey[];

const titleOf = (key: AICapabilityKey): string =>
  AI_MANAGER_CAPABILITIES.find((c) => c.key === key)?.title ?? key;

/**
 * Nested panel of per-scan AI Manager capability toggles. Rendered only when the
 * AI Position Manager switch is on. Each toggle flips one capability; "Reset to
 * all on" restores every capability to true.
 *
 * NeuSwitch does not forward arbitrary DOM props, so each row is wrapped in a
 * div carrying the data-testid; NeuSwitch's own `label`/`description` render the
 * copy. NeuSwitch renders role="switch".
 */
export function AICapabilityPanel({ value, onChange }: AICapabilityPanelProps) {
  // Normalize against a full all-on object so a partial/legacy object (missing
  // keys, or a future-added key) never renders a defined capability as OFF.
  const v: AIManagerCapabilities = { ...allCapabilitiesOn(), ...value };

  const setKey = (key: AICapabilityKey, checked: boolean) =>
    onChange({ ...v, [key]: checked });

  const disabledSafety = SAFETY_KEYS.filter((key) => v[key] === false);

  return (
    <div className="mt-3 ml-3 rounded-[var(--neu-radius-md)] neu-surface-base bg-[var(--neu-surface-muted)] p-3 shadow-[var(--neu-shadow-inset)] space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
          AI Manager capabilities
        </p>
        <button
          type="button"
          data-testid="ai-cap-reset"
          className="text-[10px] font-semibold uppercase tracking-wider text-[var(--neu-accent)] hover:underline"
          onClick={() => onChange(allCapabilitiesOn())}
        >
          Reset to all on
        </button>
      </div>
      {disabledSafety.length > 0 ? (
        <div
          role="alert"
          data-testid="ai-cap-safety-warning"
          className="flex items-start gap-2 rounded-[var(--neu-radius-sm)] border border-[color-mix(in_oklch,var(--neu-danger)_30%,var(--neu-stroke-soft))] bg-[color-mix(in_oklch,var(--neu-danger)_8%,var(--neu-surface-base))] px-3 py-2 text-[11px] leading-5 text-[color-mix(in_oklch,var(--neu-danger)_85%,var(--neu-text-strong))]"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-current" />
          <span>
            Crash protection reduced for this scan:
            <ul className="mt-1 list-disc pl-4 space-y-0.5">
              {disabledSafety.map((key) => (
                <li key={key}>
                  <span className="font-semibold">{titleOf(key)}</span> off — the AI
                  Manager {SAFETY_WARNINGS[key]}.
                </li>
              ))}
            </ul>
          </span>
        </div>
      ) : null}
      {AI_MANAGER_CAPABILITIES.map((cap) => (
        <div
          key={cap.key}
          data-testid={`ai-cap-row-${cap.key}`}
          className="rounded-[var(--neu-radius-sm)] neu-surface-base p-3 border-none shadow-[var(--shadow-card)]"
        >
          <NeuSwitch
            checked={v[cap.key]}
            onChange={(checked: boolean) => setKey(cap.key, checked)}
            label={cap.title}
            description={cap.description}
          />
        </div>
      ))}
    </div>
  );
}
