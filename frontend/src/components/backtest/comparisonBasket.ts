/**
 * Comparison basket — a small sessionStorage-backed set of run ids the user has
 * marked for side-by-side comparison. Kept framework-free so the storage logic
 * is testable; components subscribe via the useComparisonBasket hook.
 */
const STORAGE_KEY = "backtest_comparison_basket";
/** The maximum number of runs that can be compared at once. Single source of
 * truth — the list-page selection cap and the compare-page cap derive from this.
 * NOTE: EquityOverlayChart.OVERLAY_COLORS must have at least this many entries
 * (it currently has exactly 4); if you raise this, extend that palette too. */
export const MAX_COMPARE_RUNS = 4;
export const MAX_BASKET = MAX_COMPARE_RUNS;

function read(): string[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    /* storage may be unavailable (private mode / quota) — basket is best-effort */
  }
}

export function getBasket(): string[] {
  return read();
}

/** Add an id (no-op if already present or basket full). Returns the new basket. */
export function addToBasket(id: string): string[] {
  const cur = read();
  if (cur.includes(id) || cur.length >= MAX_BASKET) return cur;
  const next = [...cur, id];
  write(next);
  return next;
}

export function removeFromBasket(id: string): string[] {
  const next = read().filter((x) => x !== id);
  write(next);
  return next;
}

export function clearBasket(): void {
  write([]);
}

export function isInBasket(id: string): boolean {
  return read().includes(id);
}
