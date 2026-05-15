import { useMemo } from "react";
import type { Trade } from "@/components/trades/types";
import { TradeRow } from "@/components/trades/TradeRow";
import { useAppSelector, useAppDispatch } from "@/store";
import { setSortColumn, setSortDirection } from "@/store/trades-slice";

const COLUMNS = [
  { key: "symbol", label: "Symbol" },
  { key: "side", label: "Side" },
  { key: "account_id", label: "Account" },
  { key: "status", label: "Status" },
  { key: "qty", label: "Qty" },
  { key: "entry_price", label: "Entry" },
  { key: "realized_pnl", label: "PnL" },
  { key: "fees", label: "Fees" },
  { key: "opened_at", label: "Opened" },
  { key: "", label: "Actions" },
] as const;

function sortTrades(trades: Trade[], column: string, direction: "asc" | "desc"): Trade[] {
  if (!column) return trades;
  const sorted = [...trades].sort((a, b) => {
    const aVal = (a as Record<string, unknown>)[column];
    const bVal = (b as Record<string, unknown>)[column];
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;
    if (typeof aVal === "string" && typeof bVal === "string") return aVal.localeCompare(bVal);
    if (typeof aVal === "number" && typeof bVal === "number") return aVal - bVal;
    return 0;
  });
  return direction === "desc" ? sorted.reverse() : sorted;
}

function filterTrades(trades: Trade[], filters: { account_ids?: string[]; symbol?: string; side?: string }): Trade[] {
  return trades.filter((t) => {
    if (filters.account_ids?.length && !filters.account_ids.includes(t.account_id)) return false;
    if (filters.symbol && !t.symbol.toLowerCase().includes(filters.symbol.toLowerCase())) return false;
    if (filters.side && t.side !== filters.side) return false;
    return true;
  });
}

export function TradesTable({ trades }: { trades: Trade[] }) {
  const dispatch = useAppDispatch();
  const sortColumn = useAppSelector((s) => s.trades.sortColumn);
  const sortDirection = useAppSelector((s) => s.trades.sortDirection);
  const filters = useAppSelector((s) => s.trades.filters);

  const filtered = useMemo(() => filterTrades(trades, filters), [trades, filters]);
  const sorted = useMemo(() => sortTrades(filtered, sortColumn, sortDirection), [filtered, sortColumn, sortDirection]);

  const handleSort = (key: string) => {
    if (!key) return;
    if (sortColumn === key) {
      dispatch(setSortDirection(sortDirection === "asc" ? "desc" : "asc"));
    } else {
      dispatch(setSortColumn(key));
      dispatch(setSortDirection("asc"));
    }
  };

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <p className="text-lg font-medium">No trades found</p>
        <p className="text-sm mt-1">Trades will appear here when positions are opened.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            {COLUMNS.map((col) => (
              <th
                key={col.key || col.label}
                className={`px-3 py-2 text-xs font-medium text-muted-foreground ${col.key ? "cursor-pointer hover:text-foreground select-none" : ""}`}
                onClick={() => handleSort(col.key)}
              >
                {col.label}
                {sortColumn === col.key && (
                  <span className="ml-1">{sortDirection === "asc" ? "↑" : "↓"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((trade) => (
            <TradeRow key={trade.id} trade={trade} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
