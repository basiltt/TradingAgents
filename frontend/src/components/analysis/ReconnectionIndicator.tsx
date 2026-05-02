import type { ConnectionStatus } from "@/hooks/useAnalysisWebSocket";
import { Badge } from "@/components/ui/badge";

interface ReconnectionIndicatorProps {
  status: ConnectionStatus;
  attempt: number;
}

export function ReconnectionIndicator({ status, attempt }: ReconnectionIndicatorProps) {
  return (
    <div role="status">
      {status === "connected" && (
        <Badge variant="outline" className="border-emerald-500/50 text-emerald-600 dark:text-emerald-400 gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Connected
        </Badge>
      )}
      {status === "connecting" && (
        <Badge variant="outline" className="text-muted-foreground gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />
          Connecting...
        </Badge>
      )}
      {status === "reconnecting" && (
        <Badge variant="outline" className="border-amber-500/50 text-amber-600 dark:text-amber-400 gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          Reconnecting ({attempt})
        </Badge>
      )}
      {status === "disconnected" && (
        <Badge variant="outline" className="text-muted-foreground gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50" />
          Disconnected
        </Badge>
      )}
    </div>
  );
}
