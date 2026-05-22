import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  Radar,
  Sparkles,
  Wallet,
} from "lucide-react";
import { useAppSelector } from "@/store";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const quickActions = [
  {
    title: "Research Pipelines",
    description: "Launch stock or crypto analysis workflows with AI agents.",
    icon: Sparkles,
    to: "/analysis/new",
    action: "Launch",
  },
  {
    title: "Market Scanner",
    description: "Batch-scan markets and drill into signal snapshots.",
    icon: Radar,
    to: "/scanner",
    action: "Scan",
  },
  {
    title: "Portfolio",
    description: "Track balances, positions, and automation rules.",
    icon: Wallet,
    to: "/accounts",
    action: "View",
  },
];

export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);
  const runningCount = entries.filter(([, run]) => run.status === "running").length;

  return (
    <div className="page-shell space-y-8 pb-8 route-stage">
      {/* Hero section */}
      <section className="rounded-[calc(var(--radius)*2)] p-6 sm:p-8 shadow-[var(--shadow-card)]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              Trading Workspace
            </h1>
            <p className="text-sm text-muted-foreground">
              {runningCount > 0
                ? `${runningCount} analysis running`
                : "Ready to launch"}
            </p>
          </div>
          <div className="flex gap-3">
            <Link to="/analysis/new">
              <Button size="lg">
                New Analysis
                <ArrowRight className="ml-2 size-4" />
              </Button>
            </Link>
            <Link to="/scanner">
              <Button variant="outline" size="lg">
                Scanner
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Quick actions grid */}
      <section className="grid gap-5 sm:grid-cols-3">
        {quickActions.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.title} to={card.to} className="block group">
              <Card className="h-full rounded-[calc(var(--radius)*1.4)] transition-all duration-200 group-hover:-translate-y-0.5 group-hover:shadow-[var(--shadow-card-hover)]">
                <CardHeader className="space-y-4 pb-3">
                  <div className="inline-flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.1)] shadow-[var(--shadow-inset)]">
                    <Icon className="size-4.5 text-muted-foreground" />
                  </div>
                  <div className="space-y-1">
                    <CardTitle className="text-base">{card.title}</CardTitle>
                    <CardDescription className="text-sm leading-relaxed">
                      {card.description}
                    </CardDescription>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <span className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                    {card.action}
                    <ArrowRight className="size-3.5" />
                  </span>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </section>

      {/* Active runs or empty state */}
      {entries.length > 0 ? (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Active Runs</h2>
            <Link to="/history">
              <Button variant="ghost" size="sm">
                History
              </Button>
            </Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }} className="block group">
                <Card className="h-full rounded-[calc(var(--radius)*1.4)] transition-all duration-200 group-hover:-translate-y-0.5 group-hover:shadow-[var(--shadow-card-hover)]">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="font-mono text-lg">{run.ticker}</CardTitle>
                      <Badge variant={run.status === "running" ? "default" : "secondary"}>
                        {run.status}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Activity className="size-3.5" />
                      <span className="truncate">
                        {run.currentAgent ? `${run.currentAgent} active` : "Waiting"}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </section>
      ) : (
        <Card className="rounded-[calc(var(--radius)*1.6)]">
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center sm:flex-row sm:text-left sm:p-6">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.3)] bg-primary text-white shadow-[var(--shadow-soft)]">
              <Sparkles className="size-5" />
            </div>
            <div className="flex-1 space-y-1">
              <h2 className="text-lg font-semibold">No active runs</h2>
              <p className="text-sm text-muted-foreground">
                Launch an analysis to start streaming agent reasoning.
              </p>
            </div>
            <div className="flex gap-2">
              <Link to="/analysis/new">
                <Button size="sm">Start analysis</Button>
              </Link>
              <Link to="/scanner">
                <Button variant="outline" size="sm">Scanner</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
