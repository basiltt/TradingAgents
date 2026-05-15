const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const nf = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const qtyNf = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 });

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 30],
  ["month", 12],
  ["year", Infinity],
];

export function formatRelativeTime(dateStr: string): string {
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
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

export function formatPrice(value: number | null, decimals = 2): string {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatQty(value: number, decimals = 4): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatPnl(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${nf.format(value)}`;
}

export function formatAbsoluteTime(dateStr: string): string {
  const d = new Date(dateStr);
  const local = d.toLocaleString();
  const utc = d.toUTCString();
  return `${local} (${utc})`;
}
