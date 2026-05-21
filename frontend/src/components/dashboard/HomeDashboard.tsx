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
import { PageHeader } from "@/components/layout/PageHeader";

const featureCards = [
  {
    title: "Research Pipelines",
    description:
      "Launch stock or crypto analysis with provider overrides, research depth, and output controls.",
    icon: Sparkles,
    to: "/analysis/new",
    action: "Start an analysis",
  },
  {
    title: "Market Scanner",
    description:
      "Batch scan symbols, attach automation rules, and reuse the same agent presets at scale.",
    icon: Radar,
    to: "/scanner",
    action: "Open scanner",
  },
  {
    title: "Portfolio Oversight",
    description:
      "Track accounts, trades, strategies, and cycles from a single responsive workspace.",
    icon: Wallet,
    to: "/accounts",
    action: "Review accounts",
  },
];

export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);
  const runningCount = entries.filter(([, run]) => run.status === "running").length;
  const completedCount = entries.filter(([, run]) => run.status === "completed").length;
  const failedCount = entries.filter(([, run]) => run.status === "failed").length;

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Trading Workspace"
        title="Autonomous trading research, portfolio oversight, and scanner automation in one adaptive UI."
        description="The redesigned command center is tuned for touch devices, laptop workflows, and ultra-wide monitoring setups. Launch workflows faster, keep status visible, and switch the full palette from a single source."
        actions={
          <>
            <Link
              to="/analysis/new"
              className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-primary/20 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
            >
              Start analysis
            </Link>
            <Link
              to="/scanner"
              className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-border/70 bg-card/75 px-3.5 py-2.5 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)]"
            >
              Open scanner
            </Link>
          </>
        }
        stats={[
          { label: "Running", value: String(runningCount), tone: "accent" },
          { label: "Completed", value: String(completedCount), tone: "success" },
          { label: "Failed", value: String(failedCount), tone: "danger" },
          { label: "Tracked runs", value: String(entries.length), tone: "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Responsive by design</Badge>
          <Badge variant="outline">Light and dark themes</Badge>
          <Badge variant="outline">Shared palette tokens</Badge>
        </div>
      </PageHeader>

      <section className="grid gap-4 xl:grid-cols-3">
        {featureCards.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.title} to={card.to} className="block">
              <Card className="h-full hover:-translate-y-1">
                <CardHeader className="space-y-3">
                  <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
                    <Icon className="size-4.5" />
                  </div>
                  <div className="space-y-2">
                    <CardTitle>{card.title}</CardTitle>
                    <CardDescription>{card.description}</CardDescription>
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
              <h2 className="text-xl font-semibold tracking-tight">Active analysis queue</h2>
            </div>
            <Link to="/history" className="text-sm font-semibold text-primary">
              View full history
            </Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }} className="block">
                <Card className="h-full hover:-translate-y-1">
                  <CardHeader className="gap-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="section-eyebrow">Pipeline run</p>
                        <CardTitle className="mt-2 font-mono text-xl tracking-[0.04em]">
                          {run.ticker}
                        </CardTitle>
                      </div>
                      <Badge variant={run.status === "running" ? "default" : "secondary"}>
                        {run.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2 rounded-[calc(var(--radius)*1.15)] border border-border/60 bg-muted/20 px-2.5 py-1.5 text-[0.82rem] text-muted-foreground">
                      <Activity className="size-4 text-primary" />
                      <span className="truncate">
                        {run.currentAgent ? `${run.currentAgent} is currently active` : "Waiting for orchestration"}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-3 sm:grid-cols-2">
                    <SummaryStat
                      icon={ChartColumnBig}
                      label="Status"
                      value={run.status}
                    />
                    <SummaryStat
                      icon={Radar}
                      label="Agent"
                      value={run.currentAgent ?? "Pending"}
                    />
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </section>
      ) : (
        <Card className="overflow-hidden border-dashed">
          <CardContent className="grid gap-4 p-5 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <Sparkles className="size-5.5" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-tight">No active runs yet</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Launch a new analysis to stream agent reasoning, monitor progress, and capture the final report from the redesigned workspace.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 md:justify-end">
              <Link
                to="/analysis/new"
                className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-primary/20 bg-primary px-3.5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
              >
                Start analysis
              </Link>
              <Link
                to="/scanner"
                className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-border/70 bg-card/75 px-3.5 py-2.5 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)]"
              >
                Explore scanner
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
    <div className="rounded-[calc(var(--radius)*1.25)] border border-border/60 bg-card/65 p-3 shadow-[var(--shadow-soft)]">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-4" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">
          {label}
        </span>
      </div>
      <p className="mt-3 text-base font-semibold tracking-tight text-foreground">{value}</p>
    </div>
  );
}
