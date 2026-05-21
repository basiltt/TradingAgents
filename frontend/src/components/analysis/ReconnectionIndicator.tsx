import type { ConnectionStatus } from "@/hooks/useAnalysisWebSocket";

interface ReconnectionIndicatorProps {
  status: ConnectionStatus;
  attempt: number;
}

export function ReconnectionIndicator({ status, attempt }: ReconnectionIndicatorProps) {
  return (
    <div role="status">
      {status === "connected" && (
        <span className="inline-flex items-center text-[10px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-500 gap-1.5 shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-sm" />
          Connected
        </span>
      )}
      {status === "connecting" && (
        <span className="inline-flex items-center text-[10px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded-full border border-border bg-muted/40 text-muted-foreground gap-1.5 shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />
          Connecting
        </span>
      )}
      {status === "reconnecting" && (
        <span className="inline-flex items-center text-[10px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-500 gap-1.5 shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
          Reconnecting ({attempt})
        </span>
      )}
      {status === "disconnected" && (
        <span className="inline-flex items-center text-[10px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded-full border border-border bg-muted/20 text-muted-foreground gap-1.5 shadow-sm opacity-60">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50" />
          Offline
        </span>
      )}
    </div>
  );
}
