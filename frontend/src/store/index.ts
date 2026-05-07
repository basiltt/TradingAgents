import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { analysisSlice } from "./analysis-slice";
import { uiSlice } from "./ui-slice";
import accountsReducer from "./accounts-slice";

export const store = configureStore({
  reducer: {
    analysis: analysisSlice.reducer,
    ui: uiSlice.reducer,
    accounts: accountsReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
