/* eslint-disable react-refresh/only-export-components */
import { useState, useMemo, useCallback, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ScanResultItem } from "@/api/client";

export type SignalBucket = "buy" | "sell" | "hold" | "skipped";

export function signalBucket(r: ScanResultItem): SignalBucket {
  if (r.signal_source === "ta_prefilter") return "skipped";
  if (r.direction === "buy" || r.direction === "sell") return r.direction;
  return "hold"; // hold, unknown, or missing
}

function toggleSet<T>(set: Set<T>, val: T): Set<T> {
  const next = new Set(set);
  if (next.has(val)) next.delete(val); else next.add(val);
  return next;
}

const FILTER_NEU_CLASSES = {
  accent: "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))]",
  success: "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]",
  danger: "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]",
  warning: "bg-[color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-base))] text-[var(--neu-warning)] border-[color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))]",
  neutral: "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)]",
} as const;

function FilterChip({
  label,
  active,
  color = "accent",
  onClick,
}: {
  label: string;
  active: boolean;
  color?: keyof typeof FILTER_NEU_CLASSES;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex min-h-10 items-center justify-center rounded-[var(--neu-radius-pill)] border px-3.5 py-2 text-[11px] font-bold uppercase tracking-[0.18em] transition-all duration-200 focus-visible:outline-none shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px] active:scale-95 cursor-pointer",
        active
          ? FILTER_NEU_CLASSES[color]
          : "bg-[var(--neu-surface-raised)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] hover:text-[var(--neu-text-strong)] hover:shadow-[var(--neu-shadow-raised-hover)]",
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

const STORAGE_PREFIX = "tradingagents_scan_filters_";

function saveFilters(key: string, filters: ScanFiltersState) {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify({
      symbol: filters.symbol,
      signal: [...filters.signal],
      confidence: [...filters.confidence],
      status: [...filters.status],
      minStrength: filters.minStrength,
      showFilters: filters.showFilters,
    }));
  } catch { /* ignore localStorage errors */ }
}

function loadFilters(key: string): ScanFiltersState {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    if (!raw) return DEFAULT_FILTERS;
    const parsed = JSON.parse(raw);
    return {
      symbol: parsed.symbol ?? "",
      signal: new Set(parsed.signal ?? []),
      confidence: new Set(parsed.confidence ?? []),
      status: new Set(parsed.status ?? []),
      minStrength: parsed.minStrength ?? 0,
      showFilters: parsed.showFilters ?? false,
    };
  } catch {
    return DEFAULT_FILTERS;
  }
}

export function useScanFilters(results: ScanResultItem[], storageKey = "default") {
  const [filters, setFilters] = useState<ScanFiltersState>(() => loadFilters(storageKey));

  const update = useCallback(<K extends keyof ScanFiltersState>(key: K, value: ScanFiltersState[K]) => {
    setFilters((prev) => {
      const next = { ...prev, [key]: value };
      saveFilters(storageKey, next);
      return next;
    });
  }, [storageKey]);

  const hasActive = filters.symbol !== "" || filters.signal.size > 0 || filters.confidence.size > 0 || filters.status.size > 0 || filters.minStrength > 0;

  const filtered = useMemo(() => {
    let items = results;
    if (filters.symbol) {
      const q = filters.symbol.toLowerCase();
      items = items.filter((r) => r.ticker.toLowerCase().includes(q));
    }
    if (filters.signal.size > 0) {
      items = items.filter((r) => filters.signal.has(signalBucket(r)));
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

  const clearAll = () => {
    const cleared = { ...DEFAULT_FILTERS };
    setFilters(cleared);
    saveFilters(storageKey, cleared);
  };

  return { filters, update, hasActive, filtered, clearAll };
}

function FilterSection({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="section-eyebrow text-[0.62rem] tracking-[0.24em]">
        {label}
      </div>
      <div className="flex flex-wrap gap-2.5">
        {children}
      </div>
    </div>
  );
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
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <svg
            className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-[var(--neu-text-muted)]"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <Input
            type="text"
            placeholder="Search symbol or pair"
            value={filters.symbol}
            onChange={(e) => update("symbol", e.target.value)}
            className="h-12 border-none shadow-[var(--neu-shadow-input)] bg-[var(--neu-surface-muted)] pl-11 text-sm focus-within:ring-2 focus-within:ring-[var(--neu-accent)]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            type="button"
            variant={filters.showFilters || hasActive ? "secondary" : "outline"}
            size="sm"
            onClick={() => update("showFilters", !filters.showFilters)}
            className="min-w-[9rem] justify-center uppercase tracking-[0.18em]"
          >
            <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
            Filters
            {hasActive ? <span className="size-1.5 rounded-full bg-current opacity-80" /> : null}
          </Button>

          <Badge variant="secondary" className="border border-[color:var(--neu-stroke-soft)] px-3 py-1.5 text-[10px] tracking-[0.18em]">
            {filteredCount} of {totalCount}
          </Badge>

          {hasActive ? (
            <Button type="button" variant="ghost" size="xs" onClick={clearAll} className="uppercase tracking-[0.16em] text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]">
              Clear
            </Button>
          ) : null}
        </div>
      </div>

      {filters.showFilters ? (
        <div className="mt-5 space-y-4 border-t border-[color:var(--neu-stroke-soft)] pt-5">
          <div className="grid gap-4 xl:grid-cols-[1.25fr_1.25fr_1fr]">
            <FilterSection label="Signal">
              <FilterChip label="Buy" active={filters.signal.has("buy")} color="success" onClick={() => update("signal", toggleSet(filters.signal, "buy"))} />
              <FilterChip label="Sell" active={filters.signal.has("sell")} color="danger" onClick={() => update("signal", toggleSet(filters.signal, "sell"))} />
              <FilterChip label="Hold" active={filters.signal.has("hold")} color="warning" onClick={() => update("signal", toggleSet(filters.signal, "hold"))} />
              <FilterChip label="Skipped" active={filters.signal.has("skipped")} color="neutral" onClick={() => update("signal", toggleSet(filters.signal, "skipped"))} />
            </FilterSection>

            <FilterSection label="Confidence">
              {["high", "moderate", "low", "none"].map((c) => (
                <FilterChip
                  key={c}
                  label={c.charAt(0).toUpperCase() + c.slice(1)}
                  active={filters.confidence.has(c)}
                  onClick={() => update("confidence", toggleSet(filters.confidence, c))}
                />
              ))}
            </FilterSection>

            <FilterSection label="Status">
              {["completed", "failed", "cancelled"].map((s) => (
                <FilterChip
                  key={s}
                  label={s.charAt(0).toUpperCase() + s.slice(1)}
                  active={filters.status.has(s)}
                  onClick={() => update("status", toggleSet(filters.status, s))}
                />
              ))}
            </FilterSection>
          </div>

          <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 sm:p-5 border-none">
            <div className="mb-3 flex items-center justify-between gap-3 text-[11px] font-bold uppercase tracking-[0.16em]">
              <span className="text-[var(--neu-text-muted)]">Minimum strength</span>
              <span className="rounded-full border border-[color:var(--neu-stroke-soft)] bg-[var(--neu-surface-base)] px-3 py-1 font-mono text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-pill)]">
                {filters.minStrength > 0 ? `>= ${filters.minStrength}` : "Any"}
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={10}
              step={1}
              value={filters.minStrength}
              onChange={(e) => update("minStrength", Number(e.target.value))}
              className="neu-slider w-full"
            />
            <div className="mt-2 flex justify-between px-1 text-[10px] font-semibold text-[var(--neu-text-muted)]/60">
              <span>0</span>
              <span>5</span>
              <span>10</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
