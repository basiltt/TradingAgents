import { useState, useRef, useEffect } from "react";
import type { DashboardCard } from "@/api/client";

interface Props {
  accounts: DashboardCard[];
  selectedAccount: string;
  onSelect: (id: string) => void;
  onToggleInclusion?: (id: string, include: boolean) => void;
}

export function AccountSelector({ accounts, selectedAccount, onSelect, onToggleInclusion }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting UI state when accounts list changes
    setOpen(false);
    setSearch("");
  }, [accounts]);

  const filtered = accounts.filter(
    (a) => a.label.toLowerCase().includes(search.toLowerCase()) || a.id.includes(search),
  );

  const selectedLabel =
    selectedAccount === "portfolio"
      ? "All Accounts"
      : accounts.find((a) => a.id === selectedAccount)?.label || "Select...";

  return (
    <div ref={ref} className="relative min-w-[200px]">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-muted/50 text-sm font-medium hover:bg-muted transition-colors"
      >
        <span className="truncate">{selectedLabel}</span>
        <svg className={`w-4 h-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 top-full mt-1 w-full min-w-[280px] rounded-xl border border-border bg-card shadow-lg overflow-hidden">
          <div className="p-2 border-b border-border">
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search accounts..."
              className="w-full px-3 py-1.5 rounded-lg bg-muted/50 text-sm outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            <button
              onClick={() => { onSelect("portfolio"); setOpen(false); setSearch(""); }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50 transition-colors ${
                selectedAccount === "portfolio" ? "bg-primary/10 text-primary font-medium" : ""
              }`}
            >
              <span className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary">A</span>
              All Accounts
            </button>
            {filtered.map((acc) => {
              const excluded = !acc.include_in_analytics;
              return (
                <div
                  key={acc.id}
                  className={`flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50 transition-colors ${
                    selectedAccount === acc.id ? "bg-primary/10 text-primary font-medium" : ""
                  } ${excluded ? "opacity-50" : ""}`}
                >
                  <button
                    onClick={() => { onSelect(acc.id); setOpen(false); setSearch(""); }}
                    className="flex-1 flex items-center gap-2 text-left min-w-0"
                  >
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      acc.status === "active" ? "bg-emerald-500" :
                      acc.status === "error" ? "bg-red-500" :
                      acc.status === "disabled" ? "bg-gray-400" : "bg-yellow-500"
                    }`} />
                    <span className="truncate">{acc.label}</span>
                    {excluded && <span className="text-[10px] text-muted-foreground">(excluded)</span>}
                    {acc.total_equity && !isNaN(parseFloat(acc.total_equity)) && (
                      <span className="ml-auto text-xs text-muted-foreground tabular-nums shrink-0">
                        ${parseFloat(acc.total_equity).toFixed(0)}
                      </span>
                    )}
                  </button>
                  {onToggleInclusion && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onToggleInclusion(acc.id, acc.include_in_analytics ? false : true); }}
                      title={excluded ? "Include in analytics" : "Exclude from analytics"}
                      className="p-1 rounded hover:bg-muted transition-colors shrink-0"
                    >
                      {excluded ? (
                        <svg className="w-3.5 h-3.5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                        </svg>
                      ) : (
                        <svg className="w-3.5 h-3.5 text-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                      )}
                    </button>
                  )}
                </div>
              );
            })}
            {filtered.length === 0 && (
              <div className="px-3 py-4 text-sm text-muted-foreground text-center">No accounts found</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
