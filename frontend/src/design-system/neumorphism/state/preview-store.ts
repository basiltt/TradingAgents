import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { neuUiSlice } from "./neu-ui-slice";

export function createNeuPreviewStore() {
  return configureStore({
    reducer: {
      neuUi: neuUiSlice.reducer,
    },
  });
}

export type NeuPreviewStore = ReturnType<typeof createNeuPreviewStore>;
export type NeuPreviewState = ReturnType<NeuPreviewStore["getState"]>;
export type NeuPreviewDispatch = NeuPreviewStore["dispatch"];

export const useNeuPreviewDispatch = useDispatch.withTypes<NeuPreviewDispatch>();
export const useNeuPreviewSelector = useSelector.withTypes<NeuPreviewState>();
