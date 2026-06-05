import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { BacktestMetrics, DirectionMetrics } from "./types";
import {
  formatUsd,
  formatPct,
  formatRatio,
  formatHours,
  formatInt,
  pnlColorClass,
  PNL_NEGATIVE_CLASS,
  PNL_POSITIVE_CLASS,
  TH_CLASS,
  TH_CLASS_RIGHT,
} from "./format";

/** A single headline metric tile. */
function MetricTile({
  label,
  value,
  sub,
  colorize,
  rawValue,
  colorClass,
}: {
  label: string;
  value: string;
  sub?: string;
  colorize?: boolean;
  rawValue?: number | null;
  /** Explicit color override (used when sign is fixed by meaning, e.g. drawdown). */
  colorClass?: string;
}) {
  const valueColor = colorClass
    ? colorClass
    : colorize
      ? pnlColorClass(rawValue)
      : "text-[var(--neu-text-strong)]";
  return (
    <Card size="sm" data-testid="metric-tile">
      <CardContent className="flex flex-col gap-1 pt-4">
        <span className="text-[0.72rem] font-medium uppercase tracking-wide text-[var(--neu-text-muted)]">
          {label}
        </span>
        <span className={cn("text-lg font-semibold tabular-nums", valueColor)}>{value}</span>
        {sub ? (
          <span className="text-[0.72rem] text-[var(--neu-text-muted)]">{sub}</span>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** One row in the per-direction breakdown table. */
function BreakdownRow({
  label,
  all,
  long,
  short,
  render,
  colorize,
}: {
  label: string;
  all: DirectionMetrics;
  long: DirectionMetrics;
  short: DirectionMetrics;
  render: (m: DirectionMetrics) => { text: string; raw?: number | null };
  colorize?: boolean;
}) {
  const cols: Array<{ key: string; m: DirectionMetrics }> = [
    { key: "all", m: all },
    { key: "long", m: long },
    { key: "short", m: short },
  ];
  return (
    <tr className="border-t border-[color:var(--neu-stroke-soft)]/60">
      <th
        scope="row"
        className="py-2 pr-4 text-left text-[0.8rem] font-medium text-[var(--neu-text-muted)]"
      >
        {label}
      </th>
      {cols.map(({ key, m }) => {
        const { text, raw } = render(m);
        return (
          <td
            key={key}
            className={cn(
              "py-2 pl-4 text-right text-[0.85rem] tabular-nums",
              colorize ? pnlColorClass(raw) : "text-[var(--neu-text-strong)]",
            )}
          >
            {text}
          </td>
        );
      })}
    </tr>
  );
}

export interface MetricsGridProps {
  metrics: BacktestMetrics;
  className?: string;
}

/**
 * TradingView-style metrics dashboard: a grid of headline KPI tiles plus a
 * per-direction (All / Long / Short) breakdown table.
 */
/** A zeroed DirectionMetrics, used when the backend omits a direction bucket so
 * the breakdown table degrades to N/A rather than crashing on destructure. */
const EMPTY_DIRECTION: DirectionMetrics = {
  total_trades: 0,
  winners: 0,
  losers: 0,
  net_profit: 0,
  win_rate: null,
  avg_trade: null,
  avg_win: null,
  avg_loss: null,
};

export function MetricsGrid({ metrics, className }: MetricsGridProps) {
  const m = metrics;
  // by_direction (or any of its buckets) may be absent on a malformed payload;
  // fall back to zeroed metrics instead of throwing inside the render.
  const bd = m.by_direction ?? { all: EMPTY_DIRECTION, long: EMPTY_DIRECTION, short: EMPTY_DIRECTION };
  const all = bd.all ?? EMPTY_DIRECTION;
  const long = bd.long ?? EMPTY_DIRECTION;
  const short = bd.short ?? EMPTY_DIRECTION;

  const headline: Array<{
    label: string;
    value: string;
    sub?: string;
    colorize?: boolean;
    rawValue?: number | null;
    colorClass?: string;
  }> = [
    {
      label: "Net Profit",
      value: formatUsd(m.net_profit, { sign: true }),
      sub: formatPct(m.net_profit_pct, { sign: true }),
      colorize: true,
      rawValue: m.net_profit,
    },
    {
      label: "Final Equity",
      value: formatUsd(m.final_equity),
    },
    {
      label: "Total Trades",
      value: formatInt(m.total_trades),
      sub: `${formatInt(m.winners)}W / ${formatInt(m.losers)}L`,
    },
    {
      label: "Win Rate",
      value: formatPct(m.win_rate),
    },
    {
      label: "Profit Factor",
      value: formatRatio(m.profit_factor, { infinite: true }),
    },
    {
      label: "Max Drawdown",
      value: formatPct(m.max_dd_pct),
      sub: formatUsd(-Math.abs(m.max_dd_usd)),
      colorClass: PNL_NEGATIVE_CLASS,
    },
    {
      label: "Sharpe",
      value: formatRatio(m.sharpe),
    },
    {
      label: "Sortino",
      value: formatRatio(m.sortino),
    },
    {
      label: "CAGR",
      value: formatPct(m.cagr, { sign: true }),
      colorize: true,
      rawValue: m.cagr,
    },
    {
      label: "Calmar",
      value: formatRatio(m.calmar),
    },
    {
      label: "Expectancy",
      value: formatUsd(m.expectancy, { sign: true }),
      colorize: true,
      rawValue: m.expectancy,
    },
    {
      label: "Recovery Factor",
      value: formatRatio(m.recovery_factor),
    },
  ];

  const buyHold =
    m.buy_hold_return_pct != null || m.excess_return != null
      ? [
          {
            label: "Buy & Hold",
            value: formatPct(m.buy_hold_return_pct, { sign: true }),
            colorize: true,
            rawValue: m.buy_hold_return_pct,
          },
          {
            label: "Excess Return",
            value: formatPct(m.excess_return, { sign: true }),
            sub: "vs buy & hold",
            colorize: true,
            rawValue: m.excess_return,
          },
        ]
      : [];

  return (
    <div className={cn("flex flex-col gap-6", className)} data-testid="metrics-grid">
      {/* Headline KPI tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {[...headline, ...buyHold].map((tile) => (
          <MetricTile key={tile.label} {...tile} />
        ))}
      </div>

      {/* Per-direction breakdown */}
      <Card>
        <CardContent className="overflow-x-auto pt-5">
          <table className="w-full border-collapse" data-testid="direction-breakdown">
            <caption className="sr-only">Per-direction metric breakdown</caption>
            <thead>
              <tr>
                <th scope="col" className={cn("pb-2 text-left", TH_CLASS)}>Metric</th>
                <th scope="col" className={cn("pb-2 pl-4", TH_CLASS_RIGHT)}>All</th>
                <th scope="col" className={cn("pb-2 pl-4", TH_CLASS_RIGHT)}>Long</th>
                <th scope="col" className={cn("pb-2 pl-4", TH_CLASS_RIGHT)}>Short</th>
              </tr>
            </thead>
            <tbody>
              <BreakdownRow
                label="Total Trades"
                all={all}
                long={long}
                short={short}
                render={(d) => ({ text: formatInt(d.total_trades) })}
              />
              <BreakdownRow
                label="Winners"
                all={all}
                long={long}
                short={short}
                render={(d) => ({ text: formatInt(d.winners) })}
              />
              <BreakdownRow
                label="Losers"
                all={all}
                long={long}
                short={short}
                render={(d) => ({ text: formatInt(d.losers) })}
              />
              <BreakdownRow
                label="Net Profit"
                all={all}
                long={long}
                short={short}
                colorize
                render={(d) => ({
                  text: formatUsd(d.net_profit, { sign: true }),
                  raw: d.net_profit,
                })}
              />
              <BreakdownRow
                label="Win Rate"
                all={all}
                long={long}
                short={short}
                render={(d) => ({ text: formatPct(d.win_rate) })}
              />
              <BreakdownRow
                label="Avg Trade"
                all={all}
                long={long}
                short={short}
                colorize
                render={(d) => ({
                  text: formatUsd(d.avg_trade, { sign: true }),
                  raw: d.avg_trade,
                })}
              />
              <BreakdownRow
                label="Avg Win"
                all={all}
                long={long}
                short={short}
                colorize
                render={(d) => ({ text: formatUsd(d.avg_win, { sign: true }), raw: d.avg_win })}
              />
              <BreakdownRow
                label="Avg Loss"
                all={all}
                long={long}
                short={short}
                colorize
                render={(d) => ({ text: formatUsd(d.avg_loss, { sign: true }), raw: d.avg_loss })}
              />
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Secondary stats strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <MetricTile label="Gross Profit" value={formatUsd(m.gross_profit, { sign: true })} colorClass={PNL_POSITIVE_CLASS} />
        <MetricTile label="Gross Loss" value={formatUsd(-Math.abs(m.gross_loss))} colorClass={PNL_NEGATIVE_CLASS} />
        <MetricTile label="Largest Win" value={formatUsd(m.largest_win, { sign: true })} colorize rawValue={m.largest_win} />
        <MetricTile label="Largest Loss" value={formatUsd(m.largest_loss, { sign: true })} colorize rawValue={m.largest_loss} />
        <MetricTile label="Max Consec. Wins" value={formatInt(m.max_consecutive_wins)} sub={formatUsd(m.max_consecutive_wins_usd, { sign: true })} />
        <MetricTile label="Max Consec. Losses" value={formatInt(m.max_consecutive_losses)} sub={formatUsd(m.max_consecutive_losses_usd, { sign: true })} />
        <MetricTile label="Avg Drawdown" value={formatPct(m.avg_dd_pct)} colorClass={PNL_NEGATIVE_CLASS} />
        <MetricTile label="Max DD Duration" value={formatHours(m.max_dd_duration_hours)} />
        <MetricTile label="Avg Trade Duration" value={formatHours(m.avg_trade_duration_hours)} />
        <MetricTile label="Avg Winner Duration" value={formatHours(m.avg_winner_duration_hours)} />
        <MetricTile label="Avg Loser Duration" value={formatHours(m.avg_loser_duration_hours)} />
        <MetricTile label="Max Trade Duration" value={formatHours(m.max_trade_duration_hours)} />
        <MetricTile label="Total Commission" value={formatUsd(-Math.abs(m.total_commission))} colorClass={PNL_NEGATIVE_CLASS} />
      </div>
    </div>
  );
}
