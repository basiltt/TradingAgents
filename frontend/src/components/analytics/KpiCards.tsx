import type { PerformanceKpis } from "./performanceTypes";
import { formatUsd, formatPct, formatRatio, formatHours, formatInt, DASH, pnlColorClass } from "@/lib/format";

interface Props {
  kpis: PerformanceKpis;
  /** When true (caller passes meta.trading_days < 10) collapse the Risk group to a notice. */
  lowDataNotice?: boolean;
}

type Tile = {
  label: string;
  value: string;          // pre-formatted (DASH for null)
  numeric: number | null; // for color + sign aria
  kind: "usd" | "pct" | "ratio" | "int" | "hours";
};

function colorFor(v: number | null, neutral = false): string {
  if (v == null || neutral) return "text-[var(--neu-text-strong)]";
  return pnlColorClass(v);
}

function ariaFor(label: string, v: number | null, kind: Tile["kind"]): string {
  if (v == null) return `${label}: not available`;
  const dir = v > 0 ? "positive" : v < 0 ? "negative" : "neutral";
  const unit = kind === "usd" ? " USDT" : kind === "pct" ? " percent" : "";
  return `${label}: ${v}${unit}, ${dir}`;
}

function TileCard({ tile }: { tile: Tile }) {
  return (
    <div
      role="group"
      aria-label={ariaFor(tile.label, tile.numeric, tile.kind)}
      className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-3 sm:p-4"
    >
      <div className={`text-base sm:text-xl font-black tracking-tight tabular-nums ${colorFor(tile.numeric, tile.kind === "int")}`}>
        {tile.value}
      </div>
      <div className="mt-0.5 text-[9px] sm:text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">
        {tile.label}
      </div>
    </div>
  );
}

function f(value: number | null | undefined, kind: Tile["kind"], opts?: { sign?: boolean }): string {
  if (value == null) return DASH;
  switch (kind) {
    case "usd": return formatUsd(value, { sign: opts?.sign });
    case "pct": return formatPct(value, { sign: opts?.sign });
    case "ratio": return formatRatio(value);
    case "int": return formatInt(value);
    case "hours": return formatHours(value);
  }
}

function Group({ title, tiles }: { title: string; tiles: Tile[] }) {
  return (
    <section>
      <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">{title}</h3>
      <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-3 lg:grid-cols-5">
        {tiles.map((t) => <TileCard key={t.label} tile={t} />)}
      </div>
    </section>
  );
}

export function KpiCards({ kpis, lowDataNotice = false }: Props) {
  const quality: Tile[] = [
    { label: "Win Rate", value: f(kpis.win_rate, "pct"), numeric: kpis.win_rate, kind: "pct" },
    { label: "Profit Factor", value: f(kpis.profit_factor, "ratio"), numeric: kpis.profit_factor, kind: "ratio" },
    { label: "Expectancy", value: f(kpis.expectancy, "usd", { sign: true }), numeric: kpis.expectancy, kind: "usd" },
    { label: "Avg Win", value: f(kpis.avg_win, "usd", { sign: true }), numeric: kpis.avg_win, kind: "usd" },
    { label: "Avg Loss", value: f(kpis.avg_loss, "usd", { sign: true }), numeric: kpis.avg_loss, kind: "usd" },
    { label: "Win/Loss", value: f(kpis.avg_win_loss_ratio, "ratio"), numeric: kpis.avg_win_loss_ratio, kind: "ratio" },
  ];
  const returns: Tile[] = [
    { label: "Net P&L", value: f(kpis.net_pnl, "usd", { sign: true }), numeric: kpis.net_pnl, kind: "usd" },
    { label: "Return", value: f(kpis.total_return_pct, "pct", { sign: true }), numeric: kpis.total_return_pct, kind: "pct" },
    { label: "Gross P&L", value: f(kpis.realized_pnl_gross, "usd", { sign: true }), numeric: kpis.realized_pnl_gross, kind: "usd" },
  ];
  const consistency: Tile[] = [
    { label: "Best Trade", value: f(kpis.best_trade, "usd", { sign: true }), numeric: kpis.best_trade, kind: "usd" },
    { label: "Worst Trade", value: f(kpis.worst_trade, "usd", { sign: true }), numeric: kpis.worst_trade, kind: "usd" },
    { label: "Win Streak", value: f(kpis.max_consecutive_wins, "int"), numeric: null, kind: "int" },
    { label: "Loss Streak", value: f(kpis.max_consecutive_losses, "int"), numeric: null, kind: "int" },
    { label: "Avg Hold", value: f(kpis.avg_hold_time_hours, "hours"), numeric: null, kind: "hours" },
  ];
  const risk: Tile[] = [
    { label: "Max Drawdown", value: kpis.max_drawdown_pct != null ? f(kpis.max_drawdown_pct, "pct") : f(kpis.max_drawdown_abs, "usd"), numeric: kpis.max_drawdown_pct ?? kpis.max_drawdown_abs, kind: kpis.max_drawdown_pct != null ? "pct" : "usd" },
    { label: "Sharpe", value: f(kpis.sharpe_ratio, "ratio"), numeric: kpis.sharpe_ratio, kind: "ratio" },
    { label: "Sortino", value: f(kpis.sortino_ratio, "ratio"), numeric: kpis.sortino_ratio, kind: "ratio" },
    { label: "Calmar", value: f(kpis.calmar_ratio, "ratio"), numeric: kpis.calmar_ratio, kind: "ratio" },
    { label: "DD Duration", value: kpis.drawdown_duration_days != null ? `${kpis.drawdown_duration_days}d` : DASH, numeric: null, kind: "int" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Group title="Quality" tiles={quality} />
      <Group title="Returns" tiles={returns} />
      <Group title="Consistency" tiles={consistency} />
      {lowDataNotice ? (
        <section>
          <h3 className="mb-2 text-[10px] uppercase tracking-wider font-extrabold text-[var(--neu-text-soft)]">Risk</h3>
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-4 text-sm text-[var(--neu-text-soft)]">
            Risk metrics (Sharpe, Sortino, Calmar) need ≥10 trading days of history.
          </div>
        </section>
      ) : (
        <Group title="Risk" tiles={risk} />
      )}
    </div>
  );
}
