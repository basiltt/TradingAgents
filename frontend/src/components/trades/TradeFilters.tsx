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
    <div className="flex flex-wrap items-center gap-3 py-3">
      <select
        aria-label="Filter by account"
        className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        value={filters.account_ids?.[0] ?? ""}
        onChange={(e) =>
          updateFilters({ account_ids: e.target.value ? [e.target.value] : [] })
        }
      >
        <option value="">All Accounts</option>
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label}
          </option>
        ))}
      </select>

      <Input
        placeholder="Symbol..."
        className="h-9 w-32"
        value={filters.symbol ?? ""}
        onChange={(e) => updateFilters({ symbol: e.target.value })}
      />

      <select
        aria-label="Filter by side"
        className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        value={filters.side ?? ""}
        onChange={(e) => updateFilters({ side: e.target.value })}
      >
        <option value="">All Sides</option>
        <option value="long">Long</option>
        <option value="short">Short</option>
      </select>

      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={clearFilters}>
          Clear
        </Button>
      )}
    </div>
  );
}
