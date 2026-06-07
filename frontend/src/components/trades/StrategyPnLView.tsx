import { memo } from "react";
import type { StrategyDirectionStats } from "./types";
import { StrategyChip, type StrategyKind } from "./StrategyChip";

interface StrategyPnLViewProps {
  rows: StrategyDirectionStats[] | undefined;
  loading?: boolean;
}

function fmtPnl(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function fmtHold(mins: number): string {
  if (!mins || mins <= 0) return "—";
  if (mins < 60) return `${Math.round(mins)}m`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}

/**
 * Per-strategy × direction PnL table (FR-052/AC-016). Renders the `by_strategy`
 * breakdown from GET /trades/stats?by_strategy=true as strategy × direction ×
 * {PnL, win-rate, count, avg-hold}. Empty/absent data shows an explanatory note so
 * the tab is informative even before F2 produces any mean-reversion trades.
 */
export const StrategyPnLView = memo(function StrategyPnLView({ rows, loading }: StrategyPnLViewProps) {
  if (loading) {
    return <div className="text-sm text-muted-foreground py-6 text-center" data-testid="strategy-pnl-loading">Loading strategy breakdown…</div>;
  }
  if (!rows || rows.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-6 text-center" data-testid="strategy-pnl-empty">
        No closed trades yet for a per-strategy breakdown. Trend and mean-reversion
        results will appear here once positions close.
      </div>
    );
  }
  return (
    <table className="w-full text-sm" data-testid="strategy-pnl-table">
      <thead>
        <tr className="text-[11px] uppercase tracking-wider text-muted-foreground text-left">
          <th className="py-2 pr-4 font-medium">Strategy</th>
          <th className="py-2 pr-4 font-medium">Dir</th>
          <th className="py-2 pr-4 font-medium text-right">Trades</th>
          <th className="py-2 pr-4 font-medium text-right">Win&nbsp;%</th>
          <th className="py-2 pr-4 font-medium text-right">Total&nbsp;PnL</th>
          <th className="py-2 pr-4 font-medium text-right">Avg&nbsp;PnL</th>
          <th className="py-2 font-medium text-right">Avg&nbsp;Hold</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.strategy_kind}:${r.direction}`} className="border-t border-border/40" data-testid="strategy-pnl-row">
            <td className="py-2 pr-4"><StrategyChip kind={r.strategy_kind as StrategyKind} /></td>
            <td className="py-2 pr-4 capitalize">{r.direction}</td>
            <td className="py-2 pr-4 text-right tabular-nums">{r.count}</td>
            <td className="py-2 pr-4 text-right tabular-nums">{(r.win_rate * 100).toFixed(1)}</td>
            <td className={`py-2 pr-4 text-right tabular-nums font-medium ${r.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {fmtPnl(r.total_pnl)}
            </td>
            <td className={`py-2 pr-4 text-right tabular-nums ${r.avg_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {fmtPnl(r.avg_pnl)}
            </td>
            <td className="py-2 text-right tabular-nums text-muted-foreground">{fmtHold(r.avg_hold_minutes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
});
