import { Link } from "@tanstack/react-router";
import { useAppSelector } from "@/store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";


export function HomeDashboard() {
  const activeRuns = useAppSelector((s) => s.analysis.activeRuns);
  const entries = Object.entries(activeRuns);

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="gradient-hero relative overflow-hidden rounded-2xl p-8 md:p-10 text-white shadow-xl shadow-primary/15">
        <div className="absolute inset-0 opacity-[0.07]" style={{backgroundImage: 'radial-gradient(circle at 20% 50%, white 1px, transparent 1px), radial-gradient(circle at 80% 20%, white 1px, transparent 1px)', backgroundSize: '40px 40px'}} />
        <div className="absolute top-0 right-0 w-72 h-72 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/4 blur-3xl" />
        <div className="relative">
          <h1 className="text-2xl md:text-3xl font-bold mb-3 tracking-tight">
            Welcome to TradingAgents
          </h1>
          <p className="text-white/75 text-base md:text-lg max-w-2xl mb-8 leading-relaxed">
            AI-powered multi-agent trading analysis. Get comprehensive market insights
            from specialized analyst, researcher, and risk management agents.
          </p>
          <Link
            to="/analysis/new"
            className="inline-flex items-center gap-2 h-10 px-5 rounded-lg bg-white/90 dark:bg-white/30 text-primary dark:text-white font-semibold hover:bg-white dark:hover:bg-white/40 shadow-lg shadow-black/10 text-sm transition-colors"
          >
            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Analysis
          </Link>
        </div>
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat
          label="Active Analyses"
          value={entries.filter(([, r]) => r.status === "running").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          }
          color="text-primary"
          bgColor="bg-primary/10"
        />
        <QuickStat
          label="Completed"
          value={entries.filter(([, r]) => r.status === "completed").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="text-emerald-600 dark:text-emerald-400"
          bgColor="bg-emerald-500/10"
        />
        <QuickStat
          label="Failed"
          value={entries.filter(([, r]) => r.status === "failed").length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="text-destructive"
          bgColor="bg-destructive/10"
        />
        <QuickStat
          label="Total"
          value={entries.length}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          }
          color="text-muted-foreground"
          bgColor="bg-muted"
        />
      </div>

      {/* Active analyses */}
      {entries.length > 0 ? (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Active Analyses</h2>
            <Link to="/history" className="text-sm text-primary hover:underline font-medium">
              View all
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map(([runId, run]) => (
              <Link key={runId} to="/analysis/$runId" params={{ runId }}>
                <Card className="group hover:shadow-lg hover:border-primary/50 transition-all duration-200 cursor-pointer">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <span className="font-mono font-bold text-lg">{run.ticker}</span>
                      </span>
                      <Badge
                        variant={run.status === "running" ? "default" : "secondary"}
                        className={run.status === "running" ? "animate-pulse-slow" : ""}
                      >
                        {run.status}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {run.currentAgent ? (
                      <p className="text-sm text-muted-foreground flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                        {run.currentAgent}
                      </p>
                    ) : (
                      <p className="text-sm text-muted-foreground">Waiting...</p>
                    )}
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ) : (
        <Card className="border-dashed border-2 shadow-none">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/5 dark:bg-primary/10 flex items-center justify-center mb-5">
              <svg className="w-8 h-8 text-primary/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <h3 className="font-semibold text-foreground mb-1.5 text-base">No active analyses</h3>
            <p className="text-sm text-muted-foreground mb-6 max-w-xs leading-relaxed">
              Start a new analysis to see real-time progress from AI trading agents.
            </p>
            <Link
              to="/analysis/new"
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:opacity-90 transition-opacity"
            >
              <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Start Analysis
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
  bgColor,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}) {
  return (
    <Card className="shadow-sm hover:shadow-md transition-shadow duration-200">
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center gap-3.5">
          <div className={`w-10 h-10 rounded-xl ${bgColor} flex items-center justify-center ${color}`}>
            {icon}
          </div>
          <div>
            <p className="text-2xl font-bold tracking-tight">{value}</p>
            <p className="text-xs text-muted-foreground font-medium mt-0.5">{label}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
