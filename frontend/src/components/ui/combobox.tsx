import { useCallback, useEffect, useRef, useState } from "react";
import { CheckIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ComboboxProps {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
}

export function Combobox({
  options,
  value,
  onChange,
  placeholder = "Search...",
  loading,
  disabled,
  className,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState(value);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [openUp, setOpenUp] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = search
    ? options.filter((option) => option.toLowerCase().includes(search.toLowerCase())).slice(0, 100)
    : options.slice(0, 100);

  useEffect(() => {
    setSearch(value);
  }, [value]);

  useEffect(() => {
    setHighlightIdx(-1);
  }, [search]);

  useEffect(() => {
    if (open && wrapperRef.current) {
      const rect = wrapperRef.current.getBoundingClientRect();
      setOpenUp(window.innerHeight - rect.bottom < 260);
    }
  }, [open]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (highlightIdx >= 0 && listRef.current) {
      const element = listRef.current.children[highlightIdx] as HTMLElement;
      element?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightIdx]);

  const select = useCallback(
    (nextValue: string) => {
      onChange(nextValue);
      setSearch(nextValue);
      setOpen(false);
    },
    [onChange],
  );

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlightIdx((index) => Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIdx((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && highlightIdx >= 0 && filtered[highlightIdx]) {
      event.preventDefault();
      select(filtered[highlightIdx]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={wrapperRef} className={cn("relative", className)}>
      <Input
        value={search}
        onChange={(event) => {
          const nextValue = event.target.value.toUpperCase();
          setSearch(nextValue);
          onChange(nextValue);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
      />
      {loading ? (
        <div className="absolute right-4 top-1/2 -translate-y-1/2 text-[var(--neu-text-muted)]">
          <svg className="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      ) : null}
      {open && filtered.length > 0 ? (
        <div
          ref={listRef}
          className={cn(
            "neu-surface-base neu-surface-raised absolute z-50 max-h-60 w-full overflow-y-auto rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-2 shadow-[var(--neu-shadow-float)]",
            openUp ? "bottom-full mb-2" : "mt-2",
          )}
        >
          {filtered.map((option, index) => (
            <button
              key={option}
              type="button"
              className={cn(
                "relative flex w-full items-center justify-between rounded-[var(--neu-radius-sm)] border border-transparent py-2.5 pr-10 pl-3 text-left text-sm transition-colors",
                index === highlightIdx && "border-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))]",
                option === value && "font-semibold text-[var(--neu-accent)]",
              )}
              onMouseDown={(event) => {
                event.preventDefault();
                select(option);
              }}
            >
              <span>{option}</span>
              {option === value && (
                <span className="pointer-events-none absolute right-2 flex size-5.5 items-center justify-center rounded-full bg-white text-[var(--neu-accent)] shadow-[var(--neu-shadow-pill)]">
                  <CheckIcon className="pointer-events-none size-3 stroke-[3px]" />
                </span>
              )}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
