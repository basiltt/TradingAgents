import type { Position } from "@/api/client";

interface PositionsTableProps {
  positions: Position[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-12 text-center">
        <div className="w-12 h-12 rounded-2xl bg-muted/50 flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        </div>
        <p className="text-sm text-muted-foreground/60">No open positions</p>
      </div>
    );
  }

  const totalPnl = positions.reduce((s, p) => s + parseFloat(p.unrealisedPnl), 0);
  const longCount = positions.filter((p) => p.side === "Buy").length;
  const shortCount = positions.length - longCount;

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="flex items-center gap-6 px-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground/50 uppercase tracking-wider font-semibold">Total PnL</span>
          <span className={`text-sm font-bold tabular-nums ${totalPnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
            ${totalPnl.toFixed(2)}
          </span>
        </div>
        <div className="w-px h-4 bg-border/30" />
        <div className="flex items-center gap-3">
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-emerald-500/[0.08] text-emerald-500 border border-emerald-500/20 tabular-nums">
            {longCount} Long
          </span>
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-red-500/[0.08] text-red-500 border border-red-500/20 tabular-nums">
            {shortCount} Short
          </span>
        </div>
      </div>

      <div className="rounded-2xl border border-border/40 bg-card overflow-hidden overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/30">
              <th className="text-left px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Symbol</th>
              <th className="text-left px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Side</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Size</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Entry</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Mark</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">PnL</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Leverage</th>
              <th className="text-right px-5 py-3.5 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Liq. Price</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => {
              const pnl = parseFloat(p.unrealisedPnl);
              const mark = parseFloat(p.markPrice);
              const liq = parseFloat(p.liqPrice);
              const distToLiq = liq > 0 ? Math.abs((mark - liq) / mark * 100) : 999;
              const isLong = p.side === "Buy";

              return (
                <tr key={i} className="border-b border-border/20 last:border-0 hover:bg-muted/[0.04] transition-colors">
                  <td className="px-5 py-3.5">
                    <span className="font-semibold">{p.symbol}</span>
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={`text-[10px] px-2.5 py-1 rounded-full font-bold uppercase tracking-wider border ${
                      isLong
                        ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/[0.08]"
                        : "border-red-500/30 text-red-500 bg-red-500/[0.08]"
                    }`}>
                      {isLong ? "Long" : "Short"}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-right font-medium tabular-nums">{p.size}</td>
                  <td className="px-5 py-3.5 text-right tabular-nums text-muted-foreground">{parseFloat(p.avgPrice).toFixed(2)}</td>
                  <td className="px-5 py-3.5 text-right font-medium tabular-nums">{mark.toFixed(2)}</td>
                  <td className={`px-5 py-3.5 text-right font-semibold tabular-nums ${pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                    {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <span className="text-xs px-2 py-0.5 rounded-md bg-muted/50 font-medium tabular-nums">{p.leverage}x</span>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {liq > 0 ? (
                      <div className="flex items-center justify-end gap-2">
                        <span className={`font-medium tabular-nums ${
                          distToLiq <= 5 ? "text-red-500 font-bold" : distToLiq <= 15 ? "text-amber-500" : ""
                        }`}>
                          ${liq.toFixed(2)}
                        </span>
                        {distToLiq <= 15 && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold tabular-nums ${
                            distToLiq <= 5
                              ? "bg-red-500/10 text-red-500 border border-red-500/20"
                              : "bg-amber-500/10 text-amber-500 border border-amber-500/20"
                          }`}>
                            {distToLiq.toFixed(1)}%
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted-foreground/40">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
