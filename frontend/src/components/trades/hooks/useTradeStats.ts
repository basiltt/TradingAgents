import { useQuery } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";
import { tradeQueryKeys } from "@/components/trades/queryKeys";

export function useTradeStats(accountIds: string[] = []) {
  return useQuery({
    queryKey: tradeQueryKeys.statsFor(accountIds),
    queryFn: () => tradesApi.getStats(accountIds),
    staleTime: 10_000,
  });
}
