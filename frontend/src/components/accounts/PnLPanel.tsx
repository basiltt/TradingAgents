import { useState } from "react";
import { accountsApi, type PnlSummary } from "@/api/client";
import { Button } from "@/components/ui/button";

interface PnLPanelProps {
  pnlSummary: PnlSummary | null;
  accountId?: string;
}

export function PnLPanel({ pnlSummary: initialSummary, accountId }: PnLPanelProps) {
  const today = new Date().toISOString().split("T")[0];
  const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString().split("T")[0];

  const [startDate, setStartDate] = useState(sevenDaysAgo);
  const [endDate, setEndDate] = useState(today);
  const [pnlSummary, setPnlSummary] = useState<PnlSummary | null>(initialSummary);
  const [loading, setLoading] = useState(false);

  const fetchRange = async () => {
    if (!accountId) return;
    setLoading(true);
    try {
      const result = await accountsApi.getPnlSummary(accountId, startDate, endDate);
      setPnlSummary(result);
    } catch {
      // keep existing data
    } finally {
      setLoading(false);
    }
  };

  if (!pnlSummary && !accountId) {
    return <p className="text-muted-foreground text-center py-8">No PnL data available</p>;
  }

  return (
    <div className="space-y-4">
      {accountId && (
        <div className="flex items-center gap-2 flex-wrap">
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded px-2 py-1 text-sm" aria-label="Start date" />
          <span className="text-sm">to</span>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="border rounded px-2 py-1 text-sm" aria-label="End date" />
          <Button size="sm" variant="outline" onClick={fetchRange} disabled={loading}>
            {loading ? "Loading..." : "Apply"}
          </Button>
        </div>
      )}
      {!pnlSummary ? (
        <p className="text-muted-foreground text-center py-8">No PnL data available</p>
      ) : (
      <>
      <h3 className="font-semibold">PnL Summary</h3>
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
      </>
      )}
    </div>
  );
}
