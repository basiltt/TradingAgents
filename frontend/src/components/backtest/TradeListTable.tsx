import * as React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { BacktestTrade } from "./types";
import { formatUsd, formatPct, formatDateTime, pnlColorClass, TH_CLASS } from "./format";
import {
  type TradeSortKey,
  type SortDirection,
  type TradeFilters,
  filterTrades,
  sortTrades,
  withCumulativePnl,
  paginate,
  pageCount,
  tradesToCsv,
  normalizeSide,
} from "./tradeTable";

const PAGE_SIZE = 25;

/** Trigger a client-side CSV download. */
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

interface SortHeaderProps {
  label: string;
  sortKey: TradeSortKey;
  active: TradeSortKey;
  direction: SortDirection;
  onSort: (key: TradeSortKey) => void;
  className?: string;
}

function SortHeader({ label, sortKey, active, direction, onSort, className }: SortHeaderProps) {
  const isActive = active === sortKey;
  return (
    <th
      scope="col"
      className={cn("px-3 py-2 text-left", className)}
      aria-sort={isActive ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn("inline-flex items-center gap-1", TH_CLASS, "hover:text-[var(--neu-text-strong)]")}
        aria-label={`Sort by ${label}`}
      >
        {label}
        <span aria-hidden className="text-[0.6rem]">
          {isActive ? (direction === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

export interface TradeListTableProps {
  trades: BacktestTrade[];
  className?: string;
  /** Total trades on the server, if `trades` is a truncated subset. When set and
   * larger than `trades.length`, the export is labeled as a partial export. */
  totalCount?: number;
  /** Override the CSV download (used in tests). */
  onExport?: (csv: string) => void;
}

export function TradeListTable({ trades, className, totalCount, onExport }: TradeListTableProps) {
  const isTruncated = totalCount != null && totalCount > trades.length;
  const [sortKey, setSortKey] = React.useState<TradeSortKey>("entry_time");
  const [direction, setDirection] = React.useState<SortDirection>("asc");
  const [filters, setFilters] = React.useState<TradeFilters>({
    side: "all",
    outcome: "all",
    closeReason: "all",
    search: "",
  });
  const [page, setPage] = React.useState(1);

  const closeReasons = React.useMemo(() => {
    const set = new Set<string>();
    for (const t of trades) if (t.close_reason) set.add(t.close_reason);
    return Array.from(set).sort();
  }, [trades]);

  // Cumulative PnL is computed on the chronological order, then we filter/sort
  // for display — so the cumulative column always reflects true running total.
  const chronological = React.useMemo(
    () => withCumulativePnl(sortTrades(trades, "entry_time", "asc")),
    [trades],
  );

  const processed = React.useMemo(() => {
    const filtered = filterTrades(chronological, filters);
    return sortTrades(filtered, sortKey, direction) as Array<
      BacktestTrade & { cumulative_pnl: number }
    >;
  }, [chronological, filters, sortKey, direction]);

  const totalPages = pageCount(processed.length, PAGE_SIZE);
  const safePage = Math.min(page, totalPages);
  const pageRows = paginate(processed, safePage, PAGE_SIZE);

  const handleSort = (key: TradeSortKey) => {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDirection("desc");
    }
    setPage(1);
  };

  const updateFilter = (patch: Partial<TradeFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };

  const handleExport = () => {
    const csv = tradesToCsv(processed);
    if (onExport) onExport(csv);
    else downloadCsv("backtest-trades.csv", csv);
  };

  return (
    <div className={cn("flex flex-col gap-3", className)} data-testid="trade-list-table">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          placeholder="Search symbol…"
          value={filters.search ?? ""}
          onChange={(e) => updateFilter({ search: e.target.value })}
          aria-label="Search symbol"
          className="neu-surface-inset h-9 rounded-[var(--neu-radius-sm)] px-3 text-sm text-[var(--neu-text-strong)] placeholder:text-[var(--neu-text-muted)]"
        />
        <select
          value={filters.side}
          onChange={(e) => updateFilter({ side: e.target.value as TradeFilters["side"] })}
          aria-label="Filter by side"
          className="neu-surface-inset h-9 rounded-[var(--neu-radius-sm)] px-2 text-sm"
        >
          <option value="all">All sides</option>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
        <select
          value={filters.outcome}
          onChange={(e) => updateFilter({ outcome: e.target.value as TradeFilters["outcome"] })}
          aria-label="Filter by outcome"
          className="neu-surface-inset h-9 rounded-[var(--neu-radius-sm)] px-2 text-sm"
        >
          <option value="all">All outcomes</option>
          <option value="win">Winners</option>
          <option value="loss">Losers</option>
        </select>
        <select
          value={filters.closeReason}
          onChange={(e) => updateFilter({ closeReason: e.target.value })}
          aria-label="Filter by close reason"
          className="neu-surface-inset h-9 rounded-[var(--neu-radius-sm)] px-2 text-sm"
        >
          <option value="all">All close reasons</option>
          {closeReasons.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <span className="ml-auto text-[0.78rem] text-[var(--neu-text-muted)]">
          {processed.length} trade{processed.length === 1 ? "" : "s"}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={handleExport}
          disabled={processed.length === 0}
          title={isTruncated ? `Exports the loaded ${trades.length} of ${totalCount} trades` : undefined}
        >
          {isTruncated ? "Export CSV (partial)" : "Export CSV"}
        </Button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/60">
        <table className="w-full border-collapse text-sm" data-testid="trade-table">
          <caption className="sr-only">Simulated trades</caption>
          <thead>
            <tr className="bg-[color:var(--neu-surface-inset)]/40">
              <SortHeader label="Symbol" sortKey="symbol" active={sortKey} direction={direction} onSort={handleSort} />
              <SortHeader label="Side" sortKey="side" active={sortKey} direction={direction} onSort={handleSort} />
              <SortHeader label="Entry" sortKey="entry_time" active={sortKey} direction={direction} onSort={handleSort} />
              <SortHeader label="Exit" sortKey="exit_time" active={sortKey} direction={direction} onSort={handleSort} />
              <SortHeader label="PnL" sortKey="pnl" active={sortKey} direction={direction} onSort={handleSort} className="text-right" />
              <SortHeader label="PnL %" sortKey="pnl_pct" active={sortKey} direction={direction} onSort={handleSort} className="text-right" />
              <th scope="col" className={cn("px-3 py-2 text-right", TH_CLASS)}>
                Cum. PnL
              </th>
              <SortHeader label="Close" sortKey="close_reason" active={sortKey} direction={direction} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-[var(--neu-text-muted)]">
                  No trades match the current filters.
                </td>
              </tr>
            ) : (
              pageRows.map((t) => {
                const side = normalizeSide(t.side);
                return (
                  <tr
                    key={t.id}
                    className="border-t border-[color:var(--neu-stroke-soft)]/40 hover:bg-[color:var(--neu-surface-inset)]/30"
                  >
                    <td className="px-3 py-2 font-medium text-[var(--neu-text-strong)]">{t.symbol}</td>
                    <td className="px-3 py-2">
                      <Badge variant={side === "long" ? "default" : "destructive"}>{t.side}</Badge>
                    </td>
                    <td className="px-3 py-2 tabular-nums text-[var(--neu-text-muted)]">{formatDateTime(t.entry_time)}</td>
                    <td className="px-3 py-2 tabular-nums text-[var(--neu-text-muted)]">{formatDateTime(t.exit_time)}</td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", pnlColorClass(t.pnl))}>
                      {formatUsd(t.pnl, { sign: true })}
                    </td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", pnlColorClass(t.pnl_pct))}>
                      {formatPct(t.pnl_pct, { sign: true })}
                    </td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", pnlColorClass(t.cumulative_pnl))}>
                      {formatUsd(t.cumulative_pnl, { sign: true })}
                    </td>
                    <td className="px-3 py-2 text-[0.8rem] text-[var(--neu-text-muted)]">
                      {t.close_reason ?? "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 ? (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage <= 1}
          >
            Prev
          </Button>
          <span className="text-[0.78rem] text-[var(--neu-text-muted)]">
            Page {safePage} of {totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage >= totalPages}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}
