import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  pending: { label: "Pending", className: "bg-muted/40 text-muted-foreground border-border/40" },
  running: { label: "Running", className: "bg-primary/10 border-primary/25 text-primary animate-pulse-slow font-bold" },
  completed: { label: "Completed", className: "bg-emerald-500/10 border-emerald-500/25 text-emerald-500 font-bold" },
  failed: { label: "Failed", className: "bg-destructive/10 border-destructive/25 text-destructive font-bold" },
  cancelled: { label: "Cancelled", className: "bg-muted/30 border-border/20 text-muted-foreground" },
};

export function AnalysisStatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const config = STATUS_CONFIG[status] ?? { label: status.toUpperCase(), className: "bg-muted/30 border-border/20 text-muted-foreground" };
  return (
    <span className={cn("ml-1 inline-flex items-center text-[10px] uppercase tracking-wider font-extrabold px-2.5 py-0.5 rounded-full border shadow-sm", config.className)}>
      {config.label}
    </span>
  );
}
