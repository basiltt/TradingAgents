import type { OpenOrder } from "@/api/client";

interface OrdersTableProps {
  orders: OpenOrder[];
}

export function OrdersTable({ orders }: OrdersTableProps) {
  if (orders.length === 0) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-8 text-center">
        <div className="w-10 h-10 rounded-[calc(var(--radius)*1.2)] bg-muted/50 flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
        </div>
        <p className="text-sm text-muted-foreground/60">No open orders</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Desktop view (table) */}
      <div className="hidden sm:block rounded-2xl border border-border/40 bg-card overflow-hidden">
        <div className="overflow-x-auto scrollbar-none">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/30">
                <th className="text-left px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Symbol</th>
                <th className="text-left px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Side</th>
                <th className="text-left px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Type</th>
                <th className="text-right px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Qty</th>
                <th className="text-right px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Price</th>
                <th className="text-left px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => {
                const isBuy = o.side === "Buy";
                const statusColors: Record<string, string> = {
                  New: "bg-blue-500/10 text-blue-500 border-blue-500/20",
                  PartiallyFilled: "bg-amber-500/10 text-amber-500 border-amber-500/20",
                  Filled: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
                  Cancelled: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
                };
                return (
                  <tr key={i} className="border-b border-border/20 last:border-0 hover:bg-muted/[0.04] transition-colors">
                    <td className="px-4 py-3 font-semibold">{o.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] px-2.5 py-1 rounded-full font-bold uppercase tracking-wider border ${
                        isBuy
                          ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/[0.08]"
                          : "border-red-500/30 text-red-500 bg-red-500/[0.08]"
                      }`}>
                        {o.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {o.orderType}{o.stopOrderType ? ` (${o.stopOrderType})` : ""}
                    </td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums">{o.qty}</td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums">
                      {o.price !== "0" ? `$${parseFloat(o.price).toFixed(2)}` : (
                        <span className="text-[10px] px-2 py-0.5 rounded-md bg-muted/50 text-muted-foreground font-medium">Market</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded-full font-semibold border ${statusColors[o.orderStatus] ?? statusColors.New}`}>
                        {o.orderStatus}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile view (cards) */}
      <div className="space-y-3 sm:hidden">
        {orders.map((o, i) => {
          const isBuy = o.side === "Buy";
          const statusColors: Record<string, string> = {
            New: "bg-blue-500/10 text-blue-500 border-blue-500/20",
            PartiallyFilled: "bg-amber-500/10 text-amber-500 border-amber-500/20",
            Filled: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
            Cancelled: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
          };

          return (
            <div key={i} className="rounded-2xl border border-border/40 bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-foreground">{o.symbol}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${statusColors[o.orderStatus] ?? statusColors.New}`}>
                  {o.orderStatus}
                </span>
              </div>
              
              <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border/10 text-xs">
                <div className="space-y-0.5">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Side</span>
                  <div className="mt-1">
                    <span className={`text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider border ${
                      isBuy
                        ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/[0.08]"
                        : "border-red-500/30 text-red-500 bg-red-500/[0.08]"
                    }`}>
                      {isBuy ? "Buy" : "Sell"}
                    </span>
                  </div>
                </div>
                <div className="space-y-0.5">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Type</span>
                  <p className="text-xs font-medium text-foreground mt-1">
                    {o.orderType}{o.stopOrderType ? ` (${o.stopOrderType})` : ""}
                  </p>
                </div>
                <div className="space-y-0.5 text-right">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Qty / Price</span>
                  <p className="text-xs font-semibold tabular-nums text-foreground mt-1">
                    {o.qty} @ {o.price !== "0" ? `$${parseFloat(o.price).toFixed(2)}` : "Mkt"}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
