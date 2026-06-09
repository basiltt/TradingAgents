import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  isThemeMode,
  isThemePalette,
  isThemeContrast,
  getStoredThemeMode,
  getStoredThemePalette,
  getStoredThemeContrast,
  resolveThemeMode,
  applyPalette,
  applyContrast,
  persistAppearance,
  getPalettePreview,
  themePalettes,
  DEFAULT_THEME_MODE,
  DEFAULT_THEME_PALETTE,
  DEFAULT_THEME_CONTRAST,
  THEME_STORAGE_KEY,
  PALETTE_STORAGE_KEY,
  CONTRAST_STORAGE_KEY,
} from "../theme";

// AI-CONTEXT: resolveThemeMode does NOT call window.matchMedia — it accepts the
// already-resolved `prefers-color-scheme: dark` result as a boolean parameter.
// So these tests pass true/false directly rather than stubbing matchMedia.

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("isThemeMode", () => {
  it("accepts every valid mode string", () => {
    expect(isThemeMode("light")).toBe(true);
    expect(isThemeMode("dark")).toBe(true);
    expect(isThemeMode("system")).toBe(true);
  });

  it("rejects unknown strings (case-sensitive)", () => {
    expect(isThemeMode("LIGHT")).toBe(false);
    expect(isThemeMode("auto")).toBe(false);
    expect(isThemeMode("")).toBe(false);
  });

  it("rejects non-string values", () => {
    expect(isThemeMode(null)).toBe(false);
    expect(isThemeMode(undefined)).toBe(false);
    expect(isThemeMode(123)).toBe(false);
    expect(isThemeMode({})).toBe(false);
    expect(isThemeMode(["dark"])).toBe(false);
  });
});

describe("isThemePalette", () => {
  it("accepts every registered palette key", () => {
    expect(isThemePalette("aurora")).toBe(true);
    expect(isThemePalette("lagoon")).toBe(true);
    expect(isThemePalette("ember")).toBe(true);
    expect(isThemePalette("verdant")).toBe(true);
  });

  it("rejects unknown palette names", () => {
    expect(isThemePalette("crimson")).toBe(false);
    expect(isThemePalette("blue")).toBe(false);
    expect(isThemePalette("")).toBe(false);
  });

  it("rejects non-string values", () => {
    expect(isThemePalette(null)).toBe(false);
    expect(isThemePalette(undefined)).toBe(false);
    expect(isThemePalette(42)).toBe(false);
    expect(isThemePalette({ key: "aurora" })).toBe(false);
  });
});

describe("isThemeContrast", () => {
  it("accepts both valid contrast strings", () => {
    expect(isThemeContrast("standard")).toBe(true);
    expect(isThemeContrast("high")).toBe(true);
  });

  it("rejects unknown strings (case-sensitive)", () => {
    expect(isThemeContrast("low")).toBe(false);
    expect(isThemeContrast("HIGH")).toBe(false);
    expect(isThemeContrast("")).toBe(false);
  });

  it("rejects non-string values", () => {
    expect(isThemeContrast(null)).toBe(false);
    expect(isThemeContrast(undefined)).toBe(false);
    expect(isThemeContrast(true)).toBe(false);
    expect(isThemeContrast(0)).toBe(false);
  });
});

describe("getStoredThemeMode", () => {
  it("returns the default when nothing is stored", () => {
    expect(getStoredThemeMode()).toBe(DEFAULT_THEME_MODE);
    expect(getStoredThemeMode()).toBe("system");
  });

  it("returns the persisted value when valid", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(getStoredThemeMode()).toBe("dark");
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(getStoredThemeMode()).toBe("light");
  });

  it("falls back to the default for an invalid stored value", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(getStoredThemeMode()).toBe(DEFAULT_THEME_MODE);
  });

  it("falls back to the default for an empty stored string", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "");
    expect(getStoredThemeMode()).toBe(DEFAULT_THEME_MODE);
  });
});

