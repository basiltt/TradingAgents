import { useQuery } from "@tanstack/react-query";
import { performanceApi } from "@/api/client";

export const performanceKeys = {
  overview: (scope: string, timeframe: string) =>
    ["performance-overview", scope, timeframe] as const,
  breakdown: (scope: string, timeframe: string) =>
    ["performance-breakdown", scope, timeframe] as const,
  trades: (scope: string, timeframe: string, sort: string, dir: string) =>
    ["performance-trades", scope, timeframe, sort, dir] as const,
};

export function usePerformanceOverview(scope: string, timeframe: string) {
  return useQuery({
    queryKey: performanceKeys.overview(scope, timeframe),
    queryFn: ({ signal }) => performanceApi.getOverview(scope, timeframe, signal),
    staleTime: 60_000, // historical: 60s
  });
}

export function useTradesBreakdown(scope: string, timeframe: string) {
  return useQuery({
    queryKey: performanceKeys.breakdown(scope, timeframe),
    queryFn: ({ signal }) => performanceApi.getTradesBreakdown(scope, timeframe, signal),
    staleTime: 60_000,
  });
}

export function useTradesPage(
  scope: string, timeframe: string,
  sort: string, dir: string, cursor?: string,
) {
  return useQuery({
    queryKey: [...performanceKeys.trades(scope, timeframe, sort, dir), cursor ?? ""],
    queryFn: ({ signal }) =>
      performanceApi.getTradesPage(scope, timeframe, { sort, dir, cursor, limit: 50 }, signal),
    staleTime: 60_000,
  });
}
