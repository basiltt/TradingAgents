import type { AIManagerCapabilities } from "@/api/client";

export type AICapabilityKey = keyof AIManagerCapabilities;

// Compile-time exhaustiveness guard: this object MUST list every key of the
// AIManagerCapabilities interface (and no extras). Adding a field to the interface
// without adding it here is a TypeScript error — keeping the interface, this key set,
// and the metadata array below in lockstep (the metadata match is enforced by a test).
// NOTE: parity with the BACKEND AIManagerCapabilityToggles is NOT compiler-enforced —
// the two key sets must be kept in sync manually (the backend has its own drift test).
const CAPABILITY_KEY_PRESENCE: Record<AICapabilityKey, true> = {
  mtf: true,
  orderbook: true,
  sweep_defense: true,
  correlation: true,
  regime_enhanced: true,
  event_driven: true,
  trailing: true,
  emergency_close: true,
};

export const AI_CAPABILITY_KEYS = Object.keys(
  CAPABILITY_KEY_PRESENCE,
) as AICapabilityKey[];

export interface AICapabilityMeta {
  key: AICapabilityKey;
  title: string;
  description: string;
}

/** Display order + copy for the per-scan AI Manager capability toggles. */
export const AI_MANAGER_CAPABILITIES: AICapabilityMeta[] = [
  { key: "mtf", title: "Multi-Timeframe Analysis", description: "Aligns trend across 5m/15m/1h/4h before acting on a position." },
  { key: "orderbook", title: "Order Book Monitoring", description: "Reads live bid/ask imbalance and depth around the position." },
  { key: "sweep_defense", title: "Sweep / Stop-Hunt Defense", description: "Avoids closing into liquidity sweeps and stop-hunts." },
  { key: "correlation", title: "Correlation & Clustering", description: "Tracks portfolio heat and correlated-position clusters." },
  { key: "regime_enhanced", title: "Regime Enhancement", description: "Adapts decisions to the detected market regime." },
  { key: "event_driven", title: "Event-Driven Evaluation", description: "Reacts to live triggers (price moves, drawdown) plus a safety-net timer." },
  { key: "trailing", title: "Trailing TP/SL", description: "Dynamically trails take-profit / stop-loss on profitable positions." },
  { key: "emergency_close", title: "Emergency Close", description: "Deterministic fast-path crash protection on sharp adverse moves." },
];

/** All capabilities enabled — the default when the AI Manager is switched on.
 *  Built from the compile-time-checked key set, so it always covers every
 *  AIManagerCapabilities field (single source of truth). */
export function allCapabilitiesOn(): AIManagerCapabilities {
  const out = {} as Record<AICapabilityKey, boolean>;
  for (const key of AI_CAPABILITY_KEYS) {
    out[key] = true;
  }
  return out;
}
