import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAnalysisWebSocket, emptyWsState, type WsState } from "@/hooks/useAnalysisWebSocket";
import { AgentStatusTable } from "./AgentStatusTable";
import { MessagesPanel } from "./MessagesPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsBar } from "./StatsBar";
import { ReconnectionIndicator } from "./ReconnectionIndicator";

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
    initialData: emptyWsState,
    enabled: false,
    staleTime: Infinity,
  });

  const agents = wsData?.agents ?? EMPTY_AGENTS;
  const messages = wsData?.messages ?? EMPTY_MESSAGES;
  const reports = wsData?.reports ?? EMPTY_REPORTS;
  const stats = wsData?.stats ?? null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Analysis: {runId}</h2>
        <ReconnectionIndicator status={status} attempt={attempt} />
      </div>
      <StatsBar stats={stats} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgentStatusTable agents={agents} />
        <MessagesPanel messages={messages} />
      </div>
      <ReportPanel reports={reports} />
    </div>
  );
}
