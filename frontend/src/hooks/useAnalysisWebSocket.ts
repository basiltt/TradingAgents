import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAppDispatch } from "@/store";
import { updateRunStatus } from "@/store/analysis-slice";

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_DELAY = 1000;
const MAX_DELAY = 30000;
const MAX_MESSAGES = 500;

export interface WsState {
  agents: Record<string, string>;
  reports: Record<string, string>;
  messages: Array<{ sender: string; content: string; seq: number }>;
  stats: { tokens_in: number; tokens_out: number; llm_calls: number; tool_calls: number } | null;
  progress: { phase: string; detail: string } | null;
}

export function emptyWsState(): WsState {
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
        (prev) => updater(prev ?? emptyWsState()),
      );
    },
    [queryClient, runId],
  );

  const updateCacheRef = useRef(updateCache);
  updateCacheRef.current = updateCache;

  const [attempt, setAttempt] = useState(0);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    const ws = new WebSocket(getWsUrl(runId));
    wsRef.current = ws;
    const isReconnect = attemptRef.current > 0;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus("connected");
      attemptRef.current = 0;
      // Only wipe state on the very first connect — on reconnects keep
      // existing data visible while the server replay streams back in.
      if (!isReconnect) {
        updateCacheRef.current(() => emptyWsState());
      }
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
        const phase = data.phase as string;
        const terminal = ["completed", "failed", "cancelled"];

        if (terminal.includes(phase)) {
          dispatch(
            updateRunStatus({
              runId,
              status: phase === "completed" ? "completed" : phase === "cancelled" ? "cancelled" : "failed",
              currentAgent: undefined,
            }),
          );
          ws.close(1000, "Run terminal");
          setStatus("disconnected");
          return;
        }

        dispatch(
          updateRunStatus({
            runId,
            status: "running",
            currentAgent: phase,
          }),
        );
        updateCacheRef.current((prev) => ({
          ...prev,
          progress: { phase, detail: data.detail as string },
        }));
        return;
      }

      if (type === "stats") {
        updateCacheRef.current((prev) => ({
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
        updateCacheRef.current((prev) => {
          const next = [
            ...prev.messages,
            {
              sender: data.sender as string,
              content: data.content as string,
              seq: data.seq as number,
            },
          ];
          return {
            ...prev,
            messages: next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next,
          };
        });
        return;
      }

      if (type === "agent_status") {
        updateCacheRef.current((prev) => ({
          ...prev,
          agents: { ...prev.agents, [data.agent as string]: data.status as string },
        }));
        return;
      }

      if (type === "report_chunk") {
        updateCacheRef.current((prev) => ({
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
      if (ws !== wsRef.current && wsRef.current !== null) return;
      wsRef.current = null;

      const NON_RETRIABLE = [1000, 4400, 4403, 4404, 1008, 1009];
      if (NON_RETRIABLE.includes(ev.code)) {
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
      setAttempt(attemptRef.current);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {};
  }, [runId, dispatch]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    // Android Chrome kills the WS when the app is backgrounded.
    // Reconnect immediately when the tab becomes visible again instead
    // of waiting for the exponential backoff timer.
    function handleVisibilityChange() {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      const dead = !ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED;
      if (!dead) return;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      connect();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      mountedRef.current = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
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

  return { status, attempt };
}
