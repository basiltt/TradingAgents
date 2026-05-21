import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
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
    <div className="grid gap-3 rounded-[calc(var(--radius)*1.45)] border border-border/60 bg-muted/18 p-4 shadow-[var(--shadow-soft)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] lg:items-end">
      <div className="space-y-1.5">
        <p className="section-eyebrow">Account</p>
        <select
          aria-label="Filter by account"
          className="h-11 w-full rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/72 px-3.5 text-sm text-foreground shadow-[var(--shadow-soft)] outline-none focus:border-ring focus:ring-4 focus:ring-ring/20"
          value={filters.account_ids?.[0] ?? ""}
          onChange={(e) =>
            updateFilters({ account_ids: e.target.value ? [e.target.value] : [] })
          }
        >
          <option value="">All Accounts</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1.5">
        <p className="section-eyebrow">Pair Search</p>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter pair..."
            className="h-11 pl-10"
            value={filters.symbol ?? ""}
            onChange={(e) => updateFilters({ symbol: e.target.value })}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="section-eyebrow">Side</p>
        <select
          aria-label="Filter by side"
          className="h-11 w-full min-w-[11rem] rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/72 px-3.5 text-sm text-foreground shadow-[var(--shadow-soft)] outline-none focus:border-ring focus:ring-4 focus:ring-ring/20"
          value={filters.side ?? ""}
          onChange={(e) => updateFilters({ side: e.target.value })}
        >
          <option value="">All Sides</option>
          <option value="Buy">Long</option>
          <option value="Sell">Short</option>
        </select>
      </div>

      <div className="flex gap-2 lg:justify-end">
        <Button
          variant="ghost"
          size="sm"
          className="w-full lg:w-auto"
          onClick={clearFilters}
          disabled={!hasFilters}
        >
          <X className="size-3.5" />
          Reset
        </Button>
      </div>
    </div>
  );
}
