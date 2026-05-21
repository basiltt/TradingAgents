import { Input } from "@/components/ui/input";
import { useTradeFilters } from "@/components/trades/hooks/useTradeFilters";
import { useAppSelector } from "@/store";

export function TradeFilters() {
  const { filters, updateFilters, clearFilters } = useTradeFilters();
  const accounts = useAppSelector((s) => s.accounts.dashboard);

  const hasFilters =
    (filters.account_ids?.length ?? 0) > 0 ||
    !!filters.symbol ||
    !!filters.side;

  return (
    <div className="flex flex-wrap items-center gap-2 py-2.5">
      <select
        aria-label="Filter by account"
        className="h-7 rounded-md border border-border/50 bg-background/50 backdrop-blur-sm px-2.5 text-[11px] font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all hover:bg-muted/15 cursor-pointer"
        value={filters.account_ids?.[0] ?? ""}
        onChange={(e) =>
          updateFilters({ account_ids: e.target.value ? [e.target.value] : [] })
        }
      >
        <option value="" className="bg-popover text-foreground">All Accounts</option>
        {accounts.map((a) => (
          <option key={a.id} value={a.id} className="bg-popover text-foreground">{a.label}</option>
        ))}
      </select>

      <div className="relative">
        <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/45" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
        <Input
          placeholder="Filter pair..."
          className="h-7 w-32 pl-7 text-[11px] border-border/50 bg-background/50"
          value={filters.symbol ?? ""}
          onChange={(e) => updateFilters({ symbol: e.target.value })}
        />
      </div>

      <select
        aria-label="Filter by side"
        className="h-7 rounded-md border border-border/50 bg-background/50 backdrop-blur-sm px-2.5 text-[11px] font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all hover:bg-muted/15 cursor-pointer"
        value={filters.side ?? ""}
        onChange={(e) => updateFilters({ side: e.target.value })}
      >
        <option value="" className="bg-popover text-foreground">All Sides</option>
        <option value="Buy" className="bg-popover text-foreground">Long</option>
        <option value="Sell" className="bg-popover text-foreground">Short</option>
      </select>

      {hasFilters && (
        <button
          className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/60 hover:text-primary transition-colors ml-1.5 px-2.5 py-1 rounded-md hover:bg-muted/15 cursor-pointer"
          onClick={clearFilters}
        >
          Reset
        </button>
      )}
    </div>
  );
}
