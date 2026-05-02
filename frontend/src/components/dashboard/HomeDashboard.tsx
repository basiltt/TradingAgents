import { Link } from "@tanstack/react-router";
import { useAppSelector } from "@/store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold">TradingAgents Dashboard</h2>
        <p className="text-muted-foreground mt-1">Welcome to TradingAgents.</p>
      </div>

      {entries.length > 0 ? (
        <div>
          <h3 className="text-lg font-semibold mb-3">Active Analyses</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }}>
                <Card className="hover:border-primary transition-colors cursor-pointer">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center justify-between">
                      {run.ticker}
                      <Badge variant={run.status === "running" ? "default" : "secondary"}>
                        {run.status}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {run.currentAgent && (
                      <p className="text-sm text-muted-foreground">
                        Current: {run.currentAgent}
                      </p>
                    )}
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      <div>
        <Button asChild>
          <Link to="/analysis/new">New Analysis</Link>
        </Button>
      </div>
    </div>
  );
}
