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

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(false);
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
