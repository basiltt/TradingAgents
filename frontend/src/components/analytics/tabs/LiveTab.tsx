import { usePerformanceLive } from "../hooks/usePerformance";
import { formatUsd, formatPct, pnlColorClass, DASH } from "@/lib/format";
import type { LivePosition, AccountTile, SectorConcentration } from "../performanceTypes";

interface Props {
  scope: string;
}

export function LiveTab({ scope }: Props) {
  const { data, isLoading } = usePerformanceLive(scope);

  if (isLoading || !data) {
    return <div className="h-40 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />;
  }

  return (
    <div className="flex flex-col gap-4">
      {data.degraded && (
        <div className="rounded-[var(--neu-radius-md)] border border-[var(--neu-warning,#f59e0b)] p-3 text-sm text-[var(--neu-warning,#f59e0b)]">
          Some accounts could not be loaded — showing partial live data.
        </div>
      )}

      {/* Account tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {data.account_tiles.map((t: AccountTile) => (
          <div key={t.account_id} className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">{t.label}</span>
              <span className="text-[9px] uppercase text-[var(--neu-text-soft)]">{t.type ?? ""}</span>
            </div>
            <div className="mt-1 text-lg font-black tabular-nums text-[var(--neu-text-strong)]">
              {t.equity != null ? formatUsd(t.equity) : DASH}
            </div>
            <div className="text-xs text-[var(--neu-text-soft)]">
              {t.positions_count} open · today {t.today_pnl != null ? formatUsd(t.today_pnl, { sign: true }) : DASH}
            </div>
            {t.error && <div className="mt-1 text-xs text-[var(--neu-danger)]">{t.error}</div>}
          </div>
        ))}
      </div>

      {/* Open positions */}
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Open Positions</h3>
        {data.positions.length === 0 ? (
          <p className="text-sm text-[var(--neu-text-soft)]">No open positions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[var(--neu-text-soft)]">
                  <th className="p-1">Symbol</th><th className="p-1">Side</th>
                  <th className="p-1 text-right">Size</th><th className="p-1 text-right">Lev</th>
                  <th className="p-1 text-right">Entry</th><th className="p-1 text-right">uPnL</th>
                  <th className="p-1 text-right">%</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((p: LivePosition, i: number) => (
                  <tr key={`${p.account_id}-${p.symbol}-${i}`} className="border-t border-[var(--neu-border)]">
                    <td className="p-1 font-medium">{p.symbol}</td>
                    <td className="p-1">{p.side}</td>
                    <td className="p-1 text-right tabular-nums">{p.size}</td>
                    <td className="p-1 text-right tabular-nums">{p.leverage}x</td>
                    <td className="p-1 text-right tabular-nums">{p.entry}</td>
                    <td className="p-1 text-right tabular-nums">
                      <span className={pnlColorClass(p.unrealized_pnl)} aria-label={`${p.unrealized_pnl >= 0 ? "profit" : "loss"} ${Math.abs(p.unrealized_pnl)} USDT`}>
                        {formatUsd(p.unrealized_pnl, { sign: true })}
                      </span>
                    </td>
                    <td className="p-1 text-right tabular-nums">{p.unrealized_pnl_pct != null ? formatPct(p.unrealized_pnl_pct, { sign: true }) : DASH}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Sector concentration */}
      {data.sector_concentration.length > 0 && (
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Sector Concentration</h3>
          <div className="flex flex-col gap-2">
            {data.sector_concentration.map((s: SectorConcentration) => (
              <div key={s.sector}>
                <div className="flex justify-between text-xs text-[var(--neu-text-soft)]">
                  <span>{s.sector} ({s.positions})</span>
                  <span className="tabular-nums">{formatPct(s.exposure_pct)}</span>
                </div>
                <div className="mt-0.5 h-2 rounded-full neu-surface-base neu-surface-inset overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(s.exposure_pct, 100)}%`, background: "var(--neu-accent)" }} />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
