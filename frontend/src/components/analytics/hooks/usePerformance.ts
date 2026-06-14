import { useQuery } from "@tanstack/react-query";
import { performanceApi } from "@/api/client";

export const performanceKeys = {
  overview: (scope: string, timeframe: string) =>
    ["performance-overview", scope, timeframe] as const,
};

export function usePerformanceOverview(scope: string, timeframe: string) {
  return useQuery({
    queryKey: performanceKeys.overview(scope, timeframe),
    queryFn: ({ signal }) => performanceApi.getOverview(scope, timeframe, signal),
    staleTime: 60_000, // historical: 60s
  });
}
