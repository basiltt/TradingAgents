export type ThemeMode = "light" | "dark" | "system";
export type ThemePalette = "aurora" | "lagoon" | "ember" | "verdant";

export interface ThemePaletteDefinition {
  key: ThemePalette;
  label: string;
  description: string;
  accentHue: number;
  accentChroma: number;
  accent2Hue: number;
  accent2Chroma: number;
  accent3Hue: number;
  accent3Chroma: number;
  surfaceHue: number;
  surfaceChroma: number;
  successHue: number;
  successChroma: number;
  warningHue: number;
  warningChroma: number;
  dangerHue: number;
  dangerChroma: number;
}

export const DEFAULT_THEME_MODE: ThemeMode = "system";
export const DEFAULT_THEME_PALETTE: ThemePalette = "aurora";

export const THEME_STORAGE_KEY = "tradingagents-ui-theme";
export const PALETTE_STORAGE_KEY = "tradingagents-ui-palette";

export const themeModeOrder = ["light", "dark", "system"] as const;

export const themePalettes = {
  aurora: {
    key: "aurora",
    label: "Aurora",
    description: "Electric indigo with coral and cyan highlights.",
    accentHue: 258,
    accentChroma: 0.22,
    accent2Hue: 320,
    accent2Chroma: 0.18,
    accent3Hue: 198,
    accent3Chroma: 0.14,
    surfaceHue: 252,
    surfaceChroma: 0.018,
    successHue: 150,
    successChroma: 0.17,
    warningHue: 84,
    warningChroma: 0.16,
    dangerHue: 28,
    dangerChroma: 0.22,
  },
  lagoon: {
    key: "lagoon",
    label: "Lagoon",
    description: "Ocean blue with seafoam depth and soft violet contrast.",
    accentHue: 225,
    accentChroma: 0.19,
    accent2Hue: 186,
    accent2Chroma: 0.13,
    accent3Hue: 285,
    accent3Chroma: 0.12,
    surfaceHue: 222,
    surfaceChroma: 0.02,
    successHue: 165,
    successChroma: 0.16,
    warningHue: 88,
    warningChroma: 0.15,
    dangerHue: 24,
    dangerChroma: 0.21,
  },
  ember: {
    key: "ember",
    label: "Ember",
    description: "Copper energy with ember orange and dusk plum accents.",
    accentHue: 28,
    accentChroma: 0.2,
    accent2Hue: 9,
    accent2Chroma: 0.19,
    accent3Hue: 312,
    accent3Chroma: 0.11,
    surfaceHue: 20,
    surfaceChroma: 0.017,
    successHue: 154,
    successChroma: 0.16,
    warningHue: 85,
    warningChroma: 0.16,
    dangerHue: 18,
    dangerChroma: 0.23,
  },
  verdant: {
    key: "verdant",
    label: "Verdant",
    description: "Fresh green with lime and sky gradients for brighter dashboards.",
    accentHue: 150,
    accentChroma: 0.17,
    accent2Hue: 110,
    accent2Chroma: 0.16,
    accent3Hue: 205,
    accent3Chroma: 0.12,
    surfaceHue: 162,
    surfaceChroma: 0.016,
    successHue: 152,
    successChroma: 0.17,
    warningHue: 90,
    warningChroma: 0.15,
    dangerHue: 24,
    dangerChroma: 0.22,
  },
} satisfies Record<ThemePalette, ThemePaletteDefinition>;

export const themePaletteOrder = Object.keys(themePalettes) as ThemePalette[];

function canUseDom() {
  return typeof window !== "undefined";
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return typeof value === "string" && themeModeOrder.includes(value as ThemeMode);
}

export function isThemePalette(value: unknown): value is ThemePalette {
  return typeof value === "string" && value in themePalettes;
}

export function getStoredThemeMode(): ThemeMode {
  if (!canUseDom()) return DEFAULT_THEME_MODE;
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return isThemeMode(value) ? value : DEFAULT_THEME_MODE;
}

export function getStoredThemePalette(): ThemePalette {
  if (!canUseDom()) return DEFAULT_THEME_PALETTE;
  const value = window.localStorage.getItem(PALETTE_STORAGE_KEY);
  return isThemePalette(value) ? value : DEFAULT_THEME_PALETTE;
}

export function resolveThemeMode(
  theme: ThemeMode,
  systemPrefersDark: boolean,
): "light" | "dark" {
  if (theme === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return theme;
}

export function applyPalette(
  root: HTMLElement,
  paletteKey: ThemePalette,
): ThemePaletteDefinition {
  const palette = themePalettes[paletteKey];
  const variables: Record<string, string> = {
    "--accent-hue": String(palette.accentHue),
    "--accent-chroma": palette.accentChroma.toFixed(3),
    "--accent-2-hue": String(palette.accent2Hue),
    "--accent-2-chroma": palette.accent2Chroma.toFixed(3),
    "--accent-3-hue": String(palette.accent3Hue),
    "--accent-3-chroma": palette.accent3Chroma.toFixed(3),
    "--surface-hue": String(palette.surfaceHue),
    "--surface-chroma": palette.surfaceChroma.toFixed(3),
    "--success-hue": String(palette.successHue),
    "--success-chroma": palette.successChroma.toFixed(3),
    "--warning-hue": String(palette.warningHue),
    "--warning-chroma": palette.warningChroma.toFixed(3),
    "--danger-hue": String(palette.dangerHue),
    "--danger-chroma": palette.dangerChroma.toFixed(3),
  };

  root.dataset.palette = palette.key;
  for (const [name, value] of Object.entries(variables)) {
    root.style.setProperty(name, value);
  }
  return palette;
}

export function persistAppearance(theme: ThemeMode, palette: ThemePalette) {
  if (!canUseDom()) return;
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  window.localStorage.setItem(PALETTE_STORAGE_KEY, palette);
}

export function getPalettePreview(paletteKey: ThemePalette): string {
  const palette = themePalettes[paletteKey];
  return `linear-gradient(135deg,
    oklch(0.72 ${palette.accentChroma.toFixed(3)} ${palette.accentHue}),
    oklch(0.76 ${palette.accent2Chroma.toFixed(3)} ${palette.accent2Hue}),
    oklch(0.78 ${palette.accent3Chroma.toFixed(3)} ${palette.accent3Hue}))`;
}
