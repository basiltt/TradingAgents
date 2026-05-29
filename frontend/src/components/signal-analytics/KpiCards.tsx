import { Card, CardContent } from "@/components/ui/card";

interface Summary {
  total_trades: number;
  win_rate: number;
  avg_pnl_pct: number;
  total_pnl: number;
  avg_hold_minutes: number;
  current_streak: number;
  active_alerts: number;
}

interface Props {
  summary: Summary;
}

export function KpiCards({ summary }: Props) {
  const cards = [
    {
      label: "Total Signals",
      value: String(summary.total_trades),
      tone: "neutral",
    },
    {
      label: "Win Rate",
      value: `${summary.win_rate.toFixed(1)}%`,
      tone: summary.win_rate >= 50 ? "success" : "danger",
    },
    {
      label: "Avg PnL %",
      value: `${summary.avg_pnl_pct >= 0 ? "+" : ""}${summary.avg_pnl_pct.toFixed(2)}%`,
      tone: summary.avg_pnl_pct >= 0 ? "success" : "danger",
    },
    {
      label: "Total PnL",
      value: `${summary.total_pnl >= 0 ? "+" : ""}${summary.total_pnl.toFixed(2)}%`,
      tone: summary.total_pnl >= 0 ? "success" : "danger",
    },
    {
      label: "Streak",
      value: `${summary.current_streak >= 0 ? "+" : ""}${summary.current_streak}`,
      tone: summary.current_streak > 0 ? "success" : summary.current_streak < 0 ? "danger" : "neutral",
    },
    {
      label: "Active Alerts",
      value: String(summary.active_alerts),
      tone: summary.active_alerts > 0 ? "warning" : "neutral",
    },
  ] as const;

  const toneClass: Record<string, string> = {
    success: "text-emerald-500",
    danger: "text-destructive",
    warning: "text-amber-500",
    neutral: "text-foreground",
  };

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <p className="section-eyebrow">{card.label}</p>
            <p className={`mt-2 text-2xl font-semibold tracking-[-0.05em] ${toneClass[card.tone]}`}>
              {card.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
