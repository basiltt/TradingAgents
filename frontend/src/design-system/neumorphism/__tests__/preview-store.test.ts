import { describe, expect, it } from "vitest";
import { createNeuPreviewStore } from "../state/preview-store";
import {
  setCommandPaletteOpen,
  setNeuAccent,
  setNeuContrast,
  setNeuMode,
} from "../state/neu-ui-slice";

describe("neumorphism preview store", () => {
  it("updates appearance and shell state through the isolated slice", () => {
    const store = createNeuPreviewStore();

    store.dispatch(setNeuMode("graphite"));
    store.dispatch(setNeuAccent("rose"));
    store.dispatch(setNeuContrast("high"));
    store.dispatch(setCommandPaletteOpen(true));

    expect(store.getState().neuUi).toMatchObject({
      mode: "graphite",
      accent: "rose",
      contrast: "high",
      commandPaletteOpen: true,
    });
  });
});
