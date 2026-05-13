import type { ConnStatus } from "@/hooks/useConnectivityCheck";

export function ConnBadge({ status, latency, error, label = "Connected" }: { status: ConnStatus; latency: number | null; error: string | null; label?: string }) {
  if (status === "idle") return null;
  if (status === "checking") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground ml-auto">
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Checking...
      </span>
    );
  }
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 font-medium ml-auto">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        {label}{latency != null && ` (${latency}ms)`}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-destructive font-medium ml-auto">
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      {error || "Unreachable"}
    </span>
  );
}
