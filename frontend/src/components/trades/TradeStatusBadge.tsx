import { Badge } from "@/components/ui/badge";

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  open: { label: "Open", className: "bg-green-500/20 text-green-400 border-green-500/30" },
  pending: { label: "Pending", className: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
  closing: { label: "Closing", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  cancelling: { label: "Cancelling", className: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
  closed: { label: "Closed", className: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
  cancelled: { label: "Cancelled", className: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
  failed: { label: "Failed", className: "bg-red-500/20 text-red-400 border-red-500/30" },
  partially_filled: { label: "Partial Fill", className: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
  close_failed: { label: "Close Failed", className: "bg-red-500/20 text-red-400 border-red-500/30" },
};

const FALLBACK = { label: "Unknown", className: "bg-gray-500/20 text-gray-400 border-gray-500/30" };

export function TradeStatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? FALLBACK;
  return <Badge className={config.className}>{config.label}</Badge>;
}
