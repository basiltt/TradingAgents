/**
 * @module number
 *
 * Numeric input-parsing and clamping helpers for controlled form fields.
 *
 * Architectural role: a tiny pure-utility module that centralizes the
 * "parse a text input value and clamp it into a valid range" logic that form
 * `onChange` handlers repeat across the scanner/auto-trade config UIs. Having one
 * implementation removes the per-field risk of mistyping the min/max/fallback in a
 * hand-inlined `Math.min(MAX, Math.max(MIN, +e.target.value || X))` expression.
 *
 * Boundary: pure functions of their inputs — no DOM, no I/O, no state.
 */

/**
 * Parse a raw input value and clamp it into `[min, max]`, falling back to a
 * default when the value is empty or non-numeric.
 *
 * Mirrors the common `Math.min(max, Math.max(min, +raw || fallback))` idiom: an
 * empty string or unparseable input (`NaN`) becomes `fallback` (which is itself
 * NOT re-clamped — callers always pass an in-range fallback), and any numeric
 * value is bounded to the range.
 *
 * @param raw - The raw input value (typically `e.target.value`, a string; numbers
 *   are also accepted).
 * @param min - Inclusive lower bound.
 * @param max - Inclusive upper bound.
 * @param fallback - Value to use when `raw` is empty or non-numeric.
 * @returns A number within `[min, max]`, or `fallback` for empty/NaN input.
 *
 * @example
 * clampNumber("130", 1, 125, 1);  // 125 (clamped to max)
 * clampNumber("", 1, 125, 1);     // 1   (fallback)
 * clampNumber("abc", 0, 10, 0);   // 0   (fallback)
 * clampNumber("5", 1, 125, 1);    // 5
 */
export function clampNumber(
  raw: string | number,
  min: number,
  max: number,
  fallback: number,
): number {
  const n = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(n) || (typeof raw === "string" && raw.trim() === "")) {
    return fallback;
  }
  return Math.min(max, Math.max(min, n));
}

/**
 * Parse a raw input value and clamp it into `[min, max]`, returning `null` when
 * the input is empty.
 *
 * For optional numeric fields where an empty input means "unset" (persisted as
 * `null`) rather than a default. A non-empty but non-numeric input also yields
 * `null` (treated as "no valid value"). Mirrors the
 * `raw ? Math.min(max, Math.max(min, parseInt(raw))) : null` idiom.
 *
 * @param raw - The raw input value (typically `e.target.value`).
 * @param min - Inclusive lower bound.
 * @param max - Inclusive upper bound.
 * @returns A number within `[min, max]`, or `null` when `raw` is empty/non-numeric.
 *
 * @example
 * clampNumberOrNull("20", 1, 20);  // 20
 * clampNumberOrNull("99", 1, 20);  // 20 (clamped)
 * clampNumberOrNull("", 1, 20);    // null (unset)
 */
export function clampNumberOrNull(
  raw: string,
  min: number,
  max: number,
): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return Math.min(max, Math.max(min, n));
}
