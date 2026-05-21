import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const RECENT_MODELS_KEY = "tradingagents_recent_models";
const MAX_RECENT = 50;

interface RecentEntry {
  value: string;
  ts: number;
}

function loadRecents(): RecentEntry[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_MODELS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveRecent(modelValue: string) {
  const recents = loadRecents().filter((recent) => recent.value !== modelValue);
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

export function ModelSelect({
  options,
  value,
  onChange,
  placeholder = "Search model...",
  className,
}: ModelSelectProps) {
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
    for (const recent of loadRecents()) {
      map.set(recent.value, recent.ts);
    }
    return map;
  }, [recentVersion]);

  const sorted = useMemo(() => {
    const seen = new Set<string>();
    const unique = options.filter((option) => {
      if (seen.has(option.value)) return false;
      seen.add(option.value);
      return true;
    });
    const base = search
      ? unique.filter(
          (option) =>
            option.label.toLowerCase().includes(search.toLowerCase()) ||
            option.value.toLowerCase().includes(search.toLowerCase()),
        )
      : unique;

    return [...base].sort((left, right) => {
      const leftTimestamp = recencyMap.get(left.value) ?? 0;
      const rightTimestamp = recencyMap.get(right.value) ?? 0;
      if (leftTimestamp !== rightTimestamp) return rightTimestamp - leftTimestamp;
      return 0;
    });
  }, [options, recencyMap, search]);

  const selectedLabel = options.find((option) => option.value === value)?.label ?? value;

  useEffect(() => {
    setHighlightIdx(0);
  }, [search]);

  useEffect(() => {
    if (!open || !wrapperRef.current) return;
    const rect = wrapperRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow >= 280) {
      setDropdownStyle({
        position: "fixed",
        top: rect.bottom + 8,
        left: rect.left,
        width: rect.width,
        minWidth: 320,
        zIndex: 9999,
      });
    } else {
      setDropdownStyle({
        position: "fixed",
        bottom: window.innerHeight - rect.top + 8,
        left: rect.left,
        width: rect.width,
        minWidth: 320,
        zIndex: 9999,
      });
    }
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function reposition(event: Event) {
      if (!wrapperRef.current) return;
      if ((event.target as Element)?.closest?.("[data-model-select-portal]")) return;
      const rect = wrapperRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      if (spaceBelow >= 280) {
        setDropdownStyle((style) => ({ ...style, top: rect.bottom + 8, bottom: undefined, left: rect.left, width: rect.width }));
      } else {
        setDropdownStyle((style) => ({ ...style, top: undefined, bottom: window.innerHeight - rect.top + 8, left: rect.left, width: rect.width }));
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
    function onClickOutside(event: MouseEvent) {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(event.target as Node) &&
        !(event.target as Element)?.closest?.("[data-model-select-portal]")
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
      const element = listRef.current.children[highlightIdx] as HTMLElement;
      element?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightIdx]);

  const select = useCallback(
    (option: ModelOption) => {
      onChange(option.value);
      saveRecent(option.value);
      setRecentVersion((version) => version + 1);
      setOpen(false);
      setSearch("");
    },
    [onChange],
  );

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightIdx((index) => Math.min(index + 1, sorted.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIdx((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && sorted[highlightIdx]) {
      event.preventDefault();
      select(sorted[highlightIdx]);
    } else if (event.key === "Escape") {
      setOpen(false);
      setSearch("");
    }
  }

  const dropdown = open ? (
    <div
      data-model-select-portal
      style={dropdownStyle}
      className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-2 shadow-[var(--neu-shadow-float)]"
    >
      <div className="pb-2">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-[var(--neu-text-muted)] pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search models..."
            className="neu-input-base h-10 w-full rounded-[var(--neu-radius-md)] pl-9 pr-3 text-sm outline-none"
          />
        </div>
      </div>
      <div ref={listRef} className="max-h-56 overflow-y-auto py-1">
        {sorted.length === 0 ? (
          <div className="px-3 py-4 text-center text-sm text-[var(--neu-text-muted)]">No models found</div>
        ) : (
          sorted.map((option, index) => {
            const isRecent = recencyMap.has(option.value);
            return (
              <button
                key={option.value}
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                  select(option);
                }}
                onMouseEnter={() => setHighlightIdx(index)}
                className={cn(
                  "flex w-full items-center justify-between rounded-[var(--neu-radius-sm)] border border-transparent px-3 py-2 text-left text-sm font-mono transition-colors",
                  index === highlightIdx && "border-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))]",
                  option.value === value && "font-semibold text-[var(--neu-accent)]",
                )}
              >
                <span className="truncate">{option.label}</span>
                {isRecent && !search ? (
                  <span className="text-[10px] font-sans text-[var(--neu-text-soft)]">recent</span>
                ) : null}
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
        onClick={() => setOpen((current) => !current)}
        className="neu-input-base neu-focus-ring flex h-11 w-full items-center justify-between rounded-[var(--neu-radius-md)] px-4 py-2 text-sm font-mono shadow-none"
      >
        <span className={cn("truncate", !value && "text-[var(--neu-text-soft)]")}>
          {value ? selectedLabel : placeholder}
        </span>
        <svg className={cn("ml-2 size-4 shrink-0 text-[var(--neu-text-muted)] transition-transform", open && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {typeof document !== "undefined" ? createPortal(dropdown, document.body) : null}
    </div>
  );
}
