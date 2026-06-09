import { useEffect, useState } from "react";
import { tradesApi } from "@/api/client";
import type { StrategyDirectionStats } from "../trades/types";
import { StrategyPnLView } from "../trades/StrategyPnLView";

/**
 * Account-detail "Strategy" tab (FR-052/AC-016). Fetches the per-strategy×direction
 * PnL breakdown for this account and renders it. Self-contained fetch (mirrors the
 * other detail panels) so it adds a tab without touching the parent's data flow.
 * All state writes are guarded on the AbortController signal so a superseded fetch
 * (rapid accountId change / unmount) cannot clobber the in-flight request's state.
 */
export function StrategyTab({ accountId }: { accountId: string }) {
  const [rows, setRows] = useState<StrategyDirectionStats[] | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // AI-CONTEXT: Reset to the loading state when the account changes using React's
  // "adjust state during render when a prop changes" pattern, NOT a synchronous
  // setState in the effect body (which trips react-hooks/set-state-in-effect). The
  // effect below only performs the fetch and writes state from async callbacks
  // (microtask-deferred, so not flagged). Tracking the previous accountId ensures
  // the spinner shows immediately on switch, before the new request resolves.
  const [seenAccountId, setSeenAccountId] = useState(accountId);
  if (accountId !== seenAccountId) {
    setSeenAccountId(accountId);
    setRows(undefined);
    setLoading(true);
    setError(false);
  }

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await tradesApi.getStats([accountId], true, ctrl.signal);
        if (!ctrl.signal.aborted) setRows(res.by_strategy ?? []);
      } catch {
        if (!ctrl.signal.aborted) {
          setRows(undefined);
          setError(true);
        }
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [accountId]);

  if (error) {
    return (
      <div className="py-6 text-center text-sm text-red-400" data-testid="strategy-tab-error">
        Failed to load the strategy breakdown.
      </div>
    );
  }

  return (
    <div className="py-2">
      <StrategyPnLView rows={rows} loading={loading} />
    </div>
  );
}
