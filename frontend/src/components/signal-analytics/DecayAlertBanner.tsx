import { type DecayAlert, severityClass } from "./decayAlerts";

// AI-CONTEXT: DecayAlert, acknowledgeAlert, and severityClass live in ./decayAlerts
// so this file exports only the component (React Fast Refresh /
// react-refresh/only-export-components). SignalAnalyticsPage imports the type and
// the acknowledge helper from ./decayAlerts directly.

interface Props {
  alerts: DecayAlert[];
  onAcknowledge: (id: number) => void;
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
