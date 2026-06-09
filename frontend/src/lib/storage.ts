/**
 * @module storage
 *
 * Safe JSON-typed `localStorage` helpers.
 *
 * Architectural role: centralizes the `try { JSON.parse(localStorage.getItem) } catch`
 * read pattern and the write-with-swallow pattern that several feature modules
 * (watchlists, endpoints, analytics filters) hand-rolled. A single home for the
 * private-browsing / quota-exceeded safety so a storage failure never throws into
 * render or a user action.
 *
 * Boundary: touches `localStorage` only. Browser-only — assumes `window.localStorage`
 * exists (guarded so SSR/non-DOM contexts degrade to the fallback rather than throw).
 */

/**
 * Read and JSON-parse a value from `localStorage`, returning `fallback` on any
 * failure (missing key, malformed JSON, storage access denied).
 *
 * @typeParam T - The expected shape of the stored value.
 * @param key - The storage key.
 * @param fallback - Value returned when the key is absent or unreadable/unparseable.
 * @returns The parsed value, or `fallback`.
 *
 * @remarks Does NOT validate that the parsed shape matches `T` — it trusts the
 *   writer. Pair with a schema parse at the call site if the data is untrusted.
 *
 * @example
 * const lists = readJson<Watchlist[]>("tradingagents_watchlists", []);
 */
export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

/**
 * JSON-serialize and write a value to `localStorage`, swallowing any failure.
 *
 * @param key - The storage key.
 * @param value - The value to serialize and store.
 * @returns `true` when the write succeeded, `false` when it was swallowed (e.g.
 *   quota exceeded, private-mode denial). Callers may ignore the result for
 *   best-effort persistence.
 *
 * @remarks Side effect: writes to `localStorage`. Never throws — a storage failure
 *   is reported via the boolean return, not an exception.
 *
 * @example
 * writeJson("tradingagents_watchlists", lists);
 */
export function writeJson(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
