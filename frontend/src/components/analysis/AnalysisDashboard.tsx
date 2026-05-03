import { useQuery } from "@tanstack/react-query";
import { apiClient, type AnalysisSnapshot } from "@/api/client";
import { useAnalysisWebSocket, emptyWsState, type WsState } from "@/hooks/useAnalysisWebSocket";
import { AgentStatusTable } from "./AgentStatusTable";
import { MessagesPanel } from "./MessagesPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsBar } from "./StatsBar";
import { ReconnectionIndicator } from "./ReconnectionIndicator";
import { AnalysisStatusBadge } from "./AnalysisStatusBadge";
import { Skeleton } from "@/components/ui/skeleton";

interface AnalysisDashboardProps {
  runId: string;
}

const EMPTY_AGENTS: Record<string, string> = {};
const EMPTY_MESSAGES: Array<{ sender: string; content: string; seq: number }> = [];
const EMPTY_REPORTS: Record<string, string> = {};

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

  // Fetch saved report for completed runs
  const isTerminal = runDetails?.status === "completed" || runDetails?.status === "failed" || runDetails?.status === "cancelled";
  const { data: savedReport } = useQuery({
    queryKey: ["analysis", runId, "report"],
    queryFn: ({ signal }) => apiClient.getReport(runId, signal),
    enabled: isTerminal,
    staleTime: Infinity,
  });

  // Fetch saved snapshot (stats, agents, messages) for completed runs
  const { data: snapshot } = useQuery<AnalysisSnapshot>({
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

  const isLoading =
    status === "connecting" &&
    Object.keys(agents).length === 0 &&
    messages.length === 0 &&
    Object.keys(reports).length === 0 &&
    !runDetails &&
    !snapshot;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            {runDetails?.ticker ? (
              <span>{runDetails.ticker} Analysis</span>
            ) : (
              "Analysis"
            )}
            <AnalysisStatusBadge status={runDetails?.status} />
          </h1>
          <p className="text-sm text-muted-foreground mt-1 font-mono">{runId}</p>
        </div>
        <ReconnectionIndicator status={status} attempt={attempt} />
      </div>

      {/* Running indicator */}
      {!isTerminal && !isLoading && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 flex items-center gap-3">
          <svg className="w-4 h-4 text-primary animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm font-medium text-primary">Analysis in progress...</span>
          <div className="flex-1 h-1.5 rounded-full bg-primary/10 overflow-hidden">
            <div className="h-full w-1/3 rounded-full bg-primary/60 animate-[indeterminate_1.5s_ease-in-out_infinite]" />
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 rounded-xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Skeleton className="h-64 rounded-xl" />
            <Skeleton className="h-64 rounded-xl" />
          </div>
          <Skeleton className="h-48 rounded-xl" />
        </div>
      ) : (
        <>
          <StatsBar stats={stats} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AgentStatusTable agents={agents} />
            <MessagesPanel messages={messages} />
          </div>
          <ReportPanel reports={reports} />
        </>
      )}
    </div>
  );
}
