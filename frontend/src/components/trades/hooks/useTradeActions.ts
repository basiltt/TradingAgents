import { useQueryClient } from "@tanstack/react-query";
import { useAppDispatch } from "@/store";
import { tradesApi, accountsApi } from "@/api/client";
import {
  startPendingAction,
  removeActiveTrade,
  clearPendingAction,
  revertOptimisticUpdate,
  setPendingCloseAll,
  removeActiveTradesByAccount,
} from "@/store/trades-slice";

export function useTradeActions() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const closeTrade = async (accountId: string, tradeId: string, qty?: number) => {
    dispatch(startPendingAction({ trade_id: tradeId, action: "closing" }));
    try {
      await tradesApi.close(accountId, tradeId, qty ? { qty } : undefined);
      dispatch(clearPendingAction(tradeId));
      dispatch(removeActiveTrade(tradeId));
      queryClient.invalidateQueries({ queryKey: ["trades", "history"] });
      queryClient.invalidateQueries({ queryKey: ["trades", "stats"] });
    } catch (error) {
      dispatch(revertOptimisticUpdate(tradeId));
      throw error;
    }
  };

  const cancelTrade = async (accountId: string, tradeId: string) => {
    dispatch(startPendingAction({ trade_id: tradeId, action: "cancelling" }));
    try {
      await tradesApi.cancel(accountId, tradeId);
      dispatch(clearPendingAction(tradeId));
      dispatch(removeActiveTrade(tradeId));
      queryClient.invalidateQueries({ queryKey: ["trades", "history"] });
      queryClient.invalidateQueries({ queryKey: ["trades", "stats"] });
    } catch (error) {
      dispatch(revertOptimisticUpdate(tradeId));
      throw error;
    }
  };

  const closeAll = async (accountId: string) => {
    dispatch(setPendingCloseAll({ account_id: accountId, pending: true }));
    try {
      const result = await accountsApi.closeAllPositions(accountId);
      dispatch(removeActiveTradesByAccount(accountId));
      queryClient.invalidateQueries({ queryKey: ["trades", "history"] });
      queryClient.invalidateQueries({ queryKey: ["trades", "stats"] });
      return result;
    } finally {
      dispatch(setPendingCloseAll({ account_id: accountId, pending: false }));
    }
  };

  return { closeTrade, cancelTrade, closeAll };
}
