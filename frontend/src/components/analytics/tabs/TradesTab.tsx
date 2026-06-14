import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { useTradesBreakdown, useTradesPage } from "../hooks/usePerformance";
import { formatUsd, formatPct, pnlColorClass, DASH } from "@/lib/format";
import type { PerformanceTimeframe, TradeRow } from "../performanceTypes";

interface Props {
  scope: string;
  timeframe: PerformanceTimeframe;
}

const CLOSE_REASON_LABELS: Record<string, string> = {
  take_profit: "Take Profit",
  stop_loss: "Stop Loss",
  liquidation: "Liquidation",
  adl: "ADL",
  external: "External",
  manual_single: "Manual",
  manual_close_all: "Manual",
  rule_triggered: "Rule",
  cycle_target: "Cycle",
  cycle_drawdown: "Cycle",
};
function reasonLabel(code: string | null): string {
  if (!code) return "Unknown";
  return CLOSE_REASON_LABELS[code] ?? code.replace(/_/g, " ");
}

const DONUT_COLORS = ["var(--neu-success)", "var(--neu-danger)", "var(--neu-accent)", "#8b5cf6", "#06b6d4", "#f59e0b", "#64748b", "#ec4899"];

function PnlCell({ value }: { value: number | null }) {
  if (value == null) return <span className="text-[var(--neu-text-soft)]">{DASH}</span>;
  return (
    <span className={pnlColorClass(value)} aria-label={`${value >= 0 ? "profit" : "loss"} ${Math.abs(value)} USDT`}>
      {formatUsd(value, { sign: true })}
    </span>
  );
}

export function TradesTab({ scope, timeframe }: Props) {
  const { data: bd, isLoading: bdLoading } = useTradesBreakdown(scope, timeframe);
  const { data: pages, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useTradesPage(scope, timeframe, "net_pnl", "desc");

  if (bdLoading || !bd) {
    return <div className="h-40 animate-pulse rounded-[var(--neu-radius-md)] neu-surface-base" />;
  }

  const rows: TradeRow[] = (pages?.pages ?? []).flatMap((p) => p.rows);
  const donut = bd.by_close_reason.map((r) => ({ name: reasonLabel(r.reason), value: r.count }));

  return (
    <div className="flex flex-col gap-4">
      {bd.meta.strategy_legacy_approximate && (
        <p className="text-xs text-[var(--neu-warning,#f59e0b)]">
          Note: legacy strategy labels are approximate — trades predating strategy tracking default to “trend”.
        </p>
      )}

      {/* Per-strategy paired cards */}
      <div className="grid gap-3 md:grid-cols-2">
        {bd.by_strategy.map((s) => (
          <div key={s.strategy} className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
            <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">{s.strategy}</div>
            <div className="mt-1 text-lg font-black tabular-nums"><PnlCell value={s.pnl} /></div>
            <div className="text-xs text-[var(--neu-text-soft)]">{s.trades} trades · {s.win_rate != null ? formatPct(s.win_rate) : DASH} win</div>
          </div>
        ))}
      </div>

      {/* Per-symbol leaderboard */}
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">By Symbol</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--neu-text-soft)]">
                <th className="p-1">Symbol</th><th className="p-1 text-right">Trades</th>
                <th className="p-1 text-right">Win&nbsp;Rate</th><th className="p-1 text-right">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {bd.by_symbol.map((r) => (
                <tr key={r.symbol} className="border-t border-[var(--neu-stroke-soft)]">
                  <td className="p-1 font-medium">{r.symbol}</td>
                  <td className="p-1 text-right tabular-nums">{r.trades}</td>
                  <td className="p-1 text-right tabular-nums">{r.win_rate != null ? formatPct(r.win_rate) : DASH}</td>
                  <td className="p-1 text-right tabular-nums"><PnlCell value={r.pnl} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Close-reason donut */}
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Close Reason</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={donut} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                {donut.map((_, i) => <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </section>
        {/* P&L distribution */}
        <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
          <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">P&amp;L Distribution</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bd.pnl_distribution}>
              <XAxis dataKey="bucket" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="var(--neu-accent)" />
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      {/* Raw trades table */}
      <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4">
        <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Trades</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--neu-text-soft)]">
                <th className="p-1">Symbol</th><th className="p-1">Side</th>
                <th className="p-1 text-right">Net P&amp;L</th><th className="p-1 text-right">%</th>
                <th className="p-1">Reason</th><th className="p-1 text-right">Hold</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t: TradeRow) => (
                <tr key={t.id} className="border-t border-[var(--neu-stroke-soft)]">
                  <td className="p-1 font-medium">{t.symbol}</td>
                  <td className="p-1">{t.side}</td>
                  <td className="p-1 text-right tabular-nums"><PnlCell value={t.net_pnl} /></td>
                  <td className="p-1 text-right tabular-nums">{t.net_pnl_pct != null ? formatPct(t.net_pnl_pct, { sign: true }) : DASH}</td>
                  <td className="p-1">{reasonLabel(t.close_reason)}</td>
                  <td className="p-1 text-right tabular-nums">{t.hold_hours != null ? `${t.hold_hours.toFixed(1)}h` : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hasNextPage && (
          <button
            type="button"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            className="mt-2 rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-raised px-3 py-1 text-sm disabled:opacity-50"
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}
      </section>
    </div>
  );
}
