import type { DailySnapshot } from "@/api/client";

interface Props {
  snapshots: DailySnapshot[];
}

export function MonthlyPnlGrid({ snapshots }: Props) {
  const monthlyData: Record<string, Record<number, number>> = {};

  for (const s of snapshots) {
    const [yearStr, monthStr] = s.snapshot_date.split("-");
    const year = yearStr;
    const month = parseInt(monthStr) - 1;
    if (!monthlyData[year]) monthlyData[year] = {};
    monthlyData[year][month] = (monthlyData[year][month] || 0) + s.realised_pnl;
  }

  const years = Object.keys(monthlyData).sort();
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  if (years.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border/30">
            <th className="text-left p-2 text-[10px] text-muted-foreground font-extrabold uppercase tracking-wider">Year</th>
            {months.map((m) => (
              <th key={m} className="text-center p-2 text-[10px] text-muted-foreground font-extrabold uppercase tracking-wider">{m}</th>
            ))}
            <th className="text-center p-2 text-[10px] text-muted-foreground font-extrabold uppercase tracking-wider">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            const yearTotal = Object.values(monthlyData[year]).reduce((a, b) => a + b, 0);
            return (
              <tr key={year} className="hover:bg-muted/10 transition-colors duration-150">
                <td className="p-2 font-bold text-foreground/90">{year}</td>
                {months.map((_, idx) => {
                  const val = monthlyData[year][idx];
                  if (val === undefined) {
                    return (
                      <td key={idx} className="p-1 text-center">
                        <div className="py-1.5 px-2 text-muted-foreground/25 font-bold">-</div>
                      </td>
                    );
                  }
                  const color = val >= 0 ? "text-emerald-500 dark:text-emerald-400 bg-emerald-500/10 dark:bg-emerald-500/5 border border-emerald-500/20" : "text-destructive bg-destructive/10 dark:bg-destructive/5 border border-destructive/20";
                  return (
                    <td key={idx} className="p-1 text-center">
                      <div className={`py-1.5 px-2 rounded-lg font-medium tabular-nums ${color}`}>
                        {val >= 0 ? "+$" : "-$"}{Math.abs(val).toFixed(2)}
                      </div>
                    </td>
                  );
                })}
                <td className="p-1 text-center">
                  <div className={`py-1.5 px-2 rounded-lg font-black tabular-nums border ${yearTotal >= 0 ? "text-emerald-500 dark:text-emerald-400 bg-emerald-500/5 border-emerald-500/15" : "text-destructive bg-destructive/5 border-destructive/15"}`}>
                    {yearTotal >= 0 ? "+$" : "-$"}{Math.abs(yearTotal).toFixed(2)}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
