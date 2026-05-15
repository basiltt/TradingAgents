import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";
import { API_ACTIVE_STATUSES } from "@/components/trades/types";
import type { Trade } from "@/components/trades/types";
import { store, useAppDispatch } from "@/store";
import { setActiveTrades, setIsFetchingActiveTrades } from "@/store/trades-slice";

export async function fetchAllActiveTrades(
  dispatch: ReturnType<typeof useAppDispatch>,
) {
  dispatch(setIsFetchingActiveTrades(true));
  try {
    const allTrades: Trade[] = [];
    let cursor: string | undefined;
    let pages = 0;
    const maxPages = 20;

    do {
      const page = await tradesApi.list({
        status: [...API_ACTIVE_STATUSES],
        limit: 100,
        cursor,
      });
      allTrades.push(...page.items);
      cursor = page.has_more ? (page.cursor ?? undefined) : undefined;
      pages++;
    } while (cursor && pages < maxPages);

    dispatch(setActiveTrades(allTrades));
  } finally {
    dispatch(setIsFetchingActiveTrades(false));
  }
}

function detectChanges(remote: Trade[], local: Trade[]): boolean {
  if (remote.length !== Math.min(local.length, 50)) return true;
  for (let i = 0; i < Math.min(5, remote.length); i++) {
    const localTrade = local.find((t) => t.id === remote[i].id);
    if (!localTrade || localTrade.version !== remote[i].version) return true;
  }
  return false;
}

export function useTradePolling(enabled: boolean) {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    const interval = setInterval(async () => {
      try {
        const page1 = await tradesApi.list({
          status: [...API_ACTIVE_STATUSES],
          limit: 50,
        });
        const localTrades = Object.values(store.getState().trades.activeTrades);
        if (detectChanges(page1.items, localTrades)) {
          await fetchAllActiveTrades(dispatch);
        }
      } catch {
        // polling failure is non-fatal
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [enabled, dispatch]);

  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === "visible") {
        fetchAllActiveTrades(dispatch);
        queryClient.invalidateQueries({ queryKey: ["trades"] });
      }
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [dispatch, queryClient]);
}
