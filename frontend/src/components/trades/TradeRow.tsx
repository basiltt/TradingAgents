import { memo } from "react";
import type { Trade } from "@/components/trades/types";
import { ACTIVE_STATUSES } from "@/components/trades/types";
import { TradeStatusBadge } from "@/components/trades/TradeStatusBadge";
import { PnLDisplay } from "@/components/trades/PnLDisplay";
import { formatPrice, formatQty, formatRelativeTime } from "@/components/trades/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useAppDispatch, useAppSelector } from "@/store";
import { setSelectedTrade, setCloseModalTradeId } from "@/store/trades-slice";
import { useTradeActions } from "@/components/trades/hooks/useTradeActions";

export const TradeRow = memo(function TradeRow({
  trade,
  selected,
  onToggleSelect,
  isLast,
}: {
  trade: Trade;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  isLast: boolean;
}) {
  const dispatch = useAppDispatch();
  const accountLabel = useAppSelector(
    (s) => s.accounts.dashboard.find((a) => a.id === trade.account_id)?.label,
  );
  const pending = useAppSelector((s) => s.trades.pendingActions[trade.id]);
  const { cancelTrade } = useTradeActions();

  const isActive = ACTIVE_STATUSES.includes(trade.status);
  const isPending = !!pending;

  return (
    <tr
      className={`group transition-colors cursor-pointer ${!isLast ? "border-b border-border/20" : ""} ${selected ? "bg-primary/[0.04]" : "hover:bg-muted/10"}`}
      onClick={() => dispatch(setSelectedTrade(trade))}
    >
      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(trade.id)}
          className="w-3 h-3 rounded-sm border-border/60 accent-primary cursor-pointer"
        />
      </td>
      <td className="px-3 py-2">
        <span className="text-[13px] font-semibold tracking-tight">{trade.symbol}</span>
      </td>
      <td className="px-3 py-2">
        <span className={`text-[10px] font-bold uppercase tracking-wider ${trade.side === "Buy" ? "text-emerald-400" : "text-red-400"}`}>
          {trade.side === "Buy" ? "Long" : "Short"}
        </span>
      </td>
      <td className="px-3 py-2 text-[11px] text-muted-foreground">
        {accountLabel ?? trade.account_id.slice(0, 8)}
      </td>
      <td className="px-3 py-2"><TradeStatusBadge status={trade.status} /></td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums text-muted-foreground">
        {formatQty(trade.filled_qty ?? (isActive ? trade.qty : null))}<span className="text-muted-foreground/40">/{formatQty(trade.qty)}</span>
      </td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums">{formatPrice(trade.entry_price)}</td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums text-muted-foreground">{trade.leverage}×</td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums"><PnLDisplay value={trade.realized_pnl ?? (isActive ? 0 : null)} /></td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums"><PnLDisplay value={trade.unrealized_pnl ?? (isActive ? 0 : null)} /></td>
      <td className="px-3 py-2 text-[11px] font-mono tabular-nums text-muted-foreground/60">{formatPrice(trade.fees ?? 0)}</td>
      <td className="px-3 py-2 text-[11px] text-muted-foreground/60">
        <Tooltip>
          <TooltipTrigger>
            <span>{formatRelativeTime(trade.opened_at ?? trade.created_at)}</span>
          </TooltipTrigger>
          <TooltipContent side="left">
            {new Date(trade.opened_at ?? trade.created_at).toLocaleString()}
          </TooltipContent>
        </Tooltip>
      </td>
      <td className="px-3 py-2">
        {isActive && (
          <div className="opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
            {trade.status === "pending" ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-5 text-[10px] px-1.5 rounded text-amber-400 hover:text-amber-300 hover:bg-amber-500/10"
                disabled={isPending}
                onClick={() => cancelTrade(trade.account_id, trade.id)}
              >
                Cancel
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="h-5 text-[10px] px-1.5 rounded text-red-400 hover:text-red-300 hover:bg-red-500/10"
                disabled={isPending}
                onClick={() => dispatch(setCloseModalTradeId(trade.id))}
              >
                Close
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
});
