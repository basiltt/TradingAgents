import type { ConnectionStatus } from "@/hooks/useAnalysisWebSocket";

interface ReconnectionIndicatorProps {
  status: ConnectionStatus;
  attempt: number;
}

export function ReconnectionIndicator({ status, attempt }: ReconnectionIndicatorProps) {
  return (
    <div role="status" className="text-sm">
      {status === "connected" && (
        <span className="text-green-600">Connected</span>
      )}
      {status === "connecting" && (
        <span className="text-muted-foreground">Connecting…</span>
      )}
      {status === "reconnecting" && (
        <span className="text-yellow-600">Reconnecting (attempt {attempt})…</span>
      )}
      {status === "disconnected" && (
        <span className="text-muted-foreground">Disconnected</span>
      )}
    </div>
  );
}
