import type { PnlSummary } from "@/api/client";

interface PnLPanelProps {
  pnlSummary: PnlSummary | null;
}

export function PnLPanel({ pnlSummary }: PnLPanelProps) {
  if (!pnlSummary) {
    return <p className="text-muted-foreground text-center py-8">No PnL data available</p>;
  }

  return (
    <div className="space-y-4">
      <h3 className="font-semibold">7-Day PnL Summary</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Total PnL</p>
          <p className={`text-lg font-bold ${parseFloat(pnlSummary.total_pnl) >= 0 ? "text-green-600" : "text-red-600"}`}>
            ${parseFloat(pnlSummary.total_pnl).toFixed(2)}
          </p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Win Rate</p>
          <p className="text-lg font-bold">{pnlSummary.win_rate.toFixed(1)}%</p>
          <p className="text-xs text-muted-foreground">{pnlSummary.win_count}W / {pnlSummary.loss_count}L</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Avg Win / Loss</p>
          <p className="text-sm">
            <span className="text-green-600">${parseFloat(pnlSummary.avg_win).toFixed(2)}</span>
            {" / "}
            <span className="text-red-600">${parseFloat(pnlSummary.avg_loss).toFixed(2)}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
