import { useQuery, useInfiniteQuery } from "@tanstack/react-query";
import { performanceApi, signalAnalyticsApi } from "@/api/client";

export const performanceKeys = {
  overview: (scope: string, timeframe: string) =>
    ["performance-overview", scope, timeframe] as const,
  breakdown: (scope: string, timeframe: string) =>
    ["performance-breakdown", scope, timeframe] as const,
  trades: (scope: string, timeframe: string, sort: string, dir: string) =>
    ["performance-trades", scope, timeframe, sort, dir] as const,
  signalSummary: (scope: string) => ["performance-signals", "summary", scope] as const,
  signalWinRate: (scope: string) => ["performance-signals", "win-rate", scope] as const,
  live: (scope: string) => ["performance-live", scope] as const,
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
  sort: string, dir: string,
) {
  return useInfiniteQuery({
    queryKey: performanceKeys.trades(scope, timeframe, sort, dir),
    queryFn: ({ pageParam, signal }) =>
      performanceApi.getTradesPage(
        scope, timeframe, { sort, dir, cursor: pageParam ?? undefined, limit: 50 }, signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.has_more ? last.cursor ?? undefined : undefined),
    staleTime: 60_000,
  });
}

export function useSignalSummary(scope: string) {
  return useQuery({
    queryKey: performanceKeys.signalSummary(scope),
    queryFn: ({ signal }) => signalAnalyticsApi.summary(scope, signal),
    staleTime: 60_000,
  });
}

export function useSignalWinRate(scope: string) {
  return useQuery({
    queryKey: performanceKeys.signalWinRate(scope),
    queryFn: ({ signal }) => signalAnalyticsApi.winRate(scope, signal),
    staleTime: 60_000,
  });
}

export function usePerformanceLive(scope: string, enabled = true) {
  return useQuery({
    queryKey: performanceKeys.live(scope),
    queryFn: ({ signal }) => performanceApi.getLive(scope, signal),
    enabled,
    staleTime: 0,
    refetchInterval: 15_000, // poll while mounted; key is excluded from persistence (App.tsx)
  });
}
