import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { neuUiSlice } from "@/design-system/neumorphism";
import { analysisSlice } from "./analysis-slice";
import { uiSlice } from "./ui-slice";
import accountsReducer from "./accounts-slice";
import strategiesReducer from "./strategies-slice";
import tradesReducer from "./trades-slice";
import aiManagerReducer from "./ai-manager-slice";

export const store = configureStore({
  reducer: {
    analysis: analysisSlice.reducer,
    neuUi: neuUiSlice.reducer,
    ui: uiSlice.reducer,
    accounts: accountsReducer,
    strategies: strategiesReducer,
    trades: tradesReducer,
    aiManager: aiManagerReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
