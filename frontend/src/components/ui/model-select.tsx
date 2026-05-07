import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

const RECENT_MODELS_KEY = "tradingagents_recent_models";
const MAX_RECENT = 50;

interface RecentEntry { value: string; ts: number }

function loadRecents(): RecentEntry[] {
  try { return JSON.parse(localStorage.getItem(RECENT_MODELS_KEY) ?? "[]"); }
  catch { return []; }
}

function saveRecent(modelValue: string) {
  const recents = loadRecents().filter((r) => r.value !== modelValue);
  recents.unshift({ value: modelValue, ts: Date.now() });
  if (recents.length > MAX_RECENT) recents.length = MAX_RECENT;
  localStorage.setItem(RECENT_MODELS_KEY, JSON.stringify(recents));
}

interface ModelOption {
  label: string;
  value: string;
}

interface ModelSelectProps {
  options: ModelOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export function ModelSelect({ options, value, onChange, placeholder = "Search model...", className }: ModelSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlightIdx, setHighlightIdx] = useState(0);
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});
  const wrapperRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [recentVersion, setRecentVersion] = useState(0);

  const recencyMap = useMemo(() => {
    void recentVersion;
    const map = new Map<string, number>();
    for (const r of loadRecents()) map.set(r.value, r.ts);
    return map;
  }, [recentVersion]);

  const sorted = useMemo(() => {
    const base = search
      ? options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()) || o.value.toLowerCase().includes(search.toLowerCase()))
      : options;
    return [...base].sort((a, b) => {
      const ta = recencyMap.get(a.value) ?? 0;
      const tb = recencyMap.get(b.value) ?? 0;
      if (ta !== tb) return tb - ta;
      return 0;
    });
  }, [options, search, recencyMap]);

  const selectedLabel = options.find((o) => o.value === value)?.label ?? value;

  useEffect(() => {
    setHighlightIdx(0);
  }, [search]);

  useEffect(() => {
    if (!open || !wrapperRef.current) return;
    const rect = wrapperRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow >= 280) {
      setDropdownStyle({ position: "fixed", top: rect.bottom + 4, left: rect.left, width: rect.width, minWidth: 320, zIndex: 9999 });
    } else {
      setDropdownStyle({ position: "fixed", bottom: window.innerHeight - rect.top + 4, left: rect.left, width: rect.width, minWidth: 320, zIndex: 9999 });
    }
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function reposition(e: Event) {
      if (!wrapperRef.current) return;
      if ((e.target as Element)?.closest?.("[data-model-select-portal]")) return;
      const rect = wrapperRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      if (spaceBelow >= 280) {
        setDropdownStyle((s) => ({ ...s, top: rect.bottom + 4, bottom: undefined, left: rect.left, width: rect.width }));
      } else {
        setDropdownStyle((s) => ({ ...s, top: undefined, bottom: window.innerHeight - rect.top + 4, left: rect.left, width: rect.width }));
      }
    }
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (
        wrapperRef.current && !wrapperRef.current.contains(e.target as Node) &&
        !(e.target as Element)?.closest?.("[data-model-select-portal]")
      ) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  useEffect(() => {
    if (highlightIdx >= 0 && listRef.current) {
      const el = listRef.current.children[highlightIdx] as HTMLElement;
      el?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightIdx]);

  const select = useCallback((opt: ModelOption) => {
    onChange(opt.value);
    saveRecent(opt.value);
    setRecentVersion((v) => v + 1);
    setOpen(false);
    setSearch("");
  }, [onChange]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlightIdx((i) => Math.min(i + 1, sorted.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHighlightIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && sorted[highlightIdx]) { e.preventDefault(); select(sorted[highlightIdx]); }
    else if (e.key === "Escape") { setOpen(false); setSearch(""); }
  }

  const dropdown = open ? (
    <div
      data-model-select-portal
      style={dropdownStyle}
      className="rounded-lg border border-border bg-popover text-popover-foreground shadow-xl"
    >
      <div className="p-2 border-b border-border">
        <div className="relative">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search models..."
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
          />
        </div>
      </div>
      <div ref={listRef} className="max-h-56 overflow-y-auto py-1">
        {sorted.length === 0 ? (
          <div className="px-3 py-4 text-center text-sm text-muted-foreground">No models found</div>
        ) : (
          sorted.map((opt, i) => {
            const isRecent = recencyMap.has(opt.value);
            return (
            <button
              key={opt.value}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); select(opt); }}
              onMouseEnter={() => setHighlightIdx(i)}
              className={cn(
                "w-full text-left px-3 py-2 text-sm font-mono transition-colors",
                i === highlightIdx ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
                opt.value === value && "font-semibold text-primary",
              )}
            >
              <span className="flex items-center gap-2">
                {opt.label}
                {isRecent && !search && (
                  <span className="text-[10px] text-muted-foreground/60 font-sans">recent</span>
                )}
              </span>
            </button>
            );
          })
        )}
      </div>
    </div>
  ) : null;

  return (
    <div ref={wrapperRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono shadow-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
      >
        <span className={cn("truncate", !value && "text-muted-foreground")}>
          {value ? selectedLabel : placeholder}
        </span>
        <svg className={cn("w-4 h-4 shrink-0 text-muted-foreground transition-transform ml-2", open && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {typeof document !== "undefined" && createPortal(dropdown, document.body)}
    </div>
  );
}
