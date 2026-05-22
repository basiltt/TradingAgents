import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  ChartColumnBig,
  Radar,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wallet,
  Zap,
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

const capabilityPills = [
  "Light + dark workstation modes",
  "Desktop, tablet, and mobile layouts",
  "Reusable design tokens and shared surfaces",
];

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
        eyebrow="Trading command center"
        title="A premium crypto-native workspace for research, scanning, and portfolio execution."
        description="The workspace now prioritizes clarity under pressure: better hierarchy, more legible surfaces, stronger actions, and adaptive layouts that hold up from phones to ultra-wide dashboards."
        className="aurora-border"
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
          { label: "Readiness", value: readiness, tone: runningCount > 0 ? "warning" : "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          {capabilityPills.map((pill) => (
            <Badge key={pill} variant="outline" className="px-3 py-1 text-[0.65rem] tracking-[0.16em]">
              {pill}
            </Badge>
          ))}
        </div>
      </PageHeader>

      <section className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Card className="page-hero crypto-grid aurora-border rounded-[calc(var(--radius)*1.6)] border-border/60">
          <CardContent className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1.4fr_0.9fr] lg:items-end">
            <div className="space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/8 px-3 py-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.2em] text-foreground/82 backdrop-blur-md">
                <Zap className="size-3.5 text-primary" />
                Refined live workspace
              </div>
              <div className="space-y-3">
                <h2 className="max-w-3xl text-2xl font-semibold tracking-[-0.05em] text-foreground sm:text-3xl lg:text-[2.35rem]">
                  Ship faster decisions with a cleaner, more disciplined operator surface.
                </h2>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground sm:text-[0.95rem]">
                  Research launches, signal monitoring, and account oversight now sit inside a tighter visual system with stronger affordances, clearer empty states, and a more confident market-terminal feel.
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricTile icon={TrendingUp} label="Active pipelines" value={String(runningCount)} sublabel="Current research pressure" />
                <MetricTile icon={ShieldCheck} label="Completed runs" value={String(completedCount)} sublabel="Reusable output history" />
                <MetricTile icon={ChartColumnBig} label="Failed runs" value={String(failedCount)} sublabel="Surface exceptions quickly" />
              </div>
            </div>

            <div className="surface-lift rounded-[calc(var(--radius)*1.5)] p-4 sm:p-5">
              <p className="section-eyebrow">Workspace flow</p>
              <div className="mt-4 space-y-3">
                {[
                  ["01", "Launch", "Set ticker, analyst team, and execution models in one guided builder."],
                  ["02", "Monitor", "Track agent progress, queue health, and signal state without losing context."],
                  ["03", "Act", "Move into portfolio, trades, and strategy pages through the shared shell."],
                ].map(([step, title, desc]) => (
                  <div key={step} className="rounded-[calc(var(--radius)*1.15)] border border-border/60 bg-card/55 p-3.5 shadow-[var(--shadow-soft)]">
                    <div className="flex items-start gap-3">
                      <div className="gradient-primary inline-flex size-10 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.05)] text-primary-foreground shadow-[var(--shadow-accent)]">
                        <span className="text-xs font-bold tracking-[0.14em]">{step}</span>
                      </div>
                      <div className="space-y-1">
                        <p className="text-sm font-semibold tracking-[-0.03em] text-foreground">{title}</p>
                        <p className="text-xs leading-6 text-muted-foreground">{desc}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-1">
          {featureCards.map((card) => {
            const Icon = card.icon;
            return (
              <Link key={card.title} to={card.to} className="block">
                <Card className="h-full rounded-[calc(var(--radius)*1.45)] border-border/60 hover:-translate-y-1 hover:border-primary/30">
                  <CardHeader className="space-y-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="inline-flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.2)] bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
                        <Icon className="size-5" />
                      </div>
                      <Badge
                        variant="outline"
                        className={cn(
                          card.tone === "success" && "text-emerald-400 border-emerald-500/25",
                          card.tone === "warning" && "text-amber-400 border-amber-500/25",
                        )}
                      >
                        {card.tone}
                      </Badge>
                    </div>
                    <div className="space-y-2">
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
        </div>
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
                <Card className="h-full rounded-[calc(var(--radius)*1.45)] border-border/60 hover:-translate-y-1 hover:border-primary/30">
                  <CardHeader className="gap-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="section-eyebrow">Pipeline run</p>
                        <CardTitle className="mt-2 font-mono text-xl tracking-[0.08em]">{run.ticker}</CardTitle>
                      </div>
                      <Badge variant={run.status === "running" ? "default" : "secondary"}>{run.status}</Badge>
                    </div>
                    <div className="flex items-center gap-2 rounded-[calc(var(--radius)*1.05)] border border-border/60 bg-muted/25 px-3 py-2 text-[0.82rem] text-muted-foreground">
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
        <Card className="overflow-hidden rounded-[calc(var(--radius)*1.55)] border-dashed border-border/70">
          <CardContent className="grid gap-4 p-5 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center md:p-6">
            <div className="gradient-primary flex size-14 items-center justify-center rounded-[calc(var(--radius)*1.4)] text-primary-foreground shadow-[var(--shadow-accent)]">
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

function MetricTile({
  icon: Icon,
  label,
  value,
  sublabel,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  sublabel: string;
}) {
  return (
    <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/60 p-3.5 shadow-[var(--shadow-soft)] backdrop-blur-xl">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-4" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">{label}</span>
      </div>
      <p className="mt-3 text-xl font-semibold tracking-[-0.04em] text-foreground">{value}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{sublabel}</p>
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
    <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/65 p-3 shadow-[var(--shadow-soft)]">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-4" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">{label}</span>
      </div>
      <p className="mt-3 text-base font-semibold tracking-[-0.03em] text-foreground">{value}</p>
    </div>
  );
}
