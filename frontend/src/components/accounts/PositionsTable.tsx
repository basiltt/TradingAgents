import type { Position } from "@/api/client";
import { Badge } from "@/components/ui/badge";

interface PositionsTableProps {
  positions: Position[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return <p className="text-muted-foreground text-center py-8">No open positions</p>;
  }

  return (
    <div className="rounded border overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted">
          <tr>
            <th className="text-left p-2">Symbol</th>
            <th className="text-left p-2">Side</th>
            <th className="text-right p-2">Size</th>
            <th className="text-right p-2">Entry</th>
            <th className="text-right p-2">Mark</th>
            <th className="text-right p-2">PnL</th>
            <th className="text-right p-2">Leverage</th>
            <th className="text-right p-2">Liq. Price</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p, i) => {
            const pnl = parseFloat(p.unrealisedPnl);
            const mark = parseFloat(p.markPrice);
            const liq = parseFloat(p.liqPrice);
            const distToLiq = liq > 0 ? Math.abs((mark - liq) / mark * 100) : 999;
            const liqWarning = distToLiq <= 5 ? "text-red-600 font-bold" : distToLiq <= 15 ? "text-amber-600" : "";
            return (
              <tr key={i} className="border-t">
                <td className="p-2 font-medium">{p.symbol}</td>
                <td className="p-2">
                  <Badge variant={p.side === "Buy" ? "default" : "destructive"} className="text-xs">
                    {p.side === "Buy" ? "Long" : "Short"}
                  </Badge>
                </td>
                <td className="p-2 text-right">{p.size}</td>
                <td className="p-2 text-right">{parseFloat(p.avgPrice).toFixed(2)}</td>
                <td className="p-2 text-right">{mark.toFixed(2)}</td>
                <td className={`p-2 text-right ${pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                  ${pnl.toFixed(2)}
                </td>
                <td className="p-2 text-right">{p.leverage}x</td>
                <td className={`p-2 text-right ${liqWarning}`}>
                  {liq > 0 ? `$${liq.toFixed(2)}` : "—"}
                  {distToLiq <= 15 && <span className="ml-1 text-xs">({distToLiq.toFixed(1)}%)</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