describe("getStoredThemePalette", () => {
  it("returns the default when nothing is stored", () => {
    expect(getStoredThemePalette()).toBe(DEFAULT_THEME_PALETTE);
    expect(getStoredThemePalette()).toBe("lagoon");
  });

  it("returns the persisted value when valid", () => {
    localStorage.setItem(PALETTE_STORAGE_KEY, "ember");
    expect(getStoredThemePalette()).toBe("ember");
    localStorage.setItem(PALETTE_STORAGE_KEY, "verdant");
    expect(getStoredThemePalette()).toBe("verdant");
  });

  it("falls back to the default for an unknown palette", () => {
    localStorage.setItem(PALETTE_STORAGE_KEY, "sunset");
    expect(getStoredThemePalette()).toBe(DEFAULT_THEME_PALETTE);
  });
});

describe("getStoredThemeContrast", () => {
  it("returns the default when nothing is stored", () => {
    expect(getStoredThemeContrast()).toBe(DEFAULT_THEME_CONTRAST);
    expect(getStoredThemeContrast()).toBe("standard");
  });

  it("returns the persisted value when valid", () => {
    localStorage.setItem(CONTRAST_STORAGE_KEY, "high");
    expect(getStoredThemeContrast()).toBe("high");
  });

  it("falls back to the default for an invalid stored value", () => {
    localStorage.setItem(CONTRAST_STORAGE_KEY, "ultra");
    expect(getStoredThemeContrast()).toBe(DEFAULT_THEME_CONTRAST);
  });
});

describe("resolveThemeMode", () => {
  it("returns the concrete mode unchanged for non-system modes", () => {
    expect(resolveThemeMode("light", true)).toBe("light");
    expect(resolveThemeMode("light", false)).toBe("light");
    expect(resolveThemeMode("dark", false)).toBe("dark");
    expect(resolveThemeMode("dark", true)).toBe("dark");
  });

  it("resolves system to dark when the OS prefers dark", () => {
    expect(resolveThemeMode("system", true)).toBe("dark");
  });

  it("resolves system to light when the OS does not prefer dark", () => {
    expect(resolveThemeMode("system", false)).toBe("light");
  });

  it("never returns 'system'", () => {
    expect(resolveThemeMode("system", true)).not.toBe("system");
    expect(resolveThemeMode("system", false)).not.toBe("system");
  });
});

describe("applyPalette", () => {
  let root: HTMLElement;

  beforeEach(() => {
    root = document.createElement("div");
  });

  it("tags the element with data-palette", () => {
    applyPalette(root, "lagoon");
    expect(root.dataset.palette).toBe("lagoon");
    expect(root.getAttribute("data-palette")).toBe("lagoon");
  });

  it("writes integer hue values as plain strings", () => {
    applyPalette(root, "lagoon");
    expect(root.style.getPropertyValue("--accent-hue")).toBe("225");
    expect(root.style.getPropertyValue("--accent-2-hue")).toBe("186");
    expect(root.style.getPropertyValue("--danger-hue")).toBe("24");
  });

  it("writes chroma values rounded to 3 decimals via toFixed(3)", () => {
    applyPalette(root, "lagoon");
    expect(root.style.getPropertyValue("--accent-chroma")).toBe("0.190");
    expect(root.style.getPropertyValue("--surface-chroma")).toBe("0.020");
    expect(root.style.getPropertyValue("--danger-chroma")).toBe("0.210");
  });

  it("writes the full custom-property set for a different palette", () => {
    applyPalette(root, "aurora");
    expect(root.dataset.palette).toBe("aurora");
    expect(root.style.getPropertyValue("--accent-hue")).toBe("258");
    expect(root.style.getPropertyValue("--accent-chroma")).toBe("0.220");
    expect(root.style.getPropertyValue("--accent-2-hue")).toBe("320");
    expect(root.style.getPropertyValue("--accent-3-chroma")).toBe("0.140");
    expect(root.style.getPropertyValue("--success-hue")).toBe("150");
    expect(root.style.getPropertyValue("--warning-chroma")).toBe("0.160");
  });

  it("returns the applied palette definition", () => {
    const result = applyPalette(root, "ember");
    expect(result).toBe(themePalettes.ember);
    expect(result.key).toBe("ember");
    expect(result.label).toBe("Ember");
  });

  it("overwrites a previously applied palette", () => {
    applyPalette(root, "aurora");
    applyPalette(root, "verdant");
    expect(root.dataset.palette).toBe("verdant");
    expect(root.style.getPropertyValue("--accent-hue")).toBe("150");
  });
});

