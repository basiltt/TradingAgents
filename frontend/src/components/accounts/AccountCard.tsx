import { useNavigate } from "@tanstack/react-router";
import type { DashboardCard } from "@/api/client";
import type { Direction } from "@/store/accounts-slice";
import { useAppSelector } from "@/store";

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

export function AccountCard({ card }: AccountCardProps) {
  const navigate = useNavigate();
  const directions = useAppSelector((s) => s.accounts.directions[card.id]);

  const pnl = parseFloat(card.total_perp_upl || "0");
  const equity = parseFloat(card.total_equity || "0");
  const todayPnl = parseFloat(card.today_pnl || "0");

  return (
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
        <div className="flex items-center gap-1.5">
          <StatusDot status={card.status} />
          <span className="text-[11px] font-medium capitalize text-muted-foreground">{card.status}</span>
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
  );
}
