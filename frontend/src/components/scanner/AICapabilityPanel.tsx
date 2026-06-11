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
  const setKey = (key: AICapabilityKey, checked: boolean) =>
    onChange({ ...value, [key]: checked });

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
      {AI_MANAGER_CAPABILITIES.map((cap) => (
        <div
          key={cap.key}
          data-testid={`ai-cap-row-${cap.key}`}
          className="rounded-[var(--neu-radius-sm)] neu-surface-base p-3 border-none shadow-[var(--shadow-card)]"
        >
          <NeuSwitch
            checked={value[cap.key]}
            onChange={(checked: boolean) => setKey(cap.key, checked)}
            label={cap.title}
            description={cap.description}
          />
        </div>
      ))}
    </div>
  );
}
