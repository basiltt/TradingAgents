import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  Radar,
  Sparkles,
  Wallet,
  Zap,
} from "lucide-react";
import { useAppSelector } from "@/store";
import {
  Card,
  CardContent,
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
    gradient: "from-amber-500/10 to-orange-500/5",
  },
  {
    title: "Market Scanner",
    description: "Batch-scan markets and drill into signal snapshots.",
    icon: Radar,
    to: "/scanner",
    action: "Scan",
    gradient: "from-blue-500/10 to-cyan-500/5",
  },
  {
    title: "Portfolio",
    description: "Track balances, positions, and automation rules.",
    icon: Wallet,
    to: "/accounts",
    action: "View",
    gradient: "from-emerald-500/10 to-teal-500/5",
  },
];

export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);
  const runningCount = entries.filter(([, run]) => run.status === "running").length;

  return (
    <div className="page-shell space-y-3 sm:space-y-6 lg:space-y-8 pb-8 route-stage">
      {/* Hero section */}
      <section className="rounded-[calc(var(--radius)*1.4)] sm:rounded-[calc(var(--radius)*2)] p-3.5 sm:p-6 lg:p-8 shadow-[var(--shadow-card)] relative overflow-hidden aurora-border">
        <div className="flex flex-col gap-3 sm:gap-6 lg:flex-row lg:items-center lg:justify-between relative z-10">
          <div className="space-y-1.5 sm:space-y-3">
            <div className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 shadow-[var(--shadow-inset)] text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <Zap className="size-3 text-primary" />
              Workspace
            </div>
            <h1 className="text-lg sm:text-2xl lg:text-3xl font-bold tracking-tight">
              Trading Workspace
            </h1>
            <p className="text-[11px] sm:text-sm text-muted-foreground max-w-md leading-relaxed">
              {runningCount > 0
                ? `${runningCount} pipeline${runningCount > 1 ? "s" : ""} running`
                : "AI-powered market research and automated trading. Ready to launch."}
            </p>
          </div>
          <div className="flex gap-2 sm:gap-3">
            <Link to="/analysis/new" className="flex-1 sm:flex-none">
              <Button size="sm" className="w-full sm:w-auto sm:size-default rounded-[calc(var(--radius)*1.2)] shadow-[var(--shadow-soft)] font-semibold text-xs sm:text-sm">
                New Analysis
                <ArrowRight className="ml-1.5 size-3" />
              </Button>
            </Link>
            <Link to="/scanner" className="flex-1 sm:flex-none">
              <Button variant="outline" size="sm" className="w-full sm:w-auto sm:size-default rounded-[calc(var(--radius)*1.2)] shadow-[var(--shadow-soft)] font-semibold text-xs sm:text-sm">
                Scanner
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Quick actions grid */}
      <section className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3 neu-stagger">
        {quickActions.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.title} to={card.to} className="block group active:scale-[0.985] transition-transform duration-200">
              <Card className={cn(
                "h-full rounded-[calc(var(--radius)*1.2)] sm:rounded-[calc(var(--radius)*1.5)]",
                "neu-card-hover neu-hover-shine relative overflow-hidden"
              )}>
                <div className={cn("absolute inset-0 bg-gradient-to-br opacity-0 group-hover:opacity-100 transition-opacity duration-300", card.gradient)} />
                <div className="flex items-center gap-2.5 sm:gap-3 p-3 sm:p-5 relative">
                  <div className="inline-flex size-8 sm:size-11 shrink-0 items-center justify-center rounded-[calc(var(--radius)*0.9)] shadow-[var(--shadow-inset)] transition-all duration-300 group-hover:scale-105">
                    <Icon className="size-3.5 sm:size-5 text-primary transition-transform duration-300 group-hover:scale-110 group-hover:rotate-6" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] sm:text-sm font-bold">{card.title}</p>
                    <p className="text-[10px] sm:text-xs text-muted-foreground line-clamp-1 mt-0.5">
                      {card.description}
                    </p>
                  </div>
                  <span className="shrink-0 inline-flex items-center text-xs font-semibold text-primary transition-transform duration-300 group-hover:translate-x-1">
                    <ArrowRight className="size-3.5" />
                  </span>
                </div>
              </Card>
            </Link>
          );
        })}
      </section>

      {/* Active runs or empty state */}
      {entries.length > 0 ? (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold tracking-tight">Active Runs</h2>
            <Link to="/history">
              <Button variant="ghost" size="sm" className="rounded-[calc(var(--radius)*1.1)]">
                History
              </Button>
            </Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }} className="block group active:scale-[0.985] transition-transform duration-200">
                <Card className="h-full rounded-[calc(var(--radius)*1.4)] neu-card-hover neu-hover-shine">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="font-mono text-lg font-bold">{run.ticker}</CardTitle>
                      <Badge variant={run.status === "running" ? "default" : "secondary"} className="rounded-full">
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
        <Card className="rounded-[calc(var(--radius)*1.3)] sm:rounded-[calc(var(--radius)*1.8)]">
          <CardContent className="flex flex-col items-center gap-3 sm:gap-4 p-4 sm:p-8 lg:p-10 text-center sm:flex-row sm:text-left">
            <div className="flex size-10 sm:size-14 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.1)] sm:rounded-[calc(var(--radius)*1.4)] bg-primary text-white shadow-[var(--shadow-soft)]">
              <Sparkles className="size-4 sm:size-6" />
            </div>
            <div className="flex-1 space-y-0.5 sm:space-y-1">
              <h2 className="text-sm sm:text-lg font-bold">No active runs</h2>
              <p className="text-[11px] sm:text-sm text-muted-foreground leading-relaxed">
                Launch an analysis to start streaming agent reasoning in real-time.
              </p>
            </div>
            <div className="flex gap-2 sm:gap-3 w-full sm:w-auto">
              <Link to="/analysis/new" className="flex-1 sm:flex-none">
                <Button size="sm" className="w-full sm:w-auto rounded-[calc(var(--radius)*1.1)] shadow-[var(--shadow-soft)] text-xs">Start analysis</Button>
              </Link>
              <Link to="/scanner" className="flex-1 sm:flex-none">
                <Button variant="outline" size="sm" className="w-full sm:w-auto rounded-[calc(var(--radius)*1.1)] shadow-[var(--shadow-soft)] text-xs">Scanner</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
