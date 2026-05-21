import type { NeuPreviewState } from "./preview-store";

export const selectNeuAppearance = (state: NeuPreviewState) => state.neuUi;
export const selectNeuShellState = (state: NeuPreviewState) => ({
  sidebarCollapsed: state.neuUi.sidebarCollapsed,
  mobileNavOpen: state.neuUi.mobileNavOpen,
  commandPaletteOpen: state.neuUi.commandPaletteOpen,
  dockExpanded: state.neuUi.dockExpanded,
});