describe("applyContrast", () => {
  it("sets data-contrast to standard", () => {
    const root = document.createElement("div");
    applyContrast(root, "standard");
    expect(root.dataset.contrast).toBe("standard");
    expect(root.getAttribute("data-contrast")).toBe("standard");
  });

  it("sets data-contrast to high", () => {
    const root = document.createElement("div");
    applyContrast(root, "high");
    expect(root.dataset.contrast).toBe("high");
  });

  it("overwrites a previously applied contrast", () => {
    const root = document.createElement("div");
    applyContrast(root, "high");
    applyContrast(root, "standard");
    expect(root.dataset.contrast).toBe("standard");
  });
});

describe("persistAppearance", () => {
  it("writes all three preferences under their storage keys", () => {
    persistAppearance("dark", "ember", "high");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBe("ember");
    expect(localStorage.getItem(CONTRAST_STORAGE_KEY)).toBe("high");
  });

  it("round-trips through the getStored* readers", () => {
    persistAppearance("light", "verdant", "high");
    expect(getStoredThemeMode()).toBe("light");
    expect(getStoredThemePalette()).toBe("verdant");
    expect(getStoredThemeContrast()).toBe("high");
  });

  it("overwrites earlier persisted values", () => {
    persistAppearance("dark", "aurora", "high");
    persistAppearance("system", "lagoon", "standard");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
    expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBe("lagoon");
    expect(localStorage.getItem(CONTRAST_STORAGE_KEY)).toBe("standard");
  });
});

describe("getPalettePreview", () => {
  it("builds a 135deg linear-gradient", () => {
    const preview = getPalettePreview("lagoon");
    expect(preview.startsWith("linear-gradient(135deg")).toBe(true);
  });

  it("embeds the three accent oklch stops for lagoon", () => {
    const preview = getPalettePreview("lagoon");
    expect(preview).toContain("oklch(0.72 0.190 225)");
    expect(preview).toContain("oklch(0.76 0.130 186)");
    expect(preview).toContain("oklch(0.78 0.120 285)");
  });

  it("embeds the three accent oklch stops for aurora", () => {
    const preview = getPalettePreview("aurora");
    expect(preview).toContain("oklch(0.72 0.220 258)");
    expect(preview).toContain("oklch(0.76 0.180 320)");
    expect(preview).toContain("oklch(0.78 0.140 198)");
  });

  it("produces distinct gradients for distinct palettes", () => {
    expect(getPalettePreview("ember")).not.toBe(getPalettePreview("verdant"));
  });
});

describe("no-DOM fallbacks (canUseDom() === false)", () => {
  it("getStored* readers return defaults when window is undefined", () => {
    vi.stubGlobal("window", undefined);
    expect(getStoredThemeMode()).toBe(DEFAULT_THEME_MODE);
    expect(getStoredThemePalette()).toBe(DEFAULT_THEME_PALETTE);
    expect(getStoredThemeContrast()).toBe(DEFAULT_THEME_CONTRAST);
  });

  it("persistAppearance is a no-op when window is undefined", () => {
    vi.stubGlobal("window", undefined);
    expect(() => persistAppearance("dark", "ember", "high")).not.toThrow();
  });
});
