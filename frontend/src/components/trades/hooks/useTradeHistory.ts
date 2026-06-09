import { useInfiniteQuery } from "@tanstack/react-query";
import { tradesApi } from "@/api/client";
import { tradeQueryKeys } from "@/components/trades/queryKeys";
import { TERMINAL_STATUSES } from "@/components/trades/types";
import type { TradeFilters } from "@/components/trades/types";

function filtersToParams(filters: TradeFilters) {
  const params: Record<string, string | string[]> = {};
  if (filters.account_ids.length) params.account_id = filters.account_ids;
  if (filters.symbol) params.symbol = filters.symbol;
  if (filters.side) params.side = filters.side;
  if (filters.from_date) params.from_date = filters.from_date;
  if (filters.to_date) params.to_date = filters.to_date;
  return params;
}

export function useTradeHistory(filters: TradeFilters, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: tradeQueryKeys.historyList(filters),
    queryFn: ({ pageParam }) =>
      tradesApi.list({
        ...filtersToParams(filters),
        status: [...TERMINAL_STATUSES],
        cursor: pageParam,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.cursor ?? undefined) : undefined,
    initialPageParam: undefined as string | undefined,
    enabled,
    staleTime: 30_000,
  });
}
