import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import type { ScanResultItem } from "@/api/client";

function toggleSet<T>(set: Set<T>, val: T): Set<T> {
  const next = new Set(set);
  if (next.has(val)) next.delete(val); else next.add(val);
  return next;
}

function FilterChip({ label, active, color, onClick }: { label: string; active: boolean; color?: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-2.5 py-1 rounded-lg text-xs font-medium border transition-all",
        active
          ? `${color ?? "bg-primary/15 border-primary/40 text-primary"}`
          : "bg-transparent border-border/40 text-muted-foreground hover:bg-muted/50",
      )}
    >
      {label}
    </button>
  );
}

export interface ScanFiltersState {
  symbol: string;
  signal: Set<string>;
  confidence: Set<string>;
  status: Set<string>;
  minStrength: number;
  showFilters: boolean;
}

export const DEFAULT_FILTERS: ScanFiltersState = {
  symbol: "",
  signal: new Set(),
  confidence: new Set(),
  status: new Set(),
  minStrength: 0,
  showFilters: false,
};

export function useScanFilters(results: ScanResultItem[]) {
  const [filters, setFilters] = useState<ScanFiltersState>(DEFAULT_FILTERS);

  const update = <K extends keyof ScanFiltersState>(key: K, value: ScanFiltersState[K]) =>
    setFilters((prev) => ({ ...prev, [key]: value }));

  const hasActive = filters.symbol !== "" || filters.signal.size > 0 || filters.confidence.size > 0 || filters.status.size > 0 || filters.minStrength > 0;

  const filtered = useMemo(() => {
    let items = results;
    if (filters.symbol) {
      const q = filters.symbol.toLowerCase();
      items = items.filter((r) => r.ticker.toLowerCase().includes(q));
    }
    if (filters.signal.size > 0) {
      items = items.filter((r) => {
        const dir = r.direction === "hold" || r.direction === "unknown" ? "hold" : r.direction;
        return filters.signal.has(dir);
      });
    }
    if (filters.confidence.size > 0) {
      items = items.filter((r) => filters.confidence.has(r.confidence));
    }
    if (filters.status.size > 0) {
      items = items.filter((r) => filters.status.has(r.status));
    }
    if (filters.minStrength > 0) {
      items = items.filter((r) => Math.abs(r.score) >= filters.minStrength);
    }
    return items;
  }, [results, filters]);

  const clearAll = () => setFilters({ ...DEFAULT_FILTERS });

  return { filters, update, hasActive, filtered, clearAll };
}

export function ScanResultFiltersBar({
  filters,
  update,
  hasActive,
  totalCount,
  filteredCount,
  clearAll,
}: {
  filters: ScanFiltersState;
  update: <K extends keyof ScanFiltersState>(key: K, value: ScanFiltersState[K]) => void;
  hasActive: boolean;
  totalCount: number;
  filteredCount: number;
  clearAll: () => void;
}) {
  return (
    <div className="rounded-2xl border border-border/40 bg-card overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search symbol..."
            value={filters.symbol}
            onChange={(e) => update("symbol", e.target.value)}
            className="w-full h-9 pl-9 pr-3 rounded-lg bg-muted/30 border border-border/30 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <button
          onClick={() => update("showFilters", !filters.showFilters)}
          className={cn(
            "inline-flex items-center gap-1.5 px-3 h-9 rounded-lg text-xs font-medium border transition-colors",
            filters.showFilters || hasActive
              ? "bg-primary/10 border-primary/30 text-primary"
              : "border-border/40 text-muted-foreground hover:bg-muted/50",
          )}
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          Filters
          {hasActive && <span className="w-1.5 h-1.5 rounded-full bg-primary" />}
        </button>
        {hasActive && (
          <span className="text-xs text-muted-foreground tabular-nums">{filteredCount}/{totalCount}</span>
        )}
      </div>

      {filters.showFilters && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/20 pt-3">
          <div className="space-y-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Signal</span>
            <div className="flex flex-wrap gap-1.5">
              <FilterChip label="Buy" active={filters.signal.has("buy")} color="bg-emerald-500/15 border-emerald-500/40 text-emerald-400" onClick={() => update("signal", toggleSet(filters.signal, "buy"))} />
              <FilterChip label="Sell" active={filters.signal.has("sell")} color="bg-red-500/15 border-red-500/40 text-red-400" onClick={() => update("signal", toggleSet(filters.signal, "sell"))} />
              <FilterChip label="Hold" active={filters.signal.has("hold")} color="bg-amber-500/15 border-amber-500/40 text-amber-400" onClick={() => update("signal", toggleSet(filters.signal, "hold"))} />
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Confidence</span>
            <div className="flex flex-wrap gap-1.5">
              {["high", "moderate", "low", "none"].map((c) => (
                <FilterChip key={c} label={c.charAt(0).toUpperCase() + c.slice(1)} active={filters.confidence.has(c)} onClick={() => update("confidence", toggleSet(filters.confidence, c))} />
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Status</span>
            <div className="flex flex-wrap gap-1.5">
              {["completed", "failed", "cancelled"].map((s) => (
                <FilterChip key={s} label={s.charAt(0).toUpperCase() + s.slice(1)} active={filters.status.has(s)} onClick={() => update("status", toggleSet(filters.status, s))} />
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Min Strength</span>
              <span className="text-xs font-mono tabular-nums text-muted-foreground">{filters.minStrength > 0 ? `>= ${filters.minStrength}` : "Any"}</span>
            </div>
            <input
              type="range"
              min={0} max={10} step={1}
              value={filters.minStrength}
              onChange={(e) => update("minStrength", Number(e.target.value))}
              className="w-full h-1.5 rounded-full appearance-none bg-muted cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-[9px] text-muted-foreground/40 px-0.5">
              <span>0</span><span>5</span><span>10</span>
            </div>
          </div>

          {hasActive && (
            <button onClick={clearAll} className="text-xs text-primary hover:underline">
              Clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
