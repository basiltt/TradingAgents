import { useQuery } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";

export function useTradeEvents(accountId: string, tradeId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["trades", "events", tradeId],
    queryFn: () => tradesApi.getEvents(accountId, tradeId),
    enabled,
    staleTime: 60_000,
  });
}
