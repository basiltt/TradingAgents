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

export function formatQty(value: number | null | undefined, decimals = 4): string {
  if (value == null) return "—";
  return getQtyNf(decimals).format(value);
}

export function formatPnl(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${nf.format(value)}`;
}

export function formatAbsoluteTime(dateStr: string): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "--";
  const local = d.toLocaleString();
  const utc = d.toUTCString();
  return `${local} (${utc})`;
}
