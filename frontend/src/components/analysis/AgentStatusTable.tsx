import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface AgentStatusTableProps {
  agents: Record<string, string>;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  in_progress: "default",
  completed: "secondary",
  failed: "destructive",
};

export function AgentStatusTable({ agents }: AgentStatusTableProps) {
  const entries = Object.entries(agents);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Agents</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No agents active yet</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {entries.map(([name, status]) => (
              <Badge key={name} variant={STATUS_VARIANT[status] ?? "outline"}>
                {name}: {status}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
