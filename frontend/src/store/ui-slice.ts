import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import {
  getStoredThemeMode,
  getStoredThemePalette,
  type ThemeMode,
  type ThemePalette,
} from "@/lib/theme";

interface UiState {
  sidebarOpen: boolean;
  theme: ThemeMode;
  palette: ThemePalette;
}

const initialState: UiState = {
  sidebarOpen: false,
  theme: getStoredThemeMode(),
  palette: getStoredThemePalette(),
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
  },
});

export const { toggleSidebar, setSidebarOpen, setTheme, setPalette } = uiSlice.actions;
