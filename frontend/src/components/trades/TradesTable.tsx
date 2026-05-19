import { useMemo, useState, useCallback } from "react";
import type { Trade } from "@/components/trades/types";
import { ACTIVE_STATUSES } from "@/components/trades/types";
import { TradeRow } from "@/components/trades/TradeRow";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { useAppSelector, useAppDispatch } from "@/store";
import { setSortColumn, setSortDirection } from "@/store/trades-slice";
import { useTradeActions } from "@/components/trades/hooks/useTradeActions";

const COLUMNS = [
  { key: "__select", label: "", width: "w-9" },
  { key: "symbol", label: "Pair" },
  { key: "side", label: "Side", width: "w-16" },
  { key: "account_id", label: "Account" },
  { key: "status", label: "Status", width: "w-24" },
  { key: "qty", label: "Size" },
  { key: "entry_price", label: "Entry" },
  { key: "leverage", label: "Lev", width: "w-14" },
  { key: "realized_pnl", label: "PnL" },
  { key: "unrealized_pnl", label: "Unreal. PnL" },
  { key: "fees", label: "Fees" },
  { key: "opened_at", label: "Opened" },
  { key: "", label: "", width: "w-20" },
] as const;

function sortTrades(trades: Trade[], column: string, direction: "asc" | "desc"): Trade[] {
  if (!column) return trades;
  const dir = direction === "asc" ? 1 : -1;
  return [...trades].sort((a, b) => {
    const aVal = (a as unknown as Record<string, unknown>)[column];
    const bVal = (b as unknown as Record<string, unknown>)[column];
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;
    if (typeof aVal === "string" && typeof bVal === "string") return aVal.localeCompare(bVal) * dir;
    if (typeof aVal === "number" && typeof bVal === "number") return (aVal - bVal) * dir;
    return 0;
  });
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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const { closeTrade } = useTradeActions();

  const filtered = useMemo(() => filterTrades(trades, filters), [trades, filters]);
  const sorted = useMemo(() => sortTrades(filtered, sortColumn, sortDirection), [filtered, sortColumn, sortDirection]);

  const allSelected = sorted.length > 0 && selectedIds.size === sorted.length;

  const toggleAll = useCallback(() => {
    setSelectedIds(allSelected ? new Set() : new Set(sorted.map((t) => t.id)));
  }, [allSelected, sorted]);

  const toggleOne = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSort = (key: string) => {
    if (!key || key === "__select") return;
    if (sortColumn === key) {
      dispatch(setSortDirection(sortDirection === "asc" ? "desc" : "asc"));
    } else {
      dispatch(setSortColumn(key));
      dispatch(setSortDirection("asc"));
    }
  };

  const handleBulkClose = () => {
    selectedIds.forEach((id) => {
      const trade = sorted.find((t) => t.id === id);
      if (trade && ACTIVE_STATUSES.includes(trade.status)) {
        closeTrade(trade.account_id, trade.id);
      }
    });
    setSelectedIds(new Set());
  };

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-muted-foreground rounded-xl border border-border/40 bg-card/40">
        <div className="w-10 h-10 rounded-full border border-border/60 flex items-center justify-center mb-3">
          <svg className="w-4 h-4 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
        </div>
        <p className="text-xs font-medium">No positions</p>
        <p className="text-[11px] mt-0.5 text-muted-foreground/60">Active trades will appear here</p>
      </div>
    );
  }

  return (
    <TooltipProvider>
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 rounded-lg border border-primary/30 bg-primary/5 mb-2 animate-in fade-in duration-150">
          <span className="text-xs font-medium text-primary">{selectedIds.size} selected</span>
          <div className="flex gap-2 ml-auto">
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-[11px] px-2 text-destructive hover:bg-destructive/10"
              onClick={handleBulkClose}
            >
              Close All
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-[11px] px-2"
              onClick={() => setSelectedIds(new Set())}
            >
              Deselect
            </Button>
          </div>
        </div>
      )}
      <div className="rounded-xl border border-border/50 overflow-hidden bg-card/60">
        <table className="w-full text-left">
          <thead>
            <tr className="bg-muted/20">
              {COLUMNS.map((col) => (
                <th
                  key={col.key || "actions"}
                  className={`px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/60 ${col.width ?? ""} ${col.key && col.key !== "__select" ? "cursor-pointer hover:text-muted-foreground transition-colors select-none" : ""}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.key === "__select" ? (
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="w-3 h-3 rounded-sm border-border/60 accent-primary cursor-pointer"
                    />
                  ) : (
                    <span className="inline-flex items-center gap-0.5">
                      {col.label}
                      {sortColumn === col.key && (
                        <span className="text-primary text-[9px]">{sortDirection === "asc" ? "▲" : "▼"}</span>
                      )}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((trade, i) => (
              <TradeRow
                key={trade.id}
                trade={trade}
                selected={selectedIds.has(trade.id)}
                onToggleSelect={toggleOne}
                isLast={i === sorted.length - 1}
              />
            ))}
          </tbody>
        </table>
      </div>
    </TooltipProvider>
  );
}
