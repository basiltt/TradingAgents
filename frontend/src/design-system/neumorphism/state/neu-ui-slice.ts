import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import {
  DEFAULT_NEU_ACCENT,
  DEFAULT_NEU_CONTRAST,
  DEFAULT_NEU_MODE,
} from "../theme";
import type {
  NeuAccentPalette,
  NeuContrastMode,
  NeuSurfaceMode,
} from "../types";

export const NEU_MODE_STORAGE_KEY = "tradingagents-neu-mode";
export const NEU_ACCENT_STORAGE_KEY = "tradingagents-neu-accent";
export const NEU_CONTRAST_STORAGE_KEY = "tradingagents-neu-contrast";

export interface NeuUiState {
  mode: NeuSurfaceMode;
  accent: NeuAccentPalette;
  contrast: NeuContrastMode;
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  commandPaletteOpen: boolean;
  dockExpanded: boolean;
}

function canUseDom() {
  return typeof window !== "undefined";
}

function isNeuMode(value: unknown): value is NeuSurfaceMode {
  return value === "ivory" || value === "graphite";
}

function isNeuAccent(value: unknown): value is NeuAccentPalette {
  return value === "cobalt" || value === "sage" || value === "amber" || value === "rose";
}

function isNeuContrast(value: unknown): value is NeuContrastMode {
  return value === "balanced" || value === "high";
}

export function readStoredNeuMode() {
  if (!canUseDom()) return DEFAULT_NEU_MODE;
  const value = window.localStorage.getItem(NEU_MODE_STORAGE_KEY);
  return isNeuMode(value) ? value : DEFAULT_NEU_MODE;
}

export function readStoredNeuAccent() {
  if (!canUseDom()) return DEFAULT_NEU_ACCENT;
  const value = window.localStorage.getItem(NEU_ACCENT_STORAGE_KEY);
  return isNeuAccent(value) ? value : DEFAULT_NEU_ACCENT;
}

export function readStoredNeuContrast() {
  if (!canUseDom()) return DEFAULT_NEU_CONTRAST;
  const value = window.localStorage.getItem(NEU_CONTRAST_STORAGE_KEY);
  return isNeuContrast(value) ? value : DEFAULT_NEU_CONTRAST;
}

export function persistNeuAppearance({
  mode,
  accent,
  contrast,
}: Pick<NeuUiState, "mode" | "accent" | "contrast">) {
  if (!canUseDom()) return;
  window.localStorage.setItem(NEU_MODE_STORAGE_KEY, mode);
  window.localStorage.setItem(NEU_ACCENT_STORAGE_KEY, accent);
  window.localStorage.setItem(NEU_CONTRAST_STORAGE_KEY, contrast);
}

export const initialNeuUiState: NeuUiState = {
  mode: readStoredNeuMode(),
  accent: readStoredNeuAccent(),
  contrast: readStoredNeuContrast(),
  sidebarCollapsed: false,
  mobileNavOpen: false,
  commandPaletteOpen: false,
  dockExpanded: false,
};

export const neuUiSlice = createSlice({
  name: "neuUi",
  initialState: initialNeuUiState,
  reducers: {
    setNeuMode(state, action: PayloadAction<NeuSurfaceMode>) {
      state.mode = action.payload;
    },
    setNeuAccent(state, action: PayloadAction<NeuAccentPalette>) {
      state.accent = action.payload;
    },
    setNeuContrast(state, action: PayloadAction<NeuContrastMode>) {
      state.contrast = action.payload;
    },
    setSidebarCollapsed(state, action: PayloadAction<boolean>) {
      state.sidebarCollapsed = action.payload;
    },
    toggleSidebarCollapsed(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed;
    },
    setMobileNavOpen(state, action: PayloadAction<boolean>) {
      state.mobileNavOpen = action.payload;
    },
    setCommandPaletteOpen(state, action: PayloadAction<boolean>) {
      state.commandPaletteOpen = action.payload;
    },
    setDockExpanded(state, action: PayloadAction<boolean>) {
      state.dockExpanded = action.payload;
    },
    resetNeuUiState() {
      return initialNeuUiState;
    },
  },
});

export const {
  resetNeuUiState,
  setCommandPaletteOpen,
  setDockExpanded,
  setMobileNavOpen,
  setNeuAccent,
  setNeuContrast,
  setNeuMode,
  setSidebarCollapsed,
  toggleSidebarCollapsed,
} = neuUiSlice.actions;
