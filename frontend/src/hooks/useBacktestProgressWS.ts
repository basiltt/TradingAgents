import * as React from "react";

/** WS base — mirrors useAccountWebSocket: same-origin by default, overridable. */
const WS_BASE =
  import.meta.env.VITE_WS_BASE_URL ||
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

const RECONNECT_BASE_MS = 1500;
const RECONNECT_MAX_MS = 8000;

/** A single backtest stage event streamed from the backend. */
export interface BacktestProgressEvent {
  type: "backtest_progress";
  run_id: string;
  /** Stable machine key for the step list (e.g. "loading_klines"). */
  stage: string;
  /** Human title shown in the UI. */
  label: string;
  /** Optional specifics ("480 symbols", "1243 signals"). */
  detail: string;
  /** Overall progress 0-100, or null. */
  pct: number | null;
  /** active | done | failed */
  status: "active" | "done" | "failed";
  /** Monotonic per-run sequence. */
  seq: number;
  ts: number;
}

/** A coalesced step (latest event per stage), in first-seen order. */
export interface BacktestStep {
  stage: string;
  label: string;
  detail: string;
  status: "active" | "done" | "failed";
  pct: number | null;
}

export interface BacktestProgressState {
  /** Ordered, de-duplicated steps (one row per stage, latest wins). */
  steps: BacktestStep[];
  /** Latest overall pct seen (0-100), or null. */
  pct: number | null;
  /** True once the WS has connected at least once. */
  connected: boolean;
  /** True once a terminal (complete/failed) stage arrives. */
  terminal: boolean;
}

/**
 * Subscribe to a backtest's real-time stage stream over
 * `/ws/v1/backtest/{runId}`. Returns an ordered, coalesced step list the UI can
 * render directly. The backend replays the run's history on connect, so a late
 * subscriber still sees earlier steps.
 *
 * Resilient: reconnects with backoff while the run is active; stops on a terminal
 * stage. WS failure is non-fatal — the caller keeps its polling-based progress as
 * the source of truth for status, and simply shows fewer details.
 *
 * @param runId  The run to stream. When undefined OR `active` is false, the socket
 *               is not opened (a completed run needs no live stream).
 * @param active Whether the run is still pending/running (open the socket only then).
 */
export function useBacktestProgressWS(
  runId: string | undefined,
  active: boolean,
): BacktestProgressState {
  const [steps, setSteps] = React.useState<BacktestStep[]>([]);
  const [pct, setPct] = React.useState<number | null>(null);
  const [connected, setConnected] = React.useState(false);
  const [terminal, setTerminal] = React.useState(false);

  const wsRef = React.useRef<WebSocket | null>(null);
  const reconnectTimer = React.useRef<ReturnType<typeof setTimeout>>(undefined);
  const reconnectDelay = React.useRef(RECONNECT_BASE_MS);
  const mounted = React.useRef(false);
  // Coalesce by stage: stage -> step, plus first-seen order.
  const byStage = React.useRef<Map<string, BacktestStep>>(new Map());
  // Ref mirror of `terminal` so the WS onclose handler reads the latest value
  // without re-creating the connect effect (declared BEFORE the effect that uses it).
  const terminalRef = React.useRef(terminal);
  React.useEffect(() => {
    terminalRef.current = terminal;
  }, [terminal]);

  // Reset accumulated state whenever the run changes.
  React.useEffect(() => {
    byStage.current = new Map();
    setSteps([]);
    setPct(null);
    setTerminal(false);
  }, [runId]);

  React.useEffect(() => {
    mounted.current = true;
    if (!runId || !active) {
      return () => {
        mounted.current = false;
      };
    }

    function applyEvent(ev: BacktestProgressEvent) {
      const map = byStage.current;
      const existing = map.get(ev.stage);
      // A "done" status must not be overwritten by a later duplicate "active".
      const status =
        existing?.status === "done" && ev.status === "active"
          ? existing.status
          : ev.status;
      map.set(ev.stage, {
        stage: ev.stage,
        label: ev.label,
        detail: ev.detail,
        status,
        pct: ev.pct,
      });
      setSteps(Array.from(map.values()));
      if (typeof ev.pct === "number") {
        setPct((prev) => (prev === null ? ev.pct : Math.max(prev, ev.pct!)));
      }
      if ((ev.stage === "complete" || ev.stage === "failed") && ev.status !== "active") {
        setTerminal(true);
      }
    }

    function connect() {
      if (!mounted.current) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(`${WS_BASE}/ws/v1/backtest/${runId}`);
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mounted.current) return;
        setConnected(true);
        reconnectDelay.current = RECONNECT_BASE_MS;
      };

      ws.onmessage = (e) => {
        if (!mounted.current) return;
        let msg: unknown;
        try {
          msg = JSON.parse(e.data as string);
        } catch {
          return;
        }
        const m = msg as { type?: string };
        if (m.type === "ping") {
          // keepalive — reply so the server's receive doesn't time out
          try {
            ws.send("pong");
          } catch {
            /* socket closing */
          }
          return;
        }
        if (m.type === "backtest_progress") {
          applyEvent(msg as BacktestProgressEvent);
        }
      };

      ws.onclose = () => {
        if (!mounted.current) return;
        wsRef.current = null;
        // Reconnect only while the run is still active and not terminal.
        if (active && !terminalRef.current) scheduleReconnect();
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      };
    }

    function scheduleReconnect() {
      clearTimeout(reconnectTimer.current);
      const delay = Math.min(reconnectDelay.current, RECONNECT_MAX_MS);
      reconnectDelay.current = Math.min(delay * 2, RECONNECT_MAX_MS);
      reconnectTimer.current = setTimeout(connect, delay);
    }

    connect();

    return () => {
      mounted.current = false;
      clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (!ws) return;
      // Detach handlers FIRST so this teardown can't trigger a reconnect.
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      // CRITICAL (React StrictMode): calling close() on a socket that is still
      // CONNECTING aborts the handshake with "WebSocket is closed before the
      // connection is established" and churns reconnects. StrictMode mounts →
      // effect opens the WS → immediately unmounts → this cleanup runs while the
      // socket is mid-handshake. So if it's still CONNECTING, defer the close to
      // onopen (which fires once the handshake completes); only close immediately
      // when already OPEN.
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen = () => {
          try {
            ws.close(1000, "unmount");
          } catch {
            /* noop */
          }
        };
      } else if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.close(1000, "unmount");
        } catch {
          /* noop */
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, active]);

  return { steps, pct, connected, terminal };
}
