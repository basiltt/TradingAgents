import type { WalletBalance } from "@/api/client";

interface WalletPanelProps {
  wallet: WalletBalance;
}

export function WalletPanel({ wallet }: WalletPanelProps) {
  if (!wallet.coin.length) {
    return (
      <div className="rounded-2xl border border-border/40 bg-card p-8 text-center">
        <div className="w-10 h-10 rounded-[calc(var(--radius)*1.2)] bg-muted/50 flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20 12V8H6a2 2 0 01-2-2c0-1.1.9-2 2-2h12v4" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6v12a2 2 0 002 2h14v-4" />
          </svg>
        </div>
        <p className="text-sm text-muted-foreground/60">No wallet data</p>
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
                <th className="text-left px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Coin</th>
                <th className="text-right px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Balance</th>
                <th className="text-right px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Equity</th>
                <th className="text-right px-4 py-3 text-[11px] text-muted-foreground/60 uppercase tracking-wider font-semibold">Unrealised PnL</th>
              </tr>
            </thead>
            <tbody>
              {wallet.coin.map((c, i) => {
                const upl = parseFloat(c.unrealisedPnl || "0");
                return (
                  <tr key={i} className="border-b border-border/20 last:border-0 hover:bg-muted/[0.04] transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-xl bg-primary/10 ring-1 ring-inset ring-primary/20 flex items-center justify-center">
                          <span className="text-xs font-bold text-primary">{c.coin.charAt(0)}</span>
                        </div>
                        <span className="font-semibold">{c.coin}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums">{parseFloat(c.walletBalance || "0").toFixed(4)}</td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums">{parseFloat(c.equity || "0").toFixed(4)}</td>
                    <td className={`px-4 py-3 text-right font-semibold tabular-nums ${upl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                      {upl >= 0 ? "+" : ""}{upl.toFixed(4)}
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
        {wallet.coin.map((c, i) => {
          const upl = parseFloat(c.unrealisedPnl || "0");
          return (
            <div key={i} className="rounded-2xl border border-border/40 bg-card p-4 space-y-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-primary/10 ring-1 ring-inset ring-primary/20 flex items-center justify-center">
                  <span className="text-xs font-bold text-primary">{c.coin.charAt(0)}</span>
                </div>
                <span className="font-bold">{c.coin}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border/10">
                <div className="space-y-0.5">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Balance</span>
                  <p className="text-xs font-medium tabular-nums text-foreground">{parseFloat(c.walletBalance || "0").toFixed(4)}</p>
                </div>
                <div className="space-y-0.5">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Equity</span>
                  <p className="text-xs font-medium tabular-nums text-foreground">{parseFloat(c.equity || "0").toFixed(4)}</p>
                </div>
                <div className="space-y-0.5 text-right">
                  <span className="text-[10px] text-muted-foreground/60 uppercase font-semibold">Unrealised PnL</span>
                  <p className={`text-xs font-semibold tabular-nums ${upl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                    {upl >= 0 ? "+" : ""}{upl.toFixed(4)}
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
