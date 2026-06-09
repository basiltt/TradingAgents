import { useQuery } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";
import { tradeQueryKeys } from "@/components/trades/queryKeys";

/** Trade audit events are immutable once written; cache them for a minute. */
const TRADE_EVENTS_STALE_MS = 60_000;

export function useTradeEvents(accountId: string, tradeId: string, enabled: boolean) {
  return useQuery({
    queryKey: tradeQueryKeys.events(tradeId),
    queryFn: () => tradesApi.getEvents(accountId, tradeId),
    enabled,
    staleTime: TRADE_EVENTS_STALE_MS,
  });
}
