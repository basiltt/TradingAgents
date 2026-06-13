import * as React from "react";

/**
 * localStorage-backed tab state. Mirrors the backtest tab-persistence behavior:
 * read the stored id once on mount (fall back to `fallback ?? order[0]` when it is
 * missing OR not in `order`); `setTab(next)` updates state AND writes localStorage
 * in the SAME call — interaction-driven, never a mount-time write. Best-effort: any
 * storage read/write failure degrades to the fallback / a no-op and never throws.
 *
 * The setter may also be called imperatively to FORCE a tab (e.g. the dialog forcing
 * "schedule" on open-for-create, or the results view auto-switching on completion);
 * those calls persist too, which is intended.
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
