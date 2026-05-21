import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import {
  getStoredThemeContrast,
  getStoredThemeMode,
  getStoredThemePalette,
  type ThemeContrast,
  type ThemeMode,
  type ThemePalette,
} from "@/lib/theme";

interface UiState {
  sidebarOpen: boolean;
  theme: ThemeMode;
  palette: ThemePalette;
  contrast: ThemeContrast;
}

const initialState: UiState = {
  sidebarOpen: false,
  theme: getStoredThemeMode(),
  palette: getStoredThemePalette(),
  contrast: getStoredThemeContrast(),
};

export const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    toggleSidebar(state) {
      state.sidebarOpen = !state.sidebarOpen;
    },
    setSidebarOpen(state, action: PayloadAction<boolean>) {
      state.sidebarOpen = action.payload;
    },
    setTheme(state, action: PayloadAction<ThemeMode>) {
      state.theme = action.payload;
    },
    setPalette(state, action: PayloadAction<ThemePalette>) {
      state.palette = action.payload;
    },
    setContrast(state, action: PayloadAction<ThemeContrast>) {
      state.contrast = action.payload;
    },
  },
});

export const { toggleSidebar, setSidebarOpen, setTheme, setPalette, setContrast } = uiSlice.actions;
