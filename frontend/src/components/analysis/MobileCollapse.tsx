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
    storageKey ? readStorage(storageKey, defaultOpen) : defaultOpen
  );

  // Sync to storage whenever open changes
  useEffect(() => {
    if (storageKey) writeStorage(storageKey, open);
  }, [open, storageKey]);

  const toggle = () => setOpen((v) => !v);

  return (
    <div className={className}>
      {/* Mobile toggle header */}
      <button
        type="button"
        onClick={toggle}
        className="md:hidden w-full flex items-center justify-between gap-2 px-4 py-3 rounded-t-xl border border-border bg-card hover:bg-muted/40 active:bg-muted/60 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2 min-w-0">
          {title}
          {badge && <div className="shrink-0">{badge}</div>}
        </div>
        <svg
          className={cn("w-4 h-4 text-muted-foreground shrink-0 transition-transform duration-200", open ? "rotate-180" : "rotate-0")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Mobile body */}
      <div
        className={cn(
          "md:hidden border border-t-0 border-border rounded-b-xl overflow-hidden transition-all duration-200",
          open ? "max-h-[9999px] opacity-100" : "max-h-0 opacity-0 pointer-events-none",
        )}
      >
        {children}
      </div>

      {/* Desktop: always visible, no wrapper */}
      <div className="hidden md:block">
        {children}
      </div>
    </div>
  );
}

