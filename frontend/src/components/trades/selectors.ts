import { createSelector } from "@reduxjs/toolkit";
import type { RootState } from "@/store";

export const selectActiveTrades = (state: RootState) => state.trades.activeTrades;

export const selectActiveTradesList = createSelector(
  [selectActiveTrades],
  (activeTrades) => Object.values(activeTrades),
);

export const selectActiveTradeAggregates = createSelector(
  [selectActiveTradesList],
  (trades) => {
    let totalRealizedPnl = 0;
    for (const trade of trades) {
      if (trade.realized_pnl != null) {
        totalRealizedPnl += trade.realized_pnl;
      }
    }
    return {
      tradeCount: trades.length,
      totalPnl: totalRealizedPnl,
      totalRealizedPnl,
    };
  },
);

export const selectLastUpdated = (state: RootState) => state.trades.lastUpdated;
