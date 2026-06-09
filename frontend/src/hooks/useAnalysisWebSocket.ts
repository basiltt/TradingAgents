/**
 * WebSocket hook for real-time analysis run updates.
 *
 * Connects to `/ws/v1/analysis/:runId`, handles heartbeats, reconnection
 * with exponential backoff, and visibility-change recovery. Streams progress,
 * agent status, messages, stats, and report chunks into React Query cache.
 *
 * @module hooks/useAnalysisWebSocket
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAppDispatch } from "@/store";
import { updateRunStatus } from "@/store/analysis-slice";

// AI-CONTEXT: Reconnection caps prevent infinite retry loops on permanent failures.
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_DELAY = 1000;
const MAX_DELAY = 30000;
/** ±25% reconnect-backoff jitter band — see the delay calc in onclose for rationale. */
const RECONNECT_JITTER_MIN = 0.75;
const RECONNECT_JITTER_SPREAD = 0.5;
// AI-CONTEXT: Ring-buffer cap — prevents memory growth on long-running analyses.
const MAX_MESSAGES = 500;

/**
 * WebSocket close codes that must NOT trigger a reconnect (the failure is permanent
 * or client-caused). Hoisted to module scope so it is allocated once, named, and the
 * meaning of each code is self-documenting:
 * - 1000 NORMAL: clean server-initiated close
 * - 1008 POLICY_VIOLATION / 1009 MESSAGE_TOO_BIG: protocol-level rejections
 * - 4400 BAD_REQUEST / 4403 FORBIDDEN / 4404 RUN_NOT_FOUND: app-level rejections
 */
const NON_RETRIABLE_CLOSE_CODES = [1000, 4400, 4403, 4404, 1008, 1009] as const;

/** Accumulated real-time state from the WebSocket stream, stored in React Query cache. */
export interface WsState {
  /** Map of agent name → status string ("in_progress", "completed", "failed"). */
  agents: Record<string, string>;
  /** Map of report section ID → accumulated markdown content. */
  reports: Record<string, string>;
  /** Ordered message log. `sender` is agent name, `seq` is server-assigned sequence number. */
  messages: Array<{ sender: string; content: string; seq: number }>;
  /** Cumulative token/call usage stats, null until first stats event. */
  stats: { tokens_in: number; tokens_out: number; llm_calls: number; tool_calls: number } | null;
  /** Current phase and detail string, null until first progress event. */
  progress: { phase: string; detail: string } | null;
}

/** Returns a fresh empty WsState — factory function ensures each query cache entry gets an independent object. */
export function emptyWsState(): WsState {
  return { agents: {}, reports: {}, messages: [], stats: null, progress: null };
}

