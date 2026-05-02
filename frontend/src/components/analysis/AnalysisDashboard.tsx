import { useQueryClient } from "@tanstack/react-query";
import { useAnalysisWebSocket } from "@/hooks/useAnalysisWebSocket";
import { AgentStatusTable } from "./AgentStatusTable";
import { MessagesPanel } from "./MessagesPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsBar } from "./StatsBar";
import { ReconnectionIndicator } from "./ReconnectionIndicator";

interface WsState {
  agents: Record<string, string>;
  reports: Record<string, string>;
  messages: Array<{ sender: string; content: string; seq: number }>;
  stats: { tokens_in: number; tokens_out: number; llm_calls: number; tool_calls: number } | null;
  progress: { phase: string; detail: string } | null;
}

interface AnalysisDashboardProps {
  runId: string;
}

export function AnalysisDashboard({ runId }: AnalysisDashboardProps) {
  const { status } = useAnalysisWebSocket(runId);
  const queryClient = useQueryClient();
  const wsData = queryClient.getQueryData<WsState>(["analysis", runId, "ws-state"]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Analysis: {runId}</h2>
        <ReconnectionIndicator status={status} attempt={0} />
      </div>
      <StatsBar stats={wsData?.stats ?? null} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgentStatusTable agents={wsData?.agents ?? {}} />
        <MessagesPanel messages={wsData?.messages ?? []} />
      </div>
      <ReportPanel reports={wsData?.reports ?? {}} />
    </div>
  );
}
