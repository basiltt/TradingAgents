export interface TradeRow {
  id: number;
  closed_at: string;
  symbol: string;
  direction: string;
  confidence_score: number;
  confidence_tier: string;
  regime_at_entry: string;
  realized_pnl_pct: number;
  hold_duration_minutes: number;
  close_reason: string;
  benchmark_bnh_pnl_pct: number;
  is_win: boolean;
}

interface Props {
  trades: TradeRow[];
}

export function TradeTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">No closed trades yet.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60">
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Date</th>
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Symbol</th>
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Dir</th>
            <th className="section-eyebrow py-2 pr-4 text-right font-semibold">Conf</th>
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Tier</th>
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Regime</th>
            <th className="section-eyebrow py-2 pr-4 text-right font-semibold">PnL %</th>
            <th className="section-eyebrow py-2 pr-4 text-right font-semibold">Hold (m)</th>
            <th className="section-eyebrow py-2 pr-4 text-left font-semibold">Close Reason</th>
            <th className="section-eyebrow py-2 text-right font-semibold">vs B&H</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const pnlColor = t.realized_pnl_pct > 0 ? "text-emerald-500" : t.realized_pnl_pct < 0 ? "text-destructive" : "text-foreground";
            const vsBnh = t.realized_pnl_pct - t.benchmark_bnh_pnl_pct;
            const vsBnhColor = vsBnh > 0 ? "text-emerald-500" : vsBnh < 0 ? "text-destructive" : "text-foreground";
            return (
              <tr key={t.id} className="border-b border-border/30 hover:bg-muted/20 transition-colors">
                <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap">
                  {new Date(t.closed_at).toLocaleDateString()}
                </td>
                <td className="py-2 pr-4 font-medium">{t.symbol}</td>
                <td className="py-2 pr-4">
                  <span className={`text-xs font-bold uppercase ${t.direction === "long" ? "text-emerald-500" : "text-destructive"}`}>
                    {t.direction}
                  </span>
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">{(t.confidence_score * 100).toFixed(0)}%</td>
                <td className="py-2 pr-4 text-muted-foreground">{t.confidence_tier}</td>
                <td className="py-2 pr-4 text-muted-foreground">{t.regime_at_entry}</td>
                <td className={`py-2 pr-4 text-right tabular-nums font-semibold ${pnlColor}`}>
                  {t.realized_pnl_pct >= 0 ? "+" : ""}{t.realized_pnl_pct.toFixed(2)}%
                </td>
                <td className="py-2 pr-4 text-right tabular-nums text-muted-foreground">
                  {Math.round(t.hold_duration_minutes)}
                </td>
                <td className="py-2 pr-4 text-muted-foreground text-xs">{t.close_reason}</td>
                <td className={`py-2 text-right tabular-nums text-xs ${vsBnhColor}`}>
                  {vsBnh >= 0 ? "+" : ""}{vsBnh.toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
