import { useEffect, useRef } from "react";
import { useAppSelector, useAppDispatch } from "@/store";
import { setSelectedTradeId } from "@/store/trades-slice";
import { useTradeEvents } from "@/components/trades/hooks/useTradeEvents";
import { TradeStatusBadge } from "@/components/trades/TradeStatusBadge";
import { PnLDisplay } from "@/components/trades/PnLDisplay";
import { formatPrice, formatQty, formatRelativeTime } from "@/components/trades/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export function TradeDetailPanel() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector((s) => s.trades.selectedTradeId);
  const trade = useAppSelector((s) => (selectedId ? s.trades.activeTrades[selectedId] : undefined));
  const panelRef = useRef<HTMLDivElement>(null);

  const { data: eventsData, isLoading: eventsLoading, error: eventsError, refetch } = useTradeEvents(
    trade?.account_id ?? "",
    selectedId ?? "",
    !!selectedId && !!trade?.account_id,
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch(setSelectedTradeId(null));
    };
    if (selectedId) document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [selectedId, dispatch]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        dispatch(setSelectedTradeId(null));
      }
    };
    if (selectedId) {
      setTimeout(() => document.addEventListener("mousedown", handler), 0);
    }
    return () => document.removeEventListener("mousedown", handler);
  }, [selectedId, dispatch]);

  if (!selectedId) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" />
      <div
        ref={panelRef}
        className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto border-l border-border bg-background p-6 shadow-xl animate-in slide-in-from-right duration-200"
      >
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Trade Details</h2>
          <Button variant="ghost" size="sm" onClick={() => dispatch(setSelectedTradeId(null))}>
            ✕
          </Button>
        </div>

        {!trade ? (
          <p className="text-muted-foreground">Trade not found in active trades.</p>
        ) : (
          <div className="space-y-6">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-2xl font-bold">{trade.symbol}</span>
                <TradeStatusBadge status={trade.status} />
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field label="Side" value={trade.side.toUpperCase()} />
                <Field label="Leverage" value={`${trade.leverage}x`} />
                <Field label="Quantity" value={`${formatQty(trade.filled_qty)} / ${formatQty(trade.qty)}`} />
                <Field label="Entry Price" value={formatPrice(trade.entry_price)} />
                <Field label="Exit Price" value={formatPrice(trade.exit_price)} />
                <Field label="Avg Fill" value={formatPrice(trade.avg_fill_price)} />
                <Field label="Stop Loss" value={formatPrice(trade.stop_loss_price)} />
                <Field label="Take Profit" value={formatPrice(trade.take_profit_price)} />
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm border-t border-border pt-3">
                <Field label="Realized PnL"><PnLDisplay value={trade.realized_pnl} /></Field>
                <Field label="Net PnL"><PnLDisplay value={trade.net_pnl} /></Field>
                <Field label="Fees" value={formatPrice(trade.fees)} />
                <Field label="Source" value={trade.source} />
              </div>
            </div>

            <div>
              <h3 className="text-sm font-medium mb-3">Events Timeline</h3>
              {eventsLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}
                </div>
              ) : eventsError ? (
                <div className="text-sm text-red-400">
                  Failed to load events.{" "}
                  <button className="underline" onClick={() => refetch()}>Retry</button>
                </div>
              ) : (
                <div className="space-y-2">
                  {(eventsData?.events ?? []).map((event) => (
                    <div key={event.id} className="flex items-start gap-3 text-xs border-l-2 border-border pl-3 py-1">
                      <div className="flex-1">
                        <span className="font-medium">{event.event_type}</span>
                        {event.old_status && event.new_status && (
                          <span className="text-muted-foreground ml-1">
                            {event.old_status} → {event.new_status}
                          </span>
                        )}
                        {event.fill_qty != null && (
                          <span className="text-muted-foreground ml-1">
                            qty: {formatQty(event.fill_qty)} @ {formatPrice(event.fill_price)}
                          </span>
                        )}
                        {event.error_message && (
                          <p className="text-red-400 mt-0.5">{event.error_message}</p>
                        )}
                      </div>
                      <span className="text-muted-foreground shrink-0">
                        {formatRelativeTime(event.created_at)}
                      </span>
                    </div>
                  ))}
                  {(eventsData?.events ?? []).length === 0 && (
                    <p className="text-muted-foreground text-xs">No events recorded.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function Field({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <span className="text-muted-foreground">{label}</span>
      <div className="font-mono">{children ?? value}</div>
    </div>
  );
}
