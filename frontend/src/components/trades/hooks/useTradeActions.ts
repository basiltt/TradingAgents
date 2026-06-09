import { useQueryClient } from "@tanstack/react-query";
import { useAppDispatch } from "@/store";
import { tradesApi, accountsApi } from "@/api/client";
import { tradeQueryKeys } from "@/components/trades/queryKeys";
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
      if (!qty) {
        dispatch(removeActiveTrade(tradeId));
      }
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.history() });
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.stats() });
      if (qty) {
        queryClient.invalidateQueries({ queryKey: tradeQueryKeys.active() });
      }
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
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.history() });
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.stats() });
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
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.history() });
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.stats() });
      return result;
    } catch (error) {
      queryClient.invalidateQueries({ queryKey: tradeQueryKeys.active() });
      throw error;
    } finally {
      dispatch(setPendingCloseAll({ account_id: accountId, pending: false }));
    }
  };

  return { closeTrade, cancelTrade, closeAll };
}
