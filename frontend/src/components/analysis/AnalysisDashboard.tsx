import { useQuery } from "@tanstack/react-query";
import { useState, useEffect, useMemo } from "react";
import { apiClient, type AnalysisSnapshot } from "@/api/client";
import { useAnalysisWebSocket, emptyWsState, type WsState } from "@/hooks/useAnalysisWebSocket";
import { AgentStatusTable } from "./AgentStatusTable";
import { MessagesPanel } from "./MessagesPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsBar } from "./StatsBar";
import { ReconnectionIndicator } from "./ReconnectionIndicator";
import { AnalysisStatusBadge } from "./AnalysisStatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";


function ConfigSummary({ config }: { config: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const deepModel = String(config.deep_think_llm ?? "");
  const quickModel = String(config.quick_think_llm ?? "");
  const provider = String(config.llm_provider ?? "");

  const extras = useMemo(() => {
    const c = config;
    const pairs: [string, string][] = [];
    if (c.backend_url) pairs.push(["Backend URL", String(c.backend_url)]);
    if (c.workflow_mode) pairs.push(["Mode", c.workflow_mode === "quick_trade" ? "Quick Trade" : "Deep Analysis"]);
    if (c.asset_type) pairs.push(["Asset Type", String(c.asset_type)]);
    if (c.output_language && c.output_language !== "English") pairs.push(["Language", String(c.output_language)]);
    if (c.max_debate_rounds) pairs.push(["Debate Rounds", String(c.max_debate_rounds)]);
    if (c.max_risk_discuss_rounds) pairs.push(["Risk Rounds", String(c.max_risk_discuss_rounds)]);
    if (c.crypto_interval) pairs.push(["Interval", String(c.crypto_interval)]);
    if (c.checkpoint_enabled) pairs.push(["Checkpoints", "Enabled"]);
    return pairs;
  }, [config]);

  if (!deepModel && !quickModel && !provider) return null;

  return (
    <div className="rounded-xl border border-border/50 bg-card/50 px-4 py-2.5">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-3 w-full text-left flex-wrap"
      >
        <svg className="w-4 h-4 text-muted-foreground shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        {provider && (
          <span className="text-xs font-medium text-muted-foreground capitalize">{provider}</span>
        )}
        {!!config.workflow_mode && (
          <span className={cn(
            "px-1.5 py-0.5 rounded font-semibold text-[10px] uppercase tracking-wide",
            config.workflow_mode === "quick_trade"
              ? "bg-amber-500/15 text-amber-400"
              : "bg-emerald-500/15 text-emerald-400",
          )}>
            {config.workflow_mode === "quick_trade" ? "Quick Trade" : "Deep Analysis"}
          </span>
        )}
        {deepModel && (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-400 font-semibold text-[10px] uppercase tracking-wide">Deep</span>
            <span className="font-mono font-medium">{deepModel}</span>
          </span>
        )}
        {quickModel && (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className="px-1.5 py-0.5 rounded bg-sky-500/15 text-sky-400 font-semibold text-[10px] uppercase tracking-wide">Quick</span>
            <span className="font-mono font-medium">{quickModel}</span>
          </span>
        )}
        {extras.length > 0 && (
          <svg className={`w-3.5 h-3.5 text-muted-foreground ml-auto shrink-0 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>
      {open && extras.length > 0 && (
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-1.5 text-xs border-t border-border/50 pt-2">
          {extras.map(([k, v]) => (
            <div key={k} className="flex gap-1.5 min-w-0">
              <span className="text-muted-foreground shrink-0">{k}:</span>
              <span className="font-medium truncate">{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface AnalysisDashboardProps {
  runId: string;
}

const EMPTY_AGENTS: Record<string, string> = {};
const EMPTY_MESSAGES: Array<{ sender: string; content: string; seq: number }> = [];
const EMPTY_REPORTS: Record<string, string> = {};

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function DurationBadge({ startedAt, completedAt, isTerminal }: { startedAt?: string; completedAt?: string; isTerminal: boolean }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (isTerminal || !startedAt) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initializing timer value at effect start
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isTerminal, startedAt]);

  if (!startedAt) return null;

  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : now;
  const elapsed = Math.max(0, end - start);

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground font-mono tabular-nums">
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      {formatDuration(elapsed)}
    </span>
  );
}

export function AnalysisDashboard({ runId }: AnalysisDashboardProps) {
  const { status, attempt } = useAnalysisWebSocket(runId);
  const { data: wsData } = useQuery<WsState>({
    queryKey: ["analysis", runId, "ws-state"],
    queryFn: () => emptyWsState(),
    initialData: emptyWsState,
    enabled: false,
    staleTime: Infinity,
  });

  // Fetch run details to know if it's completed/failed
  const { data: runDetails } = useQuery({
    queryKey: ["analysis", runId, "details"],
    queryFn: ({ signal }) => apiClient.getAnalysis(runId, signal),
    staleTime: 10_000,
    refetchInterval: status === "connected" ? 15_000 : false,
  });

  const parsedConfig = useMemo<Record<string, unknown>>(() => {
    const raw = runDetails?.config;
    if (!raw) return {};
    if (typeof raw === "string") {
      try { return JSON.parse(raw); } catch { return {}; }
    }
    return raw as Record<string, unknown>;
  }, [runDetails?.config]);

  // Fetch saved report for completed runs
  const isTerminal = runDetails?.status === "completed" || runDetails?.status === "failed" || runDetails?.status === "cancelled"
    || ["completed", "failed", "cancelled"].includes(wsData?.progress?.phase ?? "");
  const { data: savedReport, isLoading: isLoadingReport } = useQuery({
    queryKey: ["analysis", runId, "report"],
    queryFn: ({ signal }) => apiClient.getReport(runId, signal),
    enabled: isTerminal,
    staleTime: Infinity,
  });

  // Fetch saved snapshot (stats, agents, messages) for completed runs
  const { data: snapshot, isLoading: isLoadingSnapshot } = useQuery<AnalysisSnapshot>({
    queryKey: ["analysis", runId, "snapshot"],
    queryFn: ({ signal }) => apiClient.getSnapshot(runId, signal),
    enabled: isTerminal,
    staleTime: Infinity,
  });

  const hasLiveData = Object.keys(wsData?.agents ?? {}).length > 0 || (wsData?.messages ?? []).length > 0;

  const agents = hasLiveData ? (wsData?.agents ?? EMPTY_AGENTS) : (snapshot?.agents ?? EMPTY_AGENTS);
  const messages = hasLiveData ? (wsData?.messages ?? EMPTY_MESSAGES) : (snapshot?.messages ?? EMPTY_MESSAGES);
  const wsReports = wsData?.reports ?? EMPTY_REPORTS;
  const stats = (wsData?.stats ?? null) || (snapshot?.stats ?? null);

  // Merge WS reports with saved report/snapshot for completed runs
  const reports = Object.keys(wsReports).length > 0
    ? wsReports
    : Object.keys(snapshot?.reports ?? {}).length > 0
      ? snapshot!.reports
      : savedReport
        ? { final_trade_decision: savedReport }
        : EMPTY_REPORTS;

  // True initial load — nothing at all yet
  const isLoading =
    status === "connecting" &&
    Object.keys(agents).length === 0 &&
    messages.length === 0 &&
    Object.keys(reports).length === 0 &&
    !runDetails &&
    !snapshot;

  // Terminal run whose snapshot/report is still being fetched from the backend
  const isLoadingTerminalData = isTerminal && !hasLiveData && (isLoadingSnapshot || isLoadingReport);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <button
              type="button"
              onClick={() => window.history.back()}
              className="w-8 h-8 rounded-xl bg-muted/60 hover:bg-muted flex items-center justify-center shrink-0 transition-colors"
              title="Go back"
            >
              <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
              <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">
              {runDetails?.ticker ? `${runDetails.ticker} Analysis` : "Analysis"}
            </h1>
            <AnalysisStatusBadge status={
              ["completed", "failed", "cancelled"].includes(wsData?.progress?.phase ?? "")
                ? wsData!.progress!.phase
                : runDetails?.status
            } />
            <DurationBadge
              startedAt={runDetails?.started_at}
              completedAt={runDetails?.completed_at}
              isTerminal={isTerminal}
            />
            {/* Reconnection indicator inline on mobile, pushed right on sm+ */}
            <div className="sm:hidden">
              <ReconnectionIndicator status={status} attempt={attempt} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-1 font-mono truncate">{runId}</p>
        </div>
        <div className="hidden sm:block shrink-0">
          <ReconnectionIndicator status={status} attempt={attempt} />
        </div>
      </div>

      {/* Config summary */}
      {Object.keys(parsedConfig).length > 0 && (
        <ConfigSummary config={parsedConfig} />
      )}

      {/* Running indicator */}
      {!isTerminal && !isLoading && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-primary animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm font-medium text-primary">Analysis in progress...</span>
          </div>
          <div className="h-1.5 rounded-full bg-primary/10 overflow-hidden sm:flex-1">
            <div className="h-full w-1/3 rounded-full bg-primary/60 animate-[indeterminate_1.5s_ease-in-out_infinite]" />
          </div>
        </div>
      )}

      {isLoading || isLoadingTerminalData ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-[72px] rounded-xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Skeleton className="h-56 rounded-xl" />
            <Skeleton className="h-56 rounded-xl" />
          </div>
          {/* Report skeleton — taller to represent multiple sections */}
          <div className="space-y-2">
            <Skeleton className="h-10 w-48 rounded-xl" />
            <Skeleton className="h-64 rounded-xl" />
          </div>
        </div>
      ) : (
        <>
          <StatsBar stats={stats} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 md:gap-4 items-stretch">
            <AgentStatusTable agents={agents} isLoading={isLoadingSnapshot} config={parsedConfig} />
            <MessagesPanel messages={messages} isLoading={isLoadingSnapshot} />
          </div>
          <ReportPanel reports={reports} isLoading={isLoadingReport || isLoadingSnapshot} />
        </>
      )}
    </div>
  );
}
