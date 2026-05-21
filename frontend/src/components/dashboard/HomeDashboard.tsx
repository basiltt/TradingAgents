import { Link } from "@tanstack/react-router";
import { useAppSelector } from "@/store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";


export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);

  return (
    <div className="space-y-8 animate-fade-in-up">
      {/* Hero Banner */}
      <div className="gradient-hero relative overflow-hidden rounded-2xl p-8 md:p-12 text-white shadow-xl shadow-primary/10 glow-primary border border-white/10 animate-gradient-shift">
        <div className="absolute inset-0 opacity-[0.08]" style={{backgroundImage: 'radial-gradient(circle at 20% 50%, white 1.5px, transparent 1.5px), radial-gradient(circle at 80% 20%, white 1.5px, transparent 1.5px)', backgroundSize: '36px 36px'}} />
        <div className="absolute top-0 right-0 w-80 h-80 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/4 blur-3xl animate-pulse-slow" />
        <div className="relative z-10 max-w-3xl">
          <h1 className="text-3xl md:text-4xl font-extrabold mb-4 tracking-tight leading-tight">
            Welcome to TradingAgents Command Center
          </h1>
          <p className="text-white/80 text-base md:text-lg max-w-2xl mb-8 leading-relaxed font-medium">
            Deploy coordinated-agent workflows. Execute parallel technical, fundamental, 
            and sentiment analysis across Stock and Crypto markets with autonomous AI agents.
          </p>
          <Link
            to="/analysis/new"
            className="inline-flex items-center gap-2.5 h-11 px-6 rounded-xl bg-white text-black font-bold hover:bg-white/90 shadow-lg shadow-black/15 text-sm transition-all duration-300 hover:scale-105 active:scale-95 touch-target cursor-pointer"
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Analysis
          </Link>
        </div>
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <QuickStat
          label="Active Runs"
          value={entries.filter(([, r]) => r.status === "running").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          }
          color="text-primary"
          glowColor="border-primary/20 hover:border-primary/60 hover:shadow-primary/5"
          bgColor="bg-primary/10"
        />
        <QuickStat
          label="Completed Runs"
          value={entries.filter(([, r]) => r.status === "completed").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="text-emerald-500"
          glowColor="border-emerald-500/20 hover:border-emerald-500/60 hover:shadow-emerald-500/5"
          bgColor="bg-emerald-500/10"
        />
        <QuickStat
          label="Failed Runs"
          value={entries.filter(([, r]) => r.status === "failed").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="text-destructive"
          glowColor="border-destructive/20 hover:border-destructive/60 hover:shadow-destructive/5"
          bgColor="bg-destructive/10"
        />
        <QuickStat
          label="Total History"
          value={entries.length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          }
          color="text-muted-foreground"
          glowColor="border-border hover:border-foreground/20"
          bgColor="bg-muted"
        />
      </div>

      {/* Active analyses */}
      {entries.length > 0 ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold tracking-tight">Active Agent Runs</h2>
            <Link to="/history" className="text-sm text-primary hover:underline font-semibold transition-all">
              View all history &rarr;
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }}>
                <Card className={`group glass-card hover:-translate-y-1 transition-all duration-300 cursor-pointer overflow-hidden border border-border/50
                  ${run.status === "running" ? "border-primary/30 glow-primary relative" : ""}`}>
                  {run.status === "running" && (
                    <div className="absolute top-0 left-0 w-full h-[2px] bg-primary animate-pulse" />
                  )}
                  <CardHeader className="pb-3 pt-5">
                    <CardTitle className="text-base flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <span className="font-mono font-extrabold text-xl tracking-wider text-foreground">{run.ticker}</span>
                      </span>
                      <Badge
                        variant={run.status === "running" ? "default" : "secondary"}
                        className={`rounded-md uppercase tracking-wider text-[10px] px-2 py-0.5 font-extrabold ${run.status === "running" ? "animate-pulse-slow shadow shadow-primary/20" : ""}`}
                      >
                        {run.status}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pb-5">
                    {run.currentAgent ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <span className="relative flex h-2 w-2 shrink-0">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                        </span>
                        <span className="font-semibold text-foreground">{run.currentAgent}</span>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground" />
                        Waiting for orchestration...
                      </p>
                    )}
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ) : (
        <Card className="border-dashed border-2 bg-card/30 border-border/80 shadow-none rounded-2xl">
          <CardContent className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/5 flex items-center justify-center mb-6 shadow-inner">
              <svg className="w-8 h-8 text-primary/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <h3 className="font-bold text-foreground mb-2 text-lg tracking-tight">No active agent runs</h3>
            <p className="text-sm text-muted-foreground mb-8 max-w-sm leading-relaxed">
              Initiate a stock or cryptocurrency analysis to monitor live agent reasoning, debates, and trade compliance steps.
            </p>
            <Link
              to="/analysis/new"
              className="inline-flex items-center gap-2 h-11 px-5 rounded-xl bg-primary text-primary-foreground font-bold text-sm hover:opacity-95 shadow-lg shadow-primary/15 transition-all duration-300 hover:scale-105 active:scale-95 cursor-pointer touch-target"
            >
              <svg className="w-4.5 h-4.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Start Analysis Engine
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function QuickStat({
  label,
  value,
  icon,
  color,
  glowColor,
  bgColor,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  glowColor: string;
  bgColor: string;
}) {
  return (
    <Card className={`glass-card border bg-card/60 transition-all duration-300 select-none ${glowColor}`}>
      <CardContent className="pt-6 pb-5 px-5">
        <div className="flex items-center gap-4">
          <div className={`w-11 h-11 rounded-xl ${bgColor} flex items-center justify-center ${color} shadow-sm shrink-0`}>
            {icon}
          </div>
          <div>
            <p className="text-2xl font-extrabold tracking-tight text-foreground leading-none">{value}</p>
            <p className="text-xs text-muted-foreground font-bold uppercase tracking-wider mt-1">{label}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
