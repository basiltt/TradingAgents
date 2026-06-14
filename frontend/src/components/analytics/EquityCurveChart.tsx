import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceDot, ResponsiveContainer } from "recharts";
import { useId } from "react";
import type { CurvePoint, EquityNow } from "./performanceTypes";

interface Props {
  data: CurvePoint[];
  /** optional absolute-equity offset D for the secondary "your equity" axis */
  startingEquity?: number | null;
  equityNow?: EquityNow | null;
}

export function EquityCurveChart({ data, startingEquity, equityNow }: Props) {
  const gradId = useId().replace(/:/g, "");
  if (data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-[var(--neu-text-soft)]">
        No closed trades in this range
      </div>
    );
  }
  const rows = data.map((p) => ({
    t: p.t,
    cum_pnl: Math.round(p.cum_pnl * 100) / 100,
  }));
  // Explicit, affine-related domains for the two y-axes: the right "equity" axis is the
  // left "cum P&L" axis shifted by D. Setting both explicitly (rather than binding an
  // invisible equity series) keeps them aligned AND avoids polluting the shared tooltip
  // with a phantom "equity" row. The eq domain is widened to include the live equity-now
  // marker so the ReferenceDot is never clipped.
  const cums = rows.map((r) => r.cum_pnl);
  // reduce (not Math.max(...spread)) so an unbounded-length window can't hit the JS
  // arg-count RangeError; the cumulative curve grows over time.
  let cMin = 0, cMax = 0;
  for (const c of cums) { if (c < cMin) cMin = c; if (c > cMax) cMax = c; }
  const pad = (cMax - cMin) * 0.05 || 1;
  const pnlMin = cMin - pad;
  const pnlMax = cMax + pad;
  let eqDomain: [number, number] | undefined;
  if (startingEquity != null) {
    let lo = pnlMin + startingEquity;
    let hi = pnlMax + startingEquity;
    if (equityNow) { lo = Math.min(lo, equityNow.equity); hi = Math.max(hi, equityNow.equity); }
    eqDomain = [lo, hi];
  }
  // anchor the "now" marker to the rightmost real category (its x is a band, not "now")
  const lastT = rows[rows.length - 1]?.t;
  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={rows}>
        <defs>
          <linearGradient id={`eq-${gradId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--neu-accent)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--neu-accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--neu-stroke-soft)" strokeDasharray="3 3" />
        <XAxis dataKey="t" tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} minTickGap={32} />
        <YAxis yAxisId="pnl" domain={[pnlMin, pnlMax]} tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        {eqDomain && (
          <YAxis yAxisId="eq" orientation="right" domain={eqDomain} tick={{ fill: "var(--neu-text-soft)", fontSize: 11 }} />
        )}
        <Tooltip />
        <Area
          yAxisId="pnl"
          type="monotone"
          dataKey="cum_pnl"
          stroke="var(--neu-accent)"
          fill={`url(#eq-${gradId})`}
        />
        {equityNow && eqDomain && lastT != null && (
          <ReferenceDot yAxisId="eq" x={lastT} y={equityNow.equity} r={4} fill="var(--neu-accent)" />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}
