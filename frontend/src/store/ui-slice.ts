import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

type Theme = "light" | "dark" | "system";

interface UiState {
  sidebarOpen: boolean;
  theme: Theme;
}

const initialState: UiState = {
  sidebarOpen: false,
  theme: "system",
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
    setTheme(state, action: PayloadAction<Theme>) {
      state.theme = action.payload;
    },
  },
});

export const { toggleSidebar, setSidebarOpen, setTheme } = uiSlice.actions;
