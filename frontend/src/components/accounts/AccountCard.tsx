import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { MoreVertical, XCircle, SlidersHorizontal, History } from "lucide-react";
import { toast } from "sonner";
import type { DashboardCard } from "@/api/client";
import { api } from "@/api/client";
import type { Direction } from "@/store/accounts-slice";
import { useAppSelector } from "@/store";
import { CloseAllConfirmDialog } from "./CloseAllConfirmDialog";
import { ConditionalRulesDialog } from "./ConditionalRulesDialog";
import { CloseHistoryDialog } from "./CloseHistoryDialog";

interface AccountCardProps {
  card: DashboardCard;
  onRefresh: () => void;
}

function DirectionIcon({ dir }: { dir?: Direction }) {
  if (!dir || dir === "neutral") return null;
  if (dir === "up") return <span className="text-emerald-500 text-[10px] animate-flash">▲</span>;
  return <span className="text-red-500 text-[10px] animate-flash">▼</span>;
}

function StatusDot({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-emerald-500 shadow-emerald-500/50",
    stale: "bg-amber-500 shadow-amber-500/50",
    error: "bg-red-500 shadow-red-500/50 animate-pulse",
    disabled: "bg-zinc-400 shadow-zinc-400/50",
  };
  return <span className={`w-2 h-2 rounded-full shadow-[0_0_6px] ${styles[status] ?? styles.disabled}`} />;
}

export function AccountCard({ card, onRefresh }: AccountCardProps) {
  const navigate = useNavigate();
  const directions = useAppSelector((s) => s.accounts.directions[card.id]);

  const [menuOpen, setMenuOpen] = useState(false);
  const [closeDialogOpen, setCloseDialogOpen] = useState(false);
  const [rulesDialogOpen, setRulesDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const pnl = parseFloat(card.total_perp_upl || "0");
  const equity = parseFloat(card.total_equity || "0");
  const todayPnl = parseFloat(card.today_pnl || "0");
  const hasPositions = card.positions_count > 0;
  const activeRules = card.active_rules_count ?? 0;

  useEffect(() => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [menuOpen]);

  const handleMenuClick = useCallback((e: React.MouseEvent, action: "close" | "rules" | "history") => {
    e.stopPropagation();
    setMenuOpen(false);
    if (action === "close") setCloseDialogOpen(true);
    else if (action === "rules") setRulesDialogOpen(true);
    else if (action === "history") setHistoryDialogOpen(true);
  }, []);

  return (
    <>
      <div
        className="group rounded-2xl border border-border/40 bg-card hover:bg-card/80 hover:border-border/70 transition-all duration-200 hover:shadow-lg hover:shadow-black/5 cursor-pointer overflow-hidden"
        onClick={() => navigate({ to: "/accounts/$accountId", params: { accountId: card.id } })}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <h3 className="font-semibold text-sm truncate">{card.label}</h3>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider border ${
              card.account_type === "live"
                ? "border-amber-500/30 text-amber-500 bg-amber-500/[0.06]"
                : "border-blue-500/30 text-blue-500 bg-blue-500/[0.06]"
            }`}>
              {card.account_type}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {activeRules > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-violet-500/15 text-violet-400 font-medium">
                {activeRules} rule{activeRules !== 1 ? "s" : ""}
              </span>
            )}
            <StatusDot status={card.status} />
            <span className="text-[11px] font-medium capitalize text-muted-foreground">{card.status}</span>

            {/* Kebab menu */}
            <div ref={menuRef} className="relative" onClick={(e) => e.stopPropagation()}>
              <button
                aria-label={`Account actions for ${card.label}`}
                className="p-1.5 rounded-lg text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/30 transition-colors"
                onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
              >
                <MoreVertical className="w-4 h-4" />
              </button>

              {menuOpen && (
                <div className="absolute right-0 top-full mt-1 z-50 min-w-[200px] rounded-xl border border-border/50 bg-popover shadow-xl shadow-black/20 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150">
                  <button
                    className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-left text-sm transition-colors ${
                      hasPositions
                        ? "text-red-400 hover:bg-red-500/10"
                        : "text-muted-foreground/30 cursor-not-allowed"
                    }`}
                    disabled={!hasPositions}
                    onClick={(e) => hasPositions && handleMenuClick(e, "close")}
                    title={!hasPositions ? "No open positions" : undefined}
                  >
                    <XCircle className="w-4 h-4" />
                    Close All Positions
                  </button>
                  <button
                    className="w-full flex items-center gap-2.5 px-3.5 py-2 text-left text-sm text-muted-foreground hover:bg-muted/30 transition-colors"
                    onClick={(e) => handleMenuClick(e, "rules")}
                  >
                    <SlidersHorizontal className="w-4 h-4" />
                    Conditional Rules
                  </button>
                  <button
                    className="w-full flex items-center gap-2.5 px-3.5 py-2 text-left text-sm text-muted-foreground hover:bg-muted/30 transition-colors"
                    onClick={(e) => handleMenuClick(e, "history")}
                  >
                    <History className="w-4 h-4" />
                    View History
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {card.status === "error" && card.last_error && (
          <div className="mx-5 mb-2 px-3 py-1.5 rounded-lg bg-red-500/[0.06] border border-red-500/15">
            <p className="text-[11px] text-red-500 truncate">{card.last_error}</p>
          </div>
        )}

        {/* Equity highlight */}
        {card.total_equity != null && (
          <div className="px-5 pb-2">
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-bold tabular-nums tracking-tight">${equity.toFixed(2)}</span>
              <DirectionIcon dir={directions?.equity} />
            </div>
            <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wider font-medium">Equity</span>
          </div>
        )}

        {/* Metrics grid */}
        {card.total_equity != null && (
          <div className="grid grid-cols-3 border-t border-border/30 divide-x divide-border/30">
            <div className="px-4 py-3">
              <div className={`text-sm font-semibold tabular-nums flex items-center gap-1 ${pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                <DirectionIcon dir={directions?.pnl} />
                ${pnl.toFixed(2)}
              </div>
              <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mt-0.5">Unreal. PnL</div>
            </div>
            <div className="px-4 py-3">
              <div className={`text-sm font-semibold tabular-nums ${todayPnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                ${todayPnl.toFixed(2)}
              </div>
              <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mt-0.5">Today</div>
            </div>
            <div className="px-4 py-3">
              <div className="text-sm font-semibold tabular-nums">{card.positions_count}</div>
              <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mt-0.5">Positions</div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-2.5 border-t border-border/20 bg-muted/[0.03]">
          {card.last_connected_at ? (
            <span className="text-[10px] text-muted-foreground/50">
              Updated {new Date(card.last_connected_at).toLocaleString(undefined, {
                month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
              })}
            </span>
          ) : (
            <span className="text-[10px] text-muted-foreground/50">No data yet</span>
          )}
          <div className="p-1 rounded-lg text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-colors">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </div>
      </div>

      {/* Dialogs */}
      <CloseAllConfirmDialog
        open={closeDialogOpen}
        onOpenChange={setCloseDialogOpen}
        accountId={card.id}
        accountLabel={card.label}
        positionsCount={card.positions_count}
        onSuccess={onRefresh}
      />
      <ConditionalRulesDialog
        open={rulesDialogOpen}
        onOpenChange={setRulesDialogOpen}
        accountId={card.id}
        accountLabel={card.label}
        onSave={onRefresh}
      />
      <CloseHistoryDialog
        open={historyDialogOpen}
        onOpenChange={setHistoryDialogOpen}
        accountId={card.id}
        accountLabel={card.label}
      />
    </>
  );
}
