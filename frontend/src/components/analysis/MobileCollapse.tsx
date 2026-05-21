import { useState, useEffect, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface MobileCollapseProps {
  title: ReactNode;
  badge?: ReactNode;
  defaultOpen?: boolean;
  /** localStorage key — when provided, open/closed state survives page refresh */
  storageKey?: string;
  children: ReactNode;
  className?: string;
}

function readStorage(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // storage unavailable — silently ignore
  }
}

/**
 * On mobile: renders a tappable header that expands/collapses the body.
 * State is persisted in localStorage when `storageKey` is provided.
 * On md+: renders header + body always visible (no toggle behavior).
 */
export function MobileCollapse({ title, badge, defaultOpen = true, storageKey, children, className }: MobileCollapseProps) {
  const [open, setOpen] = useState(() =>
    storageKey ? readStorage(storageKey, defaultOpen) : defaultOpen,
  );

  useEffect(() => {
    if (storageKey) writeStorage(storageKey, open);
  }, [open, storageKey]);

  const toggle = () => setOpen((v) => !v);

  return (
    <div className={className}>
      <button
        type="button"
        onClick={toggle}
        className="neu-surface-base neu-surface-raised md:hidden flex w-full items-center justify-between gap-3 rounded-[var(--neu-radius-lg)] px-4 py-3.5 text-left"
        aria-expanded={open}
      >
        <div className="flex min-w-0 items-center gap-2">
          {title}
          {badge ? <div className="shrink-0">{badge}</div> : null}
        </div>
        <span className="neu-surface-base neu-surface-inset flex size-8 shrink-0 items-center justify-center rounded-[var(--neu-radius-sm)] text-[var(--neu-text-muted)]">
          <svg
            className={cn("size-4 transition-transform duration-200", open ? "rotate-180" : "rotate-0")}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2.25}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </span>
      </button>

      <div
        className={cn(
          "md:hidden overflow-hidden transition-all duration-200",
          open ? "max-h-[9999px] opacity-100 pt-3" : "pointer-events-none max-h-0 opacity-0",
        )}
      >
        {children}
      </div>

      <div className="hidden md:block">
        {children}
      </div>
    </div>
  );
}
