import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { analysisSlice } from "./analysis-slice";
import { uiSlice } from "./ui-slice";
import accountsReducer from "./accounts-slice";
import strategiesReducer from "./strategies-slice";
import tradesReducer from "./trades-slice";

export const store = configureStore({
  reducer: {
    analysis: analysisSlice.reducer,
    ui: uiSlice.reducer,
    accounts: accountsReducer,
    strategies: strategiesReducer,
    trades: tradesReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
