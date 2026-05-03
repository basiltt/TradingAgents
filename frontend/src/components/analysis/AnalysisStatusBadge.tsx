import { Badge } from "@/components/ui/badge";

const STATUS_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Pending", variant: "outline" },
  running: { label: "Running", variant: "default" },
  completed: { label: "Completed", variant: "secondary" },
  failed: { label: "Failed", variant: "destructive" },
  cancelled: { label: "Cancelled", variant: "outline" },
};

export function AnalysisStatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const config = STATUS_CONFIG[status] ?? { label: status, variant: "outline" as const };
  return (
    <Badge variant={config.variant} className="ml-2 text-xs font-normal">
      {config.label}
    </Badge>
  );
}
