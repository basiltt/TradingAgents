import * as React from "react";

/**
 * localStorage-backed tab state. Shares the backtest form's tab-persistence
 * CONTRACT — read the stored id once on mount (fall back to `fallback ?? order[0]`
 * when it is missing OR not in `order`); `setTab(next)` updates state AND writes
 * localStorage in the SAME call (interaction-driven, never a mount-time write);
 * best-effort, so any storage read/write failure degrades to the fallback / a no-op
 * and never throws. It does NOT share the backtest form's storage SHAPE: the backtest
 * form stashes its active tab inside the larger `tradingagents_backtest_draft` blob via
 * an RHF subscription, whereas this hook uses a dedicated key per surface.
 *
 * The setter may also be called imperatively to FORCE a tab (e.g. the dialog forcing
 * "schedule" on open-for-create, or the results view auto-switching on completion);
 * those calls persist too, which is intended.
 *
 * IMPORTANT: `storageKey` MUST be a constant string literal for the lifetime of a
 * mounted instance. The mount read is intentionally memoized with an empty dep array,
 * so a changing key would freeze the read to the first key while writes go to the new
 * one — caller-side bug. All current callers pass module-level literals.
 */
export function useTabPersistence<T extends string>(
  storageKey: string,
  order: readonly T[],
  fallback?: T,
): [T, (next: T) => void] {
  const initial = React.useMemo<T>(() => {
    const fb = fallback ?? order[0];
    try {
      const stored = localStorage.getItem(storageKey);
      return stored && (order as readonly string[]).includes(stored) ? (stored as T) : fb;
    } catch {
      return fb;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time read only
  }, []);

  const [tab, setTab] = React.useState<T>(initial);

  const setAndPersist = React.useCallback(
    (next: T) => {
      setTab(next);
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        /* storage unavailable — best-effort, ignore */
      }
    },
    [storageKey],
  );

  return [tab, setAndPersist];
}
