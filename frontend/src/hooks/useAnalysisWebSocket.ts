import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAppDispatch } from "@/store";
import { updateRunStatus } from "@/store/analysis-slice";

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_DELAY = 1000;
const MAX_DELAY = 30000;

interface WsState {
  agents: Record<string, string>;
  reports: Record<string, string>;
  messages: Array<{ sender: string; content: string; seq: number }>;
  stats: { tokens_in: number; tokens_out: number; llm_calls: number; tool_calls: number } | null;
  progress: { phase: string; detail: string } | null;
}

function emptyState(): WsState {
  return { agents: {}, reports: {}, messages: [], stats: null, progress: null };
}

function getWsUrl(runId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/v1/analysis/${encodeURIComponent(runId)}`;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

export function useAnalysisWebSocket(runId: string) {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const updateCache = useCallback(
    (updater: (prev: WsState) => WsState) => {
      queryClient.setQueryData<WsState>(
        ["analysis", runId, "ws-state"],
        (prev) => updater(prev ?? emptyState()),
      );
    },
    [queryClient, runId],
  );

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    const ws = new WebSocket(getWsUrl(runId));
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus("connected");
      attemptRef.current = 0;
      ws.send(JSON.stringify({ type: "replay" }));
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (!mountedRef.current) return;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(ev.data as string);
      } catch {
        return;
      }

      const type = data.type as string;

      if (type === "heartbeat") {
        ws.send(JSON.stringify({ type: "pong" }));
        return;
      }

      if (type === "progress") {
        dispatch(
          updateRunStatus({
            runId,
            status: "running",
            currentAgent: data.phase as string,
          }),
        );
        updateCache((prev) => ({
          ...prev,
          progress: { phase: data.phase as string, detail: data.detail as string },
        }));
        return;
      }

      if (type === "stats") {
        updateCache((prev) => ({
          ...prev,
          stats: {
            tokens_in: data.tokens_in as number,
            tokens_out: data.tokens_out as number,
            llm_calls: data.llm_calls as number,
            tool_calls: data.tool_calls as number,
          },
        }));
        return;
      }

      if (type === "message") {
        updateCache((prev) => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              sender: data.sender as string,
              content: data.content as string,
              seq: data.seq as number,
            },
          ],
        }));
        return;
      }

      if (type === "agent_status") {
        updateCache((prev) => ({
          ...prev,
          agents: { ...prev.agents, [data.agent as string]: data.status as string },
        }));
        return;
      }

      if (type === "report_chunk") {
        updateCache((prev) => ({
          ...prev,
          reports: {
            ...prev.reports,
            [data.section as string]: data.append
              ? (prev.reports[data.section as string] ?? "") + (data.content as string)
              : (data.content as string),
          },
        }));
        return;
      }
    };

    ws.onclose = (ev: CloseEvent) => {
      if (!mountedRef.current) return;
      wsRef.current = null;

      if (ev.code === 1000 || ev.code === 4404) {
        setStatus("disconnected");
        return;
      }

      if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setStatus("disconnected");
        return;
      }

      setStatus("reconnecting");
      const delay = Math.min(BASE_DELAY * 2 ** attemptRef.current, MAX_DELAY);
      attemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {};
  }, [runId, dispatch, updateCache]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { status };
}
