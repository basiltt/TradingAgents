import { useState, useCallback } from "react";
import { accountsApi, type TradingAccount } from "@/api/client";
import { FleetCohortView, type Cohort } from "./FleetCohortView";

/**
 * Collapsible "Fleet Cohorts" panel mounted on the accounts dashboard (TASK-5.3).
 * Lazy-loads the account roster on expand and delegates bulk assignment to
 * accountsApi.update per id, tolerating partial failure (one bad PATCH does not
 * abort the rest). Refetches after a successful batch so the roster reflects reality.
 */
export function FleetCohortPanel() {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<TradingAccount[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await accountsApi.list();
      setAccounts(list);
      setLoaded(true);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !loaded) void load();
  }

  // Returns the number of successful assignments so the child only clears its
  // selection when at least one PATCH succeeded (lets the user retry a total failure).
  const onAssign = useCallback(async (ids: string[], cohort: Cohort): Promise<number> => {
    const results = await Promise.allSettled(
      ids.map((id) => accountsApi.update(id, { strategy_cohort: cohort })),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    const ok = ids.length - failed;
    setNote(
      failed
        ? `Assigned ${ok}/${ids.length}; ${failed} failed.`
        : `Assigned ${ids.length} account(s) to ${cohort.replace("_", "-")}.`,
    );
    if (ok > 0) await load(); // refresh roster only if something actually changed
    return ok;
  }, [load]);

  return (
    <div className="rounded-xl border border-border/60 bg-muted/20" data-testid="fleet-cohort-panel">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="fleet-cohort-body"
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium"
        data-testid="fleet-cohort-toggle"
      >
        <span>Fleet Cohorts (F3 — decorrelate strategy across accounts)</span>
        <span className="text-muted-foreground">{open ? "▲" : "▼"}</span>
      </button>
      {open ? (
        <div id="fleet-cohort-body" className="px-4 pb-4">
          {note ? <div className="mb-2 text-xs text-muted-foreground" data-testid="fleet-note">{note}</div> : null}
          {loadError ? (
            <div className="text-sm text-red-400 py-3 flex items-center gap-3" data-testid="fleet-load-error">
              Failed to load the fleet.
              <button type="button" onClick={() => void load()} className="px-2 py-1 rounded border border-border hover:bg-muted/50 text-foreground">
                Retry
              </button>
            </div>
          ) : loaded ? (
            <FleetCohortView accounts={accounts} onAssign={onAssign} />
          ) : (
            <div className="text-sm text-muted-foreground py-4">Loading fleet…</div>
          )}
        </div>
      ) : null}
    </div>
  );
}
