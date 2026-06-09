/**
 * Backtest form draft — a localStorage-backed snapshot of the in-progress
 * BacktestConfigForm so a user's entries survive navigating away and back (or a
 * reload). Kept framework-free and separate from the component so the storage
 * logic is unit-testable, mirroring the existing analysis ConfigForm settings
 * persistence and the watchlists/comparisonBasket helpers.
 *
 * Stored as the form's raw (pre-validation) values. It is best-effort: any
 * read/parse/write failure (private mode, quota, corrupt JSON) degrades to "no
 * draft" rather than throwing — losing a draft must never break the form.
 */
import type { BacktestConfigFormValues } from "./configSchema";

const STORAGE_KEY = "tradingagents_backtest_draft";

/** A partial snapshot — the form may persist before every field is touched, and
 * the schema can gain fields a stale draft predates. buildDefaults() backfills
 * anything missing, so a partial is always safe to restore. */
export type BacktestDraft = Partial<BacktestConfigFormValues>;

/**
 * Restore the persisted backtest form draft from localStorage.
 * @returns The saved {@link BacktestDraft}, or `undefined` when none exists or the
 * stored value is missing/corrupt/not a plain object — so callers can spread it safely.
 */
export function loadDraft(): BacktestDraft | undefined {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw);
    // Guard against a non-object payload (e.g. a bare string/array) so callers
    // can spread it safely.
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as BacktestDraft;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

/** Persist the in-progress form draft to localStorage; silently no-ops if storage is unavailable (best-effort). */
export function saveDraft(draft: BacktestDraft): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
  } catch {
    /* storage unavailable (private mode / quota) — draft is best-effort */
  }
}

/** Remove any saved draft (e.g. after a successful submit); silently no-ops on storage failure. */
export function clearDraft(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore — nothing we can do, and losing a draft is non-fatal */
  }
}
