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
    let totalUnrealizedPnl = 0;
    for (const trade of trades) {
      if (trade.realized_pnl != null) {
        totalRealizedPnl += trade.realized_pnl;
      }
      if (trade.unrealized_pnl != null) {
        totalUnrealizedPnl += trade.unrealized_pnl;
      }
    }
    const rounded = (v: number) => Math.round(v * 100) / 100;
    return {
      tradeCount: trades.length,
      totalRealizedPnl: rounded(totalRealizedPnl),
      totalUnrealizedPnl: rounded(totalUnrealizedPnl),
      totalPnl: rounded(totalRealizedPnl + totalUnrealizedPnl),
    };
  },
);

export const selectLastUpdated = (state: RootState) => state.trades.lastUpdated;
