import { useQuery } from "@tanstack/react-query";
import { useState, useEffect, useMemo } from "react";
import { formatDuration } from "@/lib/format";
import { apiClient, type AnalysisSnapshot } from "@/api/client";
import { useAnalysisWebSocket, emptyWsState, type WsState } from "@/hooks/useAnalysisWebSocket";
import { AgentStatusTable } from "./AgentStatusTable";
import { MessagesPanel } from "./MessagesPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsBar } from "./StatsBar";
import { ReconnectionIndicator } from "./ReconnectionIndicator";
import { AnalysisStatusBadge } from "./AnalysisStatusBadge";
import { PageHeader } from "@/components/layout/PageHeader";
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
    <div className="glass-card border border-border/40 rounded-2xl bg-card/40 transition-all duration-300 hover:border-border/60">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-3 w-full text-left px-4 py-3.5 flex-wrap cursor-pointer"
      >
        <div className="w-8 h-8 rounded-lg bg-muted/50 flex items-center justify-center text-muted-foreground shrink-0">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12.75 3.03v.568c0 .334.148.65.405.864l4.038 3.348a.507.507 0 00.325.122h.001c.276 0 .5-.224.5-.5V3.03M21 21v-4.5m0 0l-3-3m3 3l3-3M2.25 12a9.75 9.75 0 1119.5 0M9 9.75h.008v.008H9V9.75zm.563 0h.008v.008H9.563V9.75zm.562 0H11v.008h-.875V9.75zm.563 0h.008v.008H11.25V9.75zm.562 0h.008v.008h-.008V9.75zm.563 0h.008v.008H12.38V9.75zm.562 0h.008v.008h-.008V9.75zm.563 0h.008v.008H13.5V9.75zm.562 0h.008v.008h-.008V9.75z" />
          </svg>
        </div>
        
        <div className="flex items-center gap-2 flex-wrap">
          {provider && (
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground/90 bg-muted/40 px-2 py-0.5 rounded border border-border/20">{provider}</span>
          )}
          {!!config.workflow_mode && (
            <span className={cn(
              "px-2 py-0.5 rounded font-extrabold text-[10px] uppercase tracking-wider border",
              config.workflow_mode === "quick_trade"
                ? "bg-amber-500/10 border-amber-500/25 text-amber-500"
                : "bg-emerald-500/10 border-emerald-500/25 text-emerald-500",
            )}>
              {config.workflow_mode === "quick_trade" ? "Quick Trade" : "Deep Analysis"}
            </span>
          )}
          {deepModel && (
            <span className="inline-flex items-center gap-1.5 text-xs">
              <span className="px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/25 text-purple-500 font-extrabold text-[10px] uppercase tracking-wider">Deep Model</span>
              <span className="font-mono font-bold text-foreground/80">{deepModel}</span>
            </span>
          )}
          {quickModel && (
            <span className="inline-flex items-center gap-1.5 text-xs">
              <span className="px-2 py-0.5 rounded bg-sky-500/10 border border-sky-500/25 text-sky-500 font-extrabold text-[10px] uppercase tracking-wider">Quick Model</span>
              <span className="font-mono font-bold text-foreground/80">{quickModel}</span>
            </span>
          )}
        </div>

        {extras.length > 0 && (
          <svg className={`w-4 h-4 text-muted-foreground/60 ml-auto shrink-0 transition-transform duration-300 ${open ? "rotate-180 text-foreground" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>
      {open && extras.length > 0 && (
        <div className="px-4 pb-4.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs border-t border-border/30 pt-3.5 animate-fade-in">
          {extras.map(([k, v]) => (
            <div key={k} className="flex flex-col gap-1 px-3 py-2 rounded-xl bg-muted/20 border border-border/10">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/75 font-semibold">{k}</span>
              <span className="font-bold text-foreground truncate">{v}</span>
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
  const effectiveRunStatus =
    ["completed", "failed", "cancelled"].includes(wsData?.progress?.phase ?? "")
      ? (wsData?.progress?.phase ?? runDetails?.status ?? "running")
      : (runDetails?.status ?? "running");

  return (
    <div className="page-shell space-y-5 pb-8">
      <PageHeader
        eyebrow="Research pipeline"
        title={runDetails?.ticker ? `Analysis: ${runDetails.ticker} Pipeline` : "Analysis Pipeline Run"}
        description="Monitor live agent output, track reconnect state, and review the final decision package from a single run console."
        stats={[
          {
            label: "Feed",
            value: status === "connected" ? "Live" : status === "connecting" ? "Syncing" : "Replay",
            tone: status === "connected" ? "success" : "warning",
          },
          {
            label: "Agents",
            value: String(Object.keys(agents).length),
            tone: "accent",
          },
          {
            label: "Messages",
            value: String(messages.length),
            tone: "neutral",
          },
          {
            label: "Reports",
            value: String(Object.keys(reports).length),
            tone: isTerminal ? "success" : "neutral",
          },
        ]}
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => window.history.back()}
              className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-border/70 bg-card/72 px-3.5 py-2.5 text-sm font-semibold text-foreground shadow-[var(--shadow-soft)]"
              title="Go back"
            >
              <svg className="mr-2 size-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
              Back
            </button>
            <div className="hidden sm:block">
              <ReconnectionIndicator status={status} attempt={attempt} />
            </div>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <AnalysisStatusBadge status={effectiveRunStatus} />
          <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-[var(--shadow-soft)]">
            <DurationBadge
              startedAt={runDetails?.started_at}
              completedAt={runDetails?.completed_at}
              isTerminal={isTerminal}
            />
          </span>
          <span className="inline-flex min-h-8 items-center rounded-full border border-border/60 bg-card/68 px-3 py-1 font-mono text-xs text-muted-foreground shadow-[var(--shadow-soft)]">
            ID: {runId}
          </span>
          <div className="sm:hidden">
            <ReconnectionIndicator status={status} attempt={attempt} />
          </div>
        </div>
      </PageHeader>

      {/* Config summary */}
      {Object.keys(parsedConfig).length > 0 && (
        <ConfigSummary config={parsedConfig} />
      )}

      {/* Running indicator */}
      {!isTerminal && !isLoading && (
        <div className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3.5 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4 shadow-sm animate-pulse-slow">
          <div className="flex items-center gap-2.5 shrink-0">
            <svg className="w-5 h-5 text-primary animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm font-bold text-primary uppercase tracking-wider">Pipeline Engine active</span>
          </div>
          <div className="h-2 rounded-full bg-primary/10 overflow-hidden sm:flex-1 w-full">
            <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-primary to-purple-500 animate-[indeterminate_1.5s_ease-in-out_infinite]" />
          </div>
        </div>
      )}

      {isLoading || isLoadingTerminalData ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 rounded-2xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Skeleton className="h-[28rem] rounded-2xl" />
            <Skeleton className="h-[28rem] rounded-2xl" />
          </div>
          {/* Report skeleton — taller to represent multiple sections */}
          <div className="space-y-3">
            <Skeleton className="h-12 w-48 rounded-xl" />
            <Skeleton className="h-96 rounded-2xl" />
          </div>
        </div>
      ) : (
        <>
          <StatsBar stats={stats} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 items-stretch">
            <AgentStatusTable agents={agents} isLoading={isLoadingSnapshot} config={parsedConfig} />
            <MessagesPanel messages={messages} isLoading={isLoadingSnapshot} />
          </div>
          <ReportPanel reports={reports} isLoading={isLoadingReport || isLoadingSnapshot} />
        </>
      )}
    </div>
  );
}
