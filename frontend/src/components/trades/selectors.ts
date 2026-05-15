import { createSelector } from "@reduxjs/toolkit";
import type { RootState } from "@/store";

export const selectActiveTrades = (state: RootState) => state.trades.activeTrades;

export const selectActiveTradesList = createSelector(
  [selectActiveTrades],
  (activeTrades) => Object.values(activeTrades),
);

export const selectActiveTradeAggregates = createSelector(
  [selectActiveTrades],
  (activeTrades) => {
    const trades = Object.values(activeTrades);
    let totalRealizedPnl = 0;
    const tradeCount = trades.length;

    for (const trade of trades) {
      if (trade.realized_pnl != null) {
        totalRealizedPnl += trade.realized_pnl;
      }
    }

    return {
      tradeCount,
      totalPnl: totalRealizedPnl,
      totalUnrealizedPnl: 0,
      totalRealizedPnl,
    };
  },
);

export const selectLastUpdated = (state: RootState) => state.trades.lastUpdated;
