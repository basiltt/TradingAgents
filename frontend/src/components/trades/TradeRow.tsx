import { memo, useCallback } from "react";
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

export const TradeRow = memo(function TradeRow({ trade }: { trade: Trade }) {
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
      className="border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors"
      onClick={() => dispatch(setSelectedTrade(trade))}
    >
      <td className="px-3 py-2 text-sm">{trade.symbol}</td>
      <td className="px-3 py-2 text-sm">
        <span className={trade.side === "Buy" ? "text-green-400" : "text-red-400"}>
          {trade.side === "Buy" ? "LONG" : "SHORT"}
        </span>
      </td>
      <td className="px-3 py-2 text-sm text-muted-foreground">
        {accountLabel ?? trade.account_id.slice(0, 8)}
      </td>
      <td className="px-3 py-2 text-sm"><TradeStatusBadge status={trade.status} /></td>
      <td className="px-3 py-2 text-sm font-mono">{formatQty(trade.filled_qty)}/{formatQty(trade.qty)}</td>
      <td className="px-3 py-2 text-sm font-mono">{formatPrice(trade.entry_price)}</td>
      <td className="px-3 py-2 text-sm font-mono"><PnLDisplay value={trade.realized_pnl} /></td>
      <td className="px-3 py-2 text-sm font-mono">{formatPrice(trade.fees)}</td>
      <td className="px-3 py-2 text-sm text-muted-foreground">
        <Tooltip>
          <TooltipTrigger>
            <span>{formatRelativeTime(trade.opened_at ?? trade.created_at)}</span>
          </TooltipTrigger>
          <TooltipContent>
            {new Date(trade.opened_at ?? trade.created_at).toLocaleString()}
          </TooltipContent>
        </Tooltip>
      </td>
      <td className="px-3 py-2 text-sm">
        {isActive && (
          <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            {trade.status === "pending" ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                disabled={isPending}
                onClick={() => cancelTrade(trade.account_id, trade.id)}
              >
                Cancel
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
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
