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

// Capabilities whose disablement removes a crash-protection / safety net. Toggling
// any of these off surfaces a danger warning so it isn't an unflagged footgun.
const SAFETY_KEYS: { key: AICapabilityKey; label: string }[] = [
  { key: "emergency_close", label: "Emergency Close" },
  { key: "sweep_defense", label: "Sweep / Stop-Hunt Defense" },
];

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

  const disabledSafety = SAFETY_KEYS.filter((s) => v[s.key] === false);

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
          data-testid="ai-cap-safety-warning"
          className="flex items-start gap-2 rounded-[var(--neu-radius-sm)] border border-[color-mix(in_oklch,var(--neu-danger)_30%,var(--neu-stroke-soft))] bg-[color-mix(in_oklch,var(--neu-danger)_8%,var(--neu-surface-base))] px-3 py-2 text-[11px] leading-5 text-[color-mix(in_oklch,var(--neu-danger)_85%,var(--neu-text-strong))]"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-current" />
          <span>
            Crash protection reduced: {disabledSafety.map((s) => s.label).join(" and ")}{" "}
            {disabledSafety.length > 1 ? "are" : "is"} off. The AI Manager won't fast-close
            positions on sharp adverse moves for this scan.
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
