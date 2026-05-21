import { useEffect, useRef, useState } from "react";
import { useAppSelector, useAppDispatch } from "@/store";
import { setSelectedTrade, setCloseModalTradeId } from "@/store/trades-slice";
import { useTradeEvents } from "@/components/trades/hooks/useTradeEvents";
import { TradeStatusBadge } from "@/components/trades/TradeStatusBadge";
import { PnLDisplay } from "@/components/trades/PnLDisplay";
import { formatPrice, formatQty, formatRelativeTime } from "@/components/trades/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ACTIVE_STATUSES } from "@/components/trades/types";

export function TradeDetailPanel() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector((s) => s.trades.selectedTradeId);
  const selectedTrade = useAppSelector((s) => s.trades.selectedTrade);
  const activeTrade = useAppSelector((s) => (selectedId ? s.trades.activeTrades[selectedId] : undefined));
  const trade = activeTrade ?? selectedTrade ?? undefined;
  const pending = useAppSelector((s) => (selectedId ? s.trades.pendingActions[selectedId] : undefined));
  const panelRef = useRef<HTMLDivElement>(null);

  const { data: eventsData, isLoading: eventsLoading, error: eventsError, refetch } = useTradeEvents(
    trade?.account_id ?? "",
    selectedId ?? "",
    !!selectedId && !!trade?.account_id,
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch(setSelectedTrade(null));
    };
    if (selectedId) document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [selectedId, dispatch]);

  if (!selectedId) return null;

  const handleClose = () => dispatch(setSelectedTrade(null));
  const isActive = trade ? ACTIVE_STATUSES.includes(trade.status) : false;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={handleClose} />
      <div
        ref={panelRef}
        className="fixed right-0 top-0 z-50 h-full w-full max-w-[100vw] sm:max-w-[440px] overflow-y-auto border-l border-border/40 bg-background/80 backdrop-blur-md shadow-2xl animate-in slide-in-from-right duration-250 custom-scrollbar"
      >
        {!trade ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-muted-foreground text-sm font-medium uppercase tracking-wider">Trade not found.</p>
          </div>
        ) : (
          <>
            {/* Sticky Header */}
            <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-md border-b border-border/20 px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-base font-bold tracking-tight">{trade.symbol}</span>
                  <TradeStatusBadge status={trade.status} />
                  <span className={`text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded-lg border ${trade.side === "Buy" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"}`}>
                    {trade.side === "Buy" ? "Long" : "Short"}
                  </span>
                </div>
                <button
                  onClick={handleClose}
                  className="w-8 h-8 rounded-xl flex items-center justify-center hover:bg-muted/60 transition-colors text-muted-foreground cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
            </div>

            <div className="px-4.5 py-4 space-y-4">
              {/* PnL Hero */}
              <div className="rounded-xl bg-card/65 backdrop-blur-sm border border-border/40 p-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground/60 font-black">Unrealized PnL</span>
                    <div className="text-xl font-bold font-mono tabular-nums mt-1">
                      <PnLDisplay value={trade.unrealized_pnl ?? (isActive ? 0 : null)} />
                    </div>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground/60 font-black">Realized PnL</span>
                    <div className="text-xl font-bold font-mono tabular-nums mt-1">
                      <PnLDisplay value={trade.realized_pnl ?? (isActive ? 0 : null)} />
                    </div>
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-border/20 grid grid-cols-3 gap-3">
                  <div>
                    <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-wide">Net PnL</span>
                    <div className="text-sm font-semibold font-mono tabular-nums mt-0.5">
                      <PnLDisplay value={trade.net_pnl ?? (isActive ? ((trade.unrealized_pnl ?? 0) + (trade.realized_pnl ?? 0) - (trade.fees ?? 0)) : null)} />
                    </div>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-wide">Fees</span>
                    <div className="text-sm font-mono tabular-nums text-muted-foreground mt-0.5">{formatPrice(trade.fees ?? 0)}</div>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground/60 font-bold uppercase tracking-wide">Leverage</span>
                    <div className="text-sm font-mono tabular-nums mt-0.5 text-foreground">{trade.leverage}×</div>
                  </div>
                </div>
              </div>

              {/* Position Info */}
              <Section title="Position Details">
                <div className="space-y-1">
                  <Row label="Quantity" value={`${formatQty(trade.filled_qty ?? (isActive ? trade.qty : null))} / ${formatQty(trade.qty)}`} />
                  <Row label="Entry Price" value={formatPrice(trade.entry_price)} mono />
                  <Row label="Avg Fill Price" value={formatPrice(trade.avg_fill_price)} mono />
                  <Row label="Exit Price" value={formatPrice(trade.exit_price)} mono />
                  <Row label="Order Type" value={trade.order_type} />
                  <Row label="Margin Mode" value={trade.margin_mode ?? "--"} />
                  <Row label="Source" value={trade.source} />
                </div>
              </Section>

              {/* Risk */}
              <Section title="Risk Management">
                <div className="space-y-1">
                  <Row label="Stop Loss" value={formatPrice(trade.stop_loss_price)} mono valueClass={trade.stop_loss_price != null ? "text-red-400" : ""} />
                  <Row label="Take Profit" value={formatPrice(trade.take_profit_price)} mono valueClass={trade.take_profit_price != null ? "text-emerald-400" : ""} />
                </div>
                {isActive && <ModifyTPSL trade={trade} />}
              </Section>

              {/* Actions */}
              {isActive && (
                <Section title="Trade Actions">
                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <Button
                      size="sm"
                      className="h-8 text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:text-red-300 rounded-xl cursor-pointer"
                      disabled={!!pending}
                      onClick={() => dispatch(setCloseModalTradeId(trade.id))}
                    >
                      Close Position
                    </Button>
                    <Button
                      size="sm"
                      className="h-8 text-[10px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 hover:text-amber-300 rounded-xl cursor-pointer"
                      disabled={!!pending}
                      onClick={() => dispatch(setCloseModalTradeId(trade.id))}
                    >
                      Partial Close
                    </Button>
                  </div>
                  {pending && (
                    <div className="flex items-center gap-2 mt-2 text-[11px] text-amber-400 font-medium">
                      <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                      {pending.action === "closing" ? "Closing position..." : "Cancelling..."}
                    </div>
                  )}
                </Section>
              )}

              {/* Timeline */}
              <Section title="Timeline Events">
                {eventsLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-7 w-full rounded-xl" />)}
                  </div>
                ) : eventsError ? (
                  <p className="text-[11px] text-red-400 font-medium">
                    Failed to load.{" "}
                    <button className="underline cursor-pointer" onClick={() => refetch()}>Retry</button>
                  </p>
                ) : (
                  <div className="space-y-0 pt-1">
                    {(eventsData?.items ?? []).map((event, idx) => {
                      const events = eventsData?.items ?? [];
                      return (
                        <div key={event.id} className="flex gap-2.5 relative">
                          {idx < events.length - 1 && (
                            <div className="absolute left-[4.5px] top-4 bottom-0 w-px bg-border/40" />
                          )}
                          <div className="w-[10px] h-[10px] rounded-full border-[1.5px] border-muted-foreground/30 bg-background mt-[3px] shrink-0 relative z-10" />
                          <div className="flex-1 pb-3.5 min-w-0">
                            <div className="flex items-baseline justify-between gap-2">
                              <span className="text-[11px] font-semibold text-foreground/90">{event.event_type}</span>
                              <span className="text-[10px] text-muted-foreground/50 shrink-0 font-medium">
                                {formatRelativeTime(event.created_at)}
                              </span>
                            </div>
                            {event.old_status && event.new_status && (
                              <p className="text-[10px] text-muted-foreground/60 mt-0.5 font-medium">
                                {event.old_status} → {event.new_status}
                              </p>
                            )}
                            {event.fill_qty != null && (
                              <p className="text-[10px] text-muted-foreground/60 font-mono mt-0.5">
                                {formatQty(event.fill_qty)} @ {formatPrice(event.fill_price)}
                              </p>
                            )}
                            {event.error_message && (
                              <p className="text-[10px] text-red-400 mt-0.5 font-medium">{event.error_message}</p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {(eventsData?.items ?? []).length === 0 && (
                      <p className="text-[11px] text-muted-foreground/50 py-1 font-medium">No events recorded</p>
                    )}
                  </div>
                )}
              </Section>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border/40 bg-muted/10 rounded-xl p-4.5 space-y-2.5">
      <h3 className="text-[10px] font-black uppercase tracking-[0.12em] text-muted-foreground/80 leading-none pb-0.5">{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, value, mono, valueClass }: { label: string; value: string; mono?: boolean; valueClass?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/10 last:border-0">
      <span className="text-[11px] font-medium text-muted-foreground/60">{label}</span>
      <span className={`text-[11px] font-semibold ${mono ? "font-mono tabular-nums text-foreground/90" : "text-foreground"} ${valueClass ?? ""}`}>{value}</span>
    </div>
  );
}

function ModifyTPSL({ trade }: { trade: { id: string; stop_loss_price: number | null; take_profit_price: number | null } }) {
  const [editing, setEditing] = useState(false);
  const [sl, setSl] = useState(String(trade.stop_loss_price ?? ""));
  const [tp, setTp] = useState(String(trade.take_profit_price ?? ""));

  if (!editing) {
    return (
      <button
        className="mt-2 text-[10px] font-bold uppercase tracking-wider text-primary hover:text-primary-hover transition-colors cursor-pointer"
        onClick={() => setEditing(true)}
      >
        Modify TP / SL →
      </button>
    );
  }

  return (
    <div className="mt-3 pt-3 border-t border-border/20 space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] font-black uppercase tracking-wider text-muted-foreground/50 block mb-1">Stop Loss</label>
          <Input type="number" step="any" value={sl} onChange={(e) => setSl(e.target.value)} className="h-8 text-[11px] font-mono bg-background/50 border-border/40 focus:border-primary/50 rounded-xl" placeholder="—" />
        </div>
        <div>
          <label className="text-[9px] font-black uppercase tracking-wider text-muted-foreground/50 block mb-1">Take Profit</label>
          <Input type="number" step="any" value={tp} onChange={(e) => setTp(e.target.value)} className="h-8 text-[11px] font-mono bg-background/50 border-border/40 focus:border-primary/50 rounded-xl" placeholder="—" />
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" size="sm" className="h-7 text-[10px] flex-1 rounded-xl cursor-pointer" onClick={() => setEditing(false)}>Cancel</Button>
        <Button size="sm" className="h-7 text-[10px] flex-1 bg-primary hover:bg-primary/90 text-primary-foreground font-black uppercase tracking-wider rounded-xl cursor-pointer" onClick={() => setEditing(false)}>Save</Button>
      </div>
    </div>
  );
}
