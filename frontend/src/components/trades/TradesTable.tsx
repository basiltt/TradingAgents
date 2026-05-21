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
  { key: "symbol", label: "Pair", width: "" },
  { key: "side", label: "Side", width: "w-16" },
  { key: "account_id", label: "Account", width: "" },
  { key: "status", label: "Status", width: "w-24" },
  { key: "qty", label: "Size", width: "" },
  { key: "entry_price", label: "Entry", width: "" },
  { key: "leverage", label: "Lev", width: "w-14" },
  { key: "realized_pnl", label: "PnL", width: "" },
  { key: "unrealized_pnl", label: "Unreal. PnL", width: "" },
  { key: "fees", label: "Fees", width: "" },
  { key: "opened_at", label: "Opened", width: "" },
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
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground rounded-2xl border border-border/50 bg-card/65 backdrop-blur-sm glass-card">
        <div className="w-12 h-12 rounded-[calc(var(--radius)*1.25)] bg-muted/15 flex items-center justify-center mb-4 border border-border/30 backdrop-blur-sm">
          <svg className="w-6 h-6 text-muted-foreground/45" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
        </div>
        <h3 className="text-sm font-bold uppercase tracking-wider text-foreground">No positions</h3>
        <p className="text-[10px] mt-1 text-muted-foreground/60 uppercase tracking-wider font-semibold">Active trades will appear here</p>
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
              className="h-6 text-[11px] px-2 text-destructive hover:bg-destructive/10 cursor-pointer"
              onClick={handleBulkClose}
            >
              Close All
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-[11px] px-2 cursor-pointer"
              onClick={() => setSelectedIds(new Set())}
            >
              Deselect
            </Button>
          </div>
        </div>
      )}
      <div className="rounded-xl border border-border/50 overflow-hidden bg-card/65 backdrop-blur-sm glass-card overflow-x-auto shadow-lg shadow-black/5">
        <table className="w-full text-left min-w-[800px]">
          <thead>
            <tr className="bg-muted/15 border-b border-border/20">
              {COLUMNS.map((col) => (
                <th
                  key={col.key || "actions"}
                  className={`px-4 py-3 text-[10px] font-black uppercase tracking-[0.1em] text-muted-foreground/60 ${col.width ?? ""} ${col.key && col.key !== "__select" ? "cursor-pointer hover:text-muted-foreground transition-colors select-none" : ""}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.key === "__select" ? (
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="w-3.5 h-3.5 rounded-md border-border/60 accent-primary cursor-pointer"
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
            {sorted.map((trade) => (
              <TradeRow
                key={trade.id}
                trade={trade}
                selected={selectedIds.has(trade.id)}
                onToggleSelect={toggleOne}
              />
            ))}
          </tbody>
        </table>
      </div>
    </TooltipProvider>
  );
}
