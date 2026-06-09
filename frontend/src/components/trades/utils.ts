const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const nf = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 30],
  ["month", 12],
  ["year", Infinity],
];

/**
 * Formats an ISO date string as a localized relative time (e.g. "3 minutes ago").
 * @param dateStr - ISO 8601 date string; empty or unparseable input yields "--".
 * @returns Relative-time phrase, "just now" for deltas under 5s, or "--" on bad input.
 */
export function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return "--";
  const ts = new Date(dateStr).getTime();
  if (isNaN(ts)) return "--";
  const diff = (Date.now() - ts) / 1000;
  if (diff < 5) return "just now";
  let remaining = diff;
  for (const [unit, threshold] of UNITS) {
    if (remaining < threshold) {
      return rtf.format(-Math.round(remaining), unit);
    }
    remaining /= threshold;
  }
  return rtf.format(-Math.round(remaining), "year");
}

const nfCache = new Map<number, Intl.NumberFormat>();
function getNf(decimals: number): Intl.NumberFormat {
  let f = nfCache.get(decimals);
  if (!f) {
    f = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    nfCache.set(decimals, f);
  }
  return f;
}

/**
 * Formats a number as a fixed-decimal price using a cached en-US formatter.
 * @param value - Price value; null renders as "--".
 * @param decimals - Fixed fraction digits (used as both min and max). Defaults to 2.
 * @returns Formatted price string, or "--" when value is null.
 */
export function formatPrice(value: number | null, decimals = 2): string {
  if (value == null) return "--";
  return getNf(decimals).format(value);
}

const qtyNfCache = new Map<number, Intl.NumberFormat>();
function getQtyNf(maxDecimals: number): Intl.NumberFormat {
  let f = qtyNfCache.get(maxDecimals);
  if (!f) {
    f = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: maxDecimals,
    });
    qtyNfCache.set(maxDecimals, f);
  }
  return f;
}

/**
 * Formats a quantity with 2 to `decimals` fraction digits (always shows at least 2).
 * @param value - Quantity; null or undefined renders as "--".
 * @param decimals - Maximum fraction digits. Defaults to 4.
 * @returns Formatted quantity string, or "--" when value is nullish.
 */
export function formatQty(value: number | null | undefined, decimals = 4): string {
  if (value == null) return "--";
  return getQtyNf(decimals).format(value);
}

/**
 * Formats a profit/loss number with a leading "+" for positive values and 2 decimals.
 * @param value - Signed P&L amount.
 * @returns Formatted string, e.g. "+12.50" or "-3.40".
 */
export function formatPnl(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${nf.format(value)}`;
}

/**
 * Formats an ISO date string as local time with the UTC equivalent in parentheses.
 * @param dateStr - ISO 8601 date string; empty or unparseable input yields "--".
 * @returns "<local> (<utc>)" string, or "--" on bad input.
 */
export function formatAbsoluteTime(dateStr: string): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "--";
  const local = d.toLocaleString();
  const utc = d.toUTCString();
  return `${local} (${utc})`;
}
