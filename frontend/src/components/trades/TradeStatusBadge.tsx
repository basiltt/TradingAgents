const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  open: { label: "Open", className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  pending: { label: "Pending", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  closing: { label: "Closing", className: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  cancelling: { label: "Cancelling", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  closed: { label: "Closed", className: "bg-muted/30 text-muted-foreground border-border/30" },
  cancelled: { label: "Cancelled", className: "bg-muted/30 text-muted-foreground border-border/30" },
  failed: { label: "Failed", className: "bg-red-500/10 text-red-400 border-red-500/20" },
  partially_filled: { label: "Partial", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  partially_closed: { label: "Part. Close", className: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  close_failed: { label: "Failed", className: "bg-red-500/10 text-red-400 border-red-500/20" },
};

const FALLBACK = { label: "Unknown", className: "bg-muted/30 text-muted-foreground border-border/30" };

export function TradeStatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? FALLBACK;
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider border ${config.className}`}>
      {config.label}
    </span>
  );
}