// AI-CONTEXT: Derives WS URL from page origin so it works behind any reverse proxy
// without explicit hostname config. Protocol mirrors HTTP→WS (https→wss, http→ws).
function getWsUrl(runId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/v1/analysis/${encodeURIComponent(runId)}`;
}

/**
 * WebSocket connection lifecycle state.
 * - "connecting": initial connection attempt in flight
 * - "connected": socket open, receiving messages
 * - "reconnecting": temporarily lost, will retry with exponential backoff
 * - "disconnected": permanently closed (terminal run state or max retries exceeded)
 */
export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

const WS_MSG = {
  HEARTBEAT: "heartbeat",
  PROGRESS: "progress",
  STATS: "stats",
  MESSAGE: "message",
  AGENT_STATUS: "agent_status",
  REPORT_CHUNK: "report_chunk",
} as const;

const AGENT_STATUS = {
  IN_PROGRESS: "in_progress",
  IN_PROGRESS_LEGACY: "in progress",
  COMPLETED: "completed",
} as const;

const TERMINAL_PHASES = new Set(["completed", "failed", "cancelled"] as const);

// AI-CONTEXT: Minimum display time prevents agent status flickering when
// "in_progress" and "completed" arrive within the same frame.
const MIN_IN_PROGRESS_MS = 1500;

/**
 * Manages a WebSocket connection to the analysis run stream.
 * @param runId - The analysis run ID to subscribe to.
 * @returns Connection status and reconnection attempt count.
 */
export function useAnalysisWebSocket(runId: string) {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const mountedRef = useRef(true);
  const agentInProgressAt = useRef<Record<string, number>>({});

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
  useEffect(() => {
    updateCacheRef.current = updateCache;
  });

  const [attempt, setAttempt] = useState(0);
  const connectRef = useRef<() => void>(undefined);

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

      if (type === WS_MSG.HEARTBEAT) {
        ws.send(JSON.stringify({ type: "pong" }));
        return;
      }

      if (type === WS_MSG.PROGRESS) {
        const phase = data.phase as string;

        if (TERMINAL_PHASES.has(phase as "completed" | "failed" | "cancelled")) {
          dispatch(
            updateRunStatus({
              runId,
              status: phase as "completed" | "cancelled" | "failed",
              currentAgent: undefined,
            }),
          );
          // Mark all in-progress agents as completed
          updateCacheRef.current((prev) => {
            const updatedAgents = { ...prev.agents };
            for (const [agent, agentStatus] of Object.entries(updatedAgents)) {
              if (agentStatus === AGENT_STATUS.IN_PROGRESS || agentStatus === AGENT_STATUS.IN_PROGRESS_LEGACY) {
                updatedAgents[agent] = AGENT_STATUS.COMPLETED;
              }
            }
            return {
              ...prev,
              agents: updatedAgents,
              progress: { phase, detail: data.detail as string },
            };
          });
          queryClient.invalidateQueries({ queryKey: ["analysis", runId, "details"] });
          queryClient.invalidateQueries({ queryKey: ["analysis", runId, "report"] });
          queryClient.invalidateQueries({ queryKey: ["analysis", runId, "snapshot"] });
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

      if (type === WS_MSG.STATS) {
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

      if (type === WS_MSG.MESSAGE) {
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

      if (type === WS_MSG.AGENT_STATUS) {
        const agent = data.agent as string;
        const newStatus = data.status as string;

        if (newStatus === AGENT_STATUS.IN_PROGRESS) {
          if (!agentInProgressAt.current[agent]) {
            agentInProgressAt.current[agent] = Date.now();
          }
          updateCacheRef.current((prev) => ({
            ...prev,
            agents: { ...prev.agents, [agent]: AGENT_STATUS.IN_PROGRESS },
          }));
          return;
        }

        if (newStatus === AGENT_STATUS.COMPLETED) {
          const startedAt = agentInProgressAt.current[agent];
          const elapsed = startedAt ? Date.now() - startedAt : 0;
          const remaining = MIN_IN_PROGRESS_MS - elapsed;

          const applyCompleted = () => {
            pendingTimersRef.current.delete(timerId);
            if (!mountedRef.current) return;
            updateCacheRef.current((p) => ({
              ...p,
              agents: { ...p.agents, [agent]: AGENT_STATUS.COMPLETED },
            }));
          };

          let timerId: ReturnType<typeof setTimeout>;
          if (!startedAt) {
            // Never saw in_progress — show it briefly first
            agentInProgressAt.current[agent] = Date.now();
            updateCacheRef.current((prev) => ({
              ...prev,
              agents: { ...prev.agents, [agent]: AGENT_STATUS.IN_PROGRESS },
            }));
            timerId = setTimeout(applyCompleted, MIN_IN_PROGRESS_MS);
            pendingTimersRef.current.add(timerId);
          } else if (remaining > 0) {
            // in_progress hasn't been visible long enough — delay completed
            timerId = setTimeout(applyCompleted, remaining);
            pendingTimersRef.current.add(timerId);
          } else {
            applyCompleted();
          }
          return;
        }

        // Other statuses (failed, etc.)
        updateCacheRef.current((prev) => ({
          ...prev,
          agents: { ...prev.agents, [agent]: newStatus },
        }));
        return;
      }

      if (type === WS_MSG.REPORT_CHUNK) {
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

      // AI-CONTEXT: see NON_RETRIABLE_CLOSE_CODES (module scope) for code meanings.
      if (NON_RETRIABLE_CLOSE_CODES.includes(ev.code as (typeof NON_RETRIABLE_CLOSE_CODES)[number])) {
        setStatus("disconnected");
        return;
      }

      if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setStatus("disconnected");
        return;
      }

      setStatus("reconnecting");
      // AI-CONTEXT: ±25% jitter on the backoff (matching useAccountWebSocket) so that
      // after a server restart, every client viewing an analysis does NOT reconnect in
      // lockstep at 1s/2s/4s… — synchronized retries can re-trip a recovering backend
      // (thundering herd). The random factor spreads them out.
      const base = Math.min(BASE_DELAY * 2 ** attemptRef.current, MAX_DELAY);
      const delay = base * (RECONNECT_JITTER_MIN + Math.random() * RECONNECT_JITTER_SPREAD);
      attemptRef.current += 1;
      setAttempt(attemptRef.current);
      reconnectTimerRef.current = setTimeout(() => connectRef.current?.(), delay);
    };

    ws.onerror = () => {};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, dispatch]); // queryClient accessed via stable updateCacheRef

  useEffect(() => {
    connectRef.current = connect;
  });

  useEffect(() => {
    mountedRef.current = true;
    const timersRef = pendingTimersRef.current;
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

    // AI-CONTEXT: BFCache eligibility. An open WebSocket makes the page
    // ineligible for Chrome's back/forward cache, so when the tab is
    // backgrounded (e.g. user switches to another app on mobile) the browser
    // discards and FULLY RELOADS it on return instead of restoring instantly.
    // Closing the socket on `pagehide` lets the page qualify for BFCache;
    // `pageshow` reconnects when it is restored or shown again. We suppress the
    // reconnect-on-close path here by clearing the pending timer and nulling the
    // ref so a clean teardown doesn't schedule a redundant backoff reconnect.
    function handlePageHide() {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close(1000, "pagehide");
    }

    function handlePageShow() {
      if (!mountedRef.current) return;
      const ws = wsRef.current;
      const dead = !ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED;
      if (!dead) return;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      attemptRef.current = 0;
      connect();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);

    return () => {
      mountedRef.current = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
      const timers = timersRef;
      for (const id of timers) {
        clearTimeout(id);
      }
      timers.clear();
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
