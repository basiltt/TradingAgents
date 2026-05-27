/**
 * @module ui-slice
 *
 * Redux slice that owns all transient UI state for the TradingAgents dashboard.
 *
 * Responsibilities:
 * - Sidebar open/close state (persisted only in memory; layout re-reads on mount)
 * - Active theme mode (light / dark / system), palette, and contrast level
 *
 * Theme fields are initialised from localStorage via the helper functions in
 * `@/lib/theme` so that the user's last selection survives a page refresh.
 * Persistence back to localStorage is handled by the calling code (e.g. a
 * ThemeProvider effect), NOT by this slice — the slice is the single source of
 * truth for the *current* value, not the storage layer.
 *
 * @example
 * // Reading state
 * const theme = useAppSelector((s) => s.ui.theme);
 *
 * // Dispatching actions
 * dispatch(setTheme("dark"));
 * dispatch(toggleSidebar());
 */

import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import {
  getStoredThemeContrast,
  getStoredThemeMode,
  getStoredThemePalette,
  type ThemeContrast,
  type ThemeMode,
  type ThemePalette,
} from "@/lib/theme";

/**
 * Shape of the UI slice state tree.
 *
 * All fields are kept flat (no nested objects) so that individual selectors
 * only re-render when the specific field they depend on changes.
 */
interface UiState {
  /** Whether the main navigation sidebar is currently open. */
  sidebarOpen: boolean;

  /**
   * Active colour-scheme mode.
   * Mirrors `ThemeMode` from `@/lib/theme` — one of `"light"`, `"dark"`, or
   * `"system"`.
   */
  theme: ThemeMode;

  /**
   * Active colour palette (accent/brand colour family).
   * Mirrors `ThemePalette` from `@/lib/theme`.
   */
  palette: ThemePalette;

  /**
   * Active contrast level for accessibility (e.g. `"normal"` or `"high"`).
   * Mirrors `ThemeContrast` from `@/lib/theme`.
   */
  contrast: ThemeContrast;
}

// AI-CONTEXT: Initial state reads from localStorage so the UI matches the
// user's previous session on first render, avoiding a flash of the default
// theme.  The getter functions each return a safe fallback value when
// localStorage is unavailable (e.g. SSR or private-browsing mode).
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
    /**
     * Toggle the sidebar between open and closed.
     *
     * Use this for hamburger/close button clicks where the new state is
     * the opposite of the current state.
     */
    toggleSidebar(state) {
      state.sidebarOpen = !state.sidebarOpen;
    },

    /**
     * Explicitly set the sidebar open/closed state.
     *
     * Prefer this over `toggleSidebar` when you know the desired state (e.g.
     * closing the sidebar on a route change or on mobile overlay click).
     *
     * @param action - Payload is `true` to open, `false` to close.
     */
    setSidebarOpen(state, action: PayloadAction<boolean>) {
      state.sidebarOpen = action.payload;
    },

    /**
     * Change the active theme mode.
     *
     * Callers are responsible for persisting the new value to localStorage if
     * desired (this slice does not write to storage).
     *
     * @param action - The new `ThemeMode` value (`"light"`, `"dark"`, or
     *   `"system"`).
     */
    setTheme(state, action: PayloadAction<ThemeMode>) {
      state.theme = action.payload;
    },

    /**
     * Change the active colour palette.
     *
     * Callers are responsible for persisting the new value to localStorage if
     * desired.
     *
     * @param action - The new `ThemePalette` identifier.
     */
    setPalette(state, action: PayloadAction<ThemePalette>) {
      state.palette = action.payload;
    },

    /**
     * Change the active contrast level.
     *
     * Callers are responsible for persisting the new value to localStorage if
     * desired.
     *
     * @param action - The new `ThemeContrast` value (e.g. `"normal"` or
     *   `"high"`).
     */
    setContrast(state, action: PayloadAction<ThemeContrast>) {
      state.contrast = action.payload;
    },
  },
});

/**
 * Exported action creators for the UI slice.
 *
 * - `toggleSidebar` — flip sidebar visibility
 * - `setSidebarOpen` — set sidebar visibility explicitly
 * - `setTheme`   — update the colour-scheme mode
 * - `setPalette` — update the colour palette
 * - `setContrast` — update the contrast level
 */
export const { toggleSidebar, setSidebarOpen, setTheme, setPalette, setContrast } = uiSlice.actions;
