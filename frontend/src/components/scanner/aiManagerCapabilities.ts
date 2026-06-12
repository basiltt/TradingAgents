import type { AIManagerCapabilities } from "@/api/client";

export type AICapabilityKey = keyof AIManagerCapabilities;

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

/** All 8 capabilities enabled — the default when the AI Manager is switched on.
 *  Derived from AI_MANAGER_CAPABILITIES so a newly-added capability is included
 *  automatically (single source of truth for the key set). */
export function allCapabilitiesOn(): AIManagerCapabilities {
  const out = {} as Record<AICapabilityKey, boolean>;
  for (const cap of AI_MANAGER_CAPABILITIES) {
    out[cap.key] = true;
  }
  return out;
}
