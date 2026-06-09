/**
 * @module csvDownload
 *
 * Browser CSV download helper.
 *
 * Architectural role: a thin DOM side-effect utility that triggers a client-side
 * file download for a CSV string. Extracted from {@link ../TradeListTable} so the
 * component file exports only its component (React Fast Refresh /
 * `react-refresh/only-export-components`) and so the download behavior can be
 * stubbed/inspected independently.
 *
 * Boundary: touches the DOM (`document`, `URL`, anchor click) and is therefore the
 * single place that performs the browser-only download side effect.
 */

/**
 * Trigger a client-side CSV file download.
 *
 * Creates an in-memory Blob, wires it to a transient `<a download>` element,
 * programmatically clicks it, then revokes the object URL to release memory.
 *
 * @param filename - Suggested filename for the saved file (e.g. `"trades.csv"`).
 * @param csv - The CSV payload to download.
 * @returns Nothing; the side effect is the browser download prompt.
 *
 * @remarks Side effects: appends and removes a DOM node, allocates and revokes an
 *   object URL. No-op safety is the caller's responsibility — this assumes a DOM
 *   is present (browser context, not SSR).
 *
 * @example
 * downloadCsv("backtest-trades.csv", "symbol,pnl\nBTCUSDT,12.3\n");
 */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
