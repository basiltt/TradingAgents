import { useEffect, useRef, useState } from "react";
import type { DashboardCard } from "@/api/client";
import { cn } from "@/lib/utils";

interface Props {
  accounts: DashboardCard[];
  selectedAccount: string;
  onSelect: (id: string) => void;
  onToggleInclusion?: (id: string, include: boolean) => void;
}

export function AccountSelector({
  accounts,
  selectedAccount,
  onSelect,
  onToggleInclusion,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    setOpen(false);
    setSearch("");
  }, [accounts]);

  const filtered = accounts.filter(
    (account) =>
      account.label.toLowerCase().includes(search.toLowerCase()) || account.id.includes(search),
  );

  const selectedLabel =
    selectedAccount === "portfolio"
      ? "All Accounts"
      : accounts.find((account) => account.id === selectedAccount)?.label || "Select...";

  return (
    <div ref={ref} className="relative min-w-[200px]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="neu-input-base neu-focus-ring flex h-11 w-full items-center justify-between gap-2 rounded-[var(--neu-radius-md)] px-4 text-sm font-semibold"
      >
        <span className="truncate">{selectedLabel}</span>
        <svg className={cn("size-4 text-[var(--neu-text-muted)] transition-transform", open && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open ? (
        <div className="neu-surface-base neu-surface-raised absolute top-full z-50 mt-2 w-full min-w-[280px] overflow-hidden rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] p-2 shadow-[var(--neu-shadow-float)]">
          <div className="pb-2">
            <input
              ref={inputRef}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search accounts..."
              className="neu-input-base h-10 w-full rounded-[var(--neu-radius-md)] px-4 text-sm outline-none"
            />
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            <button
              type="button"
              onClick={() => {
                onSelect("portfolio");
                setOpen(false);
                setSearch("");
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded-[var(--neu-radius-sm)] border border-transparent px-3 py-2 text-left text-sm transition-colors",
                selectedAccount === "portfolio" && "border-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))] text-[var(--neu-accent)]",
              )}
            >
              <span className="inline-flex size-5 items-center justify-center rounded-full bg-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-surface-raised))] text-[10px] font-bold text-[var(--neu-accent)]">
                A
              </span>
              All Accounts
            </button>
            {filtered.map((account) => {
              const excluded = !account.include_in_analytics;
              return (
                <div
                  key={account.id}
                  className={cn(
                    "flex items-center gap-2 rounded-[var(--neu-radius-sm)] px-3 py-2 text-sm transition-colors",
                    selectedAccount === account.id && "bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))] text-[var(--neu-accent)]",
                    excluded && "opacity-55",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(account.id);
                      setOpen(false);
                      setSearch("");
                    }}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <span
                      className={cn(
                        "size-2 rounded-full shrink-0",
                        account.status === "active" && "bg-emerald-500",
                        account.status === "error" && "bg-red-500",
                        account.status === "disabled" && "bg-gray-400",
                        account.status === "stale" && "bg-amber-500",
                      )}
                    />
                    <span className="truncate">{account.label}</span>
                    {excluded ? <span className="text-[10px] text-[var(--neu-text-soft)]">(excluded)</span> : null}
                    {account.total_equity && !Number.isNaN(parseFloat(account.total_equity)) ? (
                      <span className="ml-auto shrink-0 text-xs tabular-nums text-[var(--neu-text-muted)]">
                        ${parseFloat(account.total_equity).toFixed(0)}
                      </span>
                    ) : null}
                  </button>
                  {onToggleInclusion ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleInclusion(account.id, account.include_in_analytics ? false : true);
                      }}
                      title={excluded ? "Include in analytics" : "Exclude from analytics"}
                      className="rounded-full p-1 text-[var(--neu-text-muted)] transition-colors hover:text-[var(--neu-text-strong)]"
                    >
                      {excluded ? (
                        <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                        </svg>
                      ) : (
                        <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                      )}
                    </button>
                  ) : null}
                </div>
              );
            })}
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-sm text-[var(--neu-text-muted)]">No accounts found</div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
