import { useQuery } from "@tanstack/react-query";
import { backtestApi } from "@/api/client";
import { isActiveStatus, type BacktestRun } from "@/components/backtest/types";

/** How often to poll a running backtest (ms). */
export const BACKTEST_POLL_INTERVAL_MS = 2000;

/**
 * Polls a single backtest run via TanStack Query.
 *
 * While the run is pending/running, refetches every 2s. Once the run reaches a
 * terminal status (completed/failed/cancelled) — OR an unrecognized status —
 * polling stops (refetchInterval returns false). Returns the standard query
 * result so callers can read `data`, `isLoading`, `error`, and `refetch`.
 *
 * @param runId The run to poll. When undefined, the query is disabled.
 */
export function useBacktestPolling(runId: string | undefined) {
  return useQuery<BacktestRun>({
    queryKey: ["backtest", runId],
    queryFn: ({ signal }) => backtestApi.get(runId!, signal),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // No data yet → keep polling. Only pending/running stay active; any other
      // value (terminal OR unknown) stops polling to avoid an infinite loop.
      if (status === undefined) return BACKTEST_POLL_INTERVAL_MS;
      return isActiveStatus(status) ? BACKTEST_POLL_INTERVAL_MS : false;
    },
    // Always refetch on mount so a navigated-back-to run shows fresh state.
    refetchOnWindowFocus: false,
  });
}
