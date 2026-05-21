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

export interface NeuUiState {
  mode: NeuSurfaceMode;
  accent: NeuAccentPalette;
  contrast: NeuContrastMode;
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  commandPaletteOpen: boolean;
  dockExpanded: boolean;
}

export const initialNeuUiState: NeuUiState = {
  mode: DEFAULT_NEU_MODE,
  accent: DEFAULT_NEU_ACCENT,
  contrast: DEFAULT_NEU_CONTRAST,
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
