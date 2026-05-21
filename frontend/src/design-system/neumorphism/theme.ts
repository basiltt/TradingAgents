import type {
  NeuAccentPalette,
  NeuContrastMode,
  NeuSurfaceMode,
} from "./types";

export const neuSurfaceModes = ["ivory", "graphite"] as const satisfies readonly NeuSurfaceMode[];
export const neuAccentPalettes = ["cobalt", "sage", "amber", "rose"] as const satisfies readonly NeuAccentPalette[];
export const neuContrastModes = ["balanced", "high"] as const satisfies readonly NeuContrastMode[];

export interface NeuAccentDefinition {
  key: NeuAccentPalette;
  label: string;
  description: string;
  accent: string;
  muted: string;
  ink: string;
  preview: string;
}

export const DEFAULT_NEU_MODE: NeuSurfaceMode = "ivory";
export const DEFAULT_NEU_ACCENT: NeuAccentPalette = "cobalt";
export const DEFAULT_NEU_CONTRAST: NeuContrastMode = "balanced";

export const neuAccentDefinitions: Record<NeuAccentPalette, NeuAccentDefinition> = {
  cobalt: {
    key: "cobalt",
    label: "Cobalt",
    description: "Calm blue emphasis for navigation, focus, and positive momentum.",
    accent: "oklch(0.61 0.13 257)",
    muted: "oklch(0.92 0.03 257)",
    ink: "oklch(0.22 0.03 257)",
    preview:
      "linear-gradient(135deg, oklch(0.68 0.14 257), oklch(0.78 0.08 235), oklch(0.88 0.03 220))",
  },
  sage: {
    key: "sage",
    label: "Sage",
    description: "Muted green emphasis for balanced monitoring surfaces.",
    accent: "oklch(0.69 0.11 154)",
    muted: "oklch(0.93 0.03 154)",
    ink: "oklch(0.26 0.03 154)",
    preview:
      "linear-gradient(135deg, oklch(0.76 0.12 154), oklch(0.82 0.07 132), oklch(0.9 0.03 118))",
  },
  amber: {
    key: "amber",
    label: "Amber",
    description: "Warm amber emphasis that keeps alerts visible without neon drift.",
    accent: "oklch(0.74 0.12 72)",
    muted: "oklch(0.95 0.03 72)",
    ink: "oklch(0.28 0.03 72)",
    preview:
      "linear-gradient(135deg, oklch(0.8 0.13 72), oklch(0.85 0.08 56), oklch(0.91 0.03 36))",
  },
  rose: {
    key: "rose",
    label: "Rose",
    description: "Measured rose emphasis for critical states and accent surfaces.",
    accent: "oklch(0.64 0.14 9)",
    muted: "oklch(0.93 0.03 9)",
    ink: "oklch(0.24 0.04 9)",
    preview:
      "linear-gradient(135deg, oklch(0.72 0.14 9), oklch(0.81 0.08 340), oklch(0.9 0.03 320))",
  },
};

export function getNeuAccentPreview(accent: NeuAccentPalette) {
  return neuAccentDefinitions[accent].preview;
}
