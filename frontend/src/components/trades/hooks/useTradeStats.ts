import { useQuery } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";

export function useTradeStats(accountIds: string[] = []) {
  return useQuery({
    queryKey: ["trades", "stats", [...accountIds].sort()],
    queryFn: () => tradesApi.getStats(accountIds),
    staleTime: 10_000,
  });
}
