import { useEffect } from "react";
import { tradesApi } from "@/api/client";
import { API_ACTIVE_STATUSES } from "@/components/trades/types";
import type { Trade } from "@/components/trades/types";
import { store, useAppDispatch } from "@/store";
import { setActiveTrades, setIsFetchingActiveTrades } from "@/store/trades-slice";

/**
 * Fetches every active trade by paginating the trades API (up to 20 pages of 100)
 * and writes the full list into the Redux store, toggling the fetching flag around it.
 * @param dispatch - The app dispatch used to update the trades slice.
 * @returns A promise that resolves once all pages are loaded and dispatched.
 */
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

/**
 * Keeps the active-trades store fresh while mounted. Polls the first page every
 * 60s and triggers a full refetch only when a cheap diff detects changes, and
 * refetches immediately when the tab becomes visible again.
 * @param enabled - When false, the polling interval is skipped (visibility refetch still runs).
 * @returns Nothing; manages two effects and clears the interval/listener on cleanup.
 */
export function useTradePolling(enabled: boolean) {
  const dispatch = useAppDispatch();

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
        fetchAllActiveTrades(dispatch).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [dispatch]);
}
