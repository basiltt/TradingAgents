import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  ChartColumnBig,
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
import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/utils";

const featureCards = [
  {
    title: "Research Pipelines",
    description:
      "Spin up stock or crypto workflows with faster setup, cleaner defaults, and better model control.",
    icon: Sparkles,
    to: "/analysis/new",
    action: "Launch research",
    tone: "accent",
  },
  {
    title: "Market Scanner",
    description:
      "Batch-scan crypto markets, monitor live sweeps, and drill into signal snapshots without context switching.",
    icon: Radar,
    to: "/scanner",
    action: "Open scanner",
    tone: "success",
  },
  {
    title: "Portfolio Control",
    description:
      "Track balances, positions, trades, and automation from one high-density responsive control surface.",
    icon: Wallet,
    to: "/accounts",
    action: "Review accounts",
    tone: "warning",
  },
];

const capabilityPills: string[] = [];

export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);
  const runningCount = entries.filter(([, run]) => run.status === "running").length;
  const completedCount = entries.filter(([, run]) => run.status === "completed").length;
  const failedCount = entries.filter(([, run]) => run.status === "failed").length;

  const readiness = runningCount > 0 ? "Engaged" : "Ready";

  return (
    <div className="page-shell space-y-6 pb-8 route-stage">
      <PageHeader
        eyebrow="Dashboard"
        title="Trading workspace"
        description=""
        className=""
        actions={
          <div className="flex flex-col gap-2 sm:flex-row">
            <Link to="/analysis/new" className="min-w-[11rem]">
              <Button size="lg" className="min-w-[11rem] w-full">
                Launch analysis
                <ArrowRight className="size-4" />
              </Button>
            </Link>
            <Link to="/scanner" className="min-w-[11rem]">
              <Button variant="outline" size="lg" className="min-w-[11rem] w-full">
                Open scanner
              </Button>
            </Link>
          </div>
        }
        stats={[
          { label: "Running", value: String(runningCount), tone: "accent" },
          { label: "Completed", value: String(completedCount), tone: "success" },
          { label: "Failed", value: String(failedCount), tone: "danger" },
          { label: "Status", value: readiness, tone: runningCount > 0 ? "warning" : "neutral" },
        ]}
      />

      <section className="grid gap-4 sm:grid-cols-3">
        {featureCards.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.title} to={card.to} className="block">
              <Card className="h-full rounded-[calc(var(--radius)*1.45)] transition hover:-translate-y-1 hover:shadow-[var(--shadow-card-hover)]">
                <CardHeader className="space-y-3">
                  <div className="inline-flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.2)] bg-primary/10 text-primary shadow-[var(--shadow-inset)]">
                    <Icon className="size-5" />
                  </div>
                  <div className="space-y-1.5">
                    <CardTitle className="text-[1.05rem]">{card.title}</CardTitle>
                    <CardDescription className="text-sm leading-6">{card.description}</CardDescription>
                  </div>
                </CardHeader>
                <CardContent>
                  <span className="inline-flex items-center gap-2 text-sm font-semibold text-primary">
                    {card.action}
                    <ArrowRight className="size-4" />
                  </span>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </section>

      {entries.length > 0 ? (
        <section className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="section-eyebrow">Live activity</p>
              <h2 className="text-xl font-semibold tracking-[-0.04em]">Active analysis queue</h2>
            </div>
            <Link to="/history">
              <Button variant="ghost" size="sm">
                View full history
              </Button>
            </Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }} className="block">
                <Card className="h-full rounded-[calc(var(--radius)*1.45)] transition hover:-translate-y-1">
                  <CardHeader className="gap-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="section-eyebrow">Pipeline run</p>
                        <CardTitle className="mt-2 font-mono text-xl tracking-[0.08em]">{run.ticker}</CardTitle>
                      </div>
                      <Badge variant={run.status === "running" ? "default" : "secondary"}>{run.status}</Badge>
                    </div>
                    <div className="flex items-center gap-2 rounded-[calc(var(--radius)*1.05)] p-2.5 text-[0.82rem] text-muted-foreground shadow-[var(--shadow-inset)]">
                      <Activity className="size-4 text-primary" />
                      <span className="truncate">
                        {run.currentAgent ? `${run.currentAgent} is currently active` : "Waiting for orchestration"}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-3 sm:grid-cols-2">
                    <SummaryStat icon={ChartColumnBig} label="Status" value={run.status} />
                    <SummaryStat icon={Radar} label="Agent" value={run.currentAgent ?? "Pending"} />
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </section>
      ) : (
        <Card className="overflow-hidden rounded-[calc(var(--radius)*1.55)]">
          <CardContent className="grid gap-4 p-5 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center md:p-6">
            <div className="flex size-14 items-center justify-center rounded-[calc(var(--radius)*1.4)] bg-primary text-white shadow-[var(--shadow-soft)]">
              <Sparkles className="size-6" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-[-0.04em]">No active runs yet</h2>
              <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
                Launch a new analysis to stream agent reasoning, monitor execution, and land inside a calmer high-signal workspace.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 md:justify-end">
              <Link to="/analysis/new">
                <Button>Start analysis</Button>
              </Link>
              <Link to="/scanner">
                <Button variant="outline">Explore scanner</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SummaryStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[calc(var(--radius)*1.2)] p-3 shadow-[var(--shadow-inset)]">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-4" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">{label}</span>
      </div>
      <p className="mt-3 text-base font-semibold tracking-[-0.03em] text-foreground">{value}</p>
    </div>
  );
}
