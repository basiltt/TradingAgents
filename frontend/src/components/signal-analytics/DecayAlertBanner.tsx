export interface DecayAlert {
  id: number;
  alert_type: string;
  severity: string;
  message: string;
  created_at: string;
}

interface Props {
  alerts: DecayAlert[];
  onAcknowledge: (id: number) => void;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

function severityClass(severity: string): string {
  switch (severity.toLowerCase()) {
    case "critical":
      return "border-destructive/40 bg-destructive/8 text-destructive";
    case "warning":
      return "border-amber-500/40 bg-amber-500/8 text-amber-700 dark:text-amber-400";
    default:
      return "border-border/60 bg-card/70 text-foreground";
  }
}

export async function acknowledgeAlert(id: number): Promise<void> {
  await fetch(`${BASE_URL}/api/v1/signal-analytics/decay-alerts/${id}/acknowledge`, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
}

export function DecayAlertBanner({ alerts, onAcknowledge }: Props) {
  if (alerts.length === 0) return null;

  return (
    <div className="space-y-2">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className={`flex items-start justify-between gap-3 rounded-[calc(var(--radius)*1.2)] border px-4 py-3 ${severityClass(alert.severity)}`}
        >
          <div className="flex-1 space-y-0.5">
            <p className="text-xs font-bold uppercase tracking-wider opacity-70">
              {alert.alert_type.replace(/_/g, " ")} &mdash; {alert.severity.toUpperCase()}
            </p>
            <p className="text-sm">{alert.message}</p>
            <p className="text-xs opacity-50">
              {new Date(alert.created_at).toLocaleString()}
            </p>
          </div>
          <button
            onClick={() => onAcknowledge(alert.id)}
            className="shrink-0 rounded-[calc(var(--radius)*0.9)] border border-current/20 px-3 py-1.5 text-xs font-semibold opacity-70 hover:opacity-100 transition-opacity"
          >
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
