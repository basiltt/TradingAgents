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
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="text-left py-2 px-2 text-muted-foreground font-medium">Year</th>
            {months.map((m) => (
              <th key={m} className="text-center py-2 px-2 text-muted-foreground font-medium">{m}</th>
            ))}
            <th className="text-center py-2 px-2 text-muted-foreground font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            const yearTotal = Object.values(monthlyData[year]).reduce((a, b) => a + b, 0);
            return (
              <tr key={year}>
                <td className="py-1.5 px-2 font-medium">{year}</td>
                {months.map((_, idx) => {
                  const val = monthlyData[year][idx];
                  if (val === undefined) {
                    return <td key={idx} className="text-center py-1.5 px-2 text-muted-foreground/30">-</td>;
                  }
                  const color = val >= 0 ? "text-emerald-500 bg-emerald-500/10" : "text-red-500 bg-red-500/10";
                  return (
                    <td key={idx} className={`text-center py-1.5 px-2 rounded font-medium tabular-nums ${color}`}>
                      {val >= 0 ? "+$" : "-$"}{Math.abs(val).toFixed(2)}
                    </td>
                  );
                })}
                <td className={`text-center py-1.5 px-2 rounded font-bold tabular-nums ${yearTotal >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                  {yearTotal >= 0 ? "+$" : "-$"}{Math.abs(yearTotal).toFixed(2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
