import { Badge } from "@/components/ui/badge";
import type { BacktestStatus } from "./types";

const STATUS_META: Record<
  BacktestStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "Pending", variant: "secondary" },
  running: { label: "Running", variant: "default" },
  completed: { label: "Completed", variant: "default" },
  failed: { label: "Failed", variant: "destructive" },
  cancelled: { label: "Cancelled", variant: "outline" },
};

export function BacktestStatusBadge({ status }: { status: BacktestStatus }) {
  const meta = STATUS_META[status] ?? { label: status, variant: "secondary" as const };
  return (
    <Badge variant={meta.variant} data-testid="status-badge" data-status={status}>
      {meta.label}
    </Badge>
  );
}
