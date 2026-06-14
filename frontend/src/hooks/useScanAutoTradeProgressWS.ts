import * as React from "react";

import {
  wsBaseUrl,
  RECONNECT_BASE_MS,
  RECONNECT_MAX_MS,
  shouldReconnect,
} from "@/api/ws";
import type { ScanAutoTradeProgressEvent } from "@/api/client";

/** A coalesced post-scan stage step (latest event per stage), first-seen order. */
export interface ScanStep {
  stage: string;
  status: string;
  pct: number | null;
  /** Accounts done within this stage, when reported. */
  accountsDone?: number;
  accountsTotal?: number;
}

/** Live per-account row, keyed by acct_ordinal (opaque handle). */
export interface ScanAccountRow {
  acctOrdinal: number;
  status: string;
  tradesExecuted: number;
  tradesFailed: number;
  tradesSkipped: number;
  stoppedReason?: string | null;
  dryRun?: boolean | null;
  substatus?: string | null;
  cooloffUntil?: number | null;
}

/** Live placed/skipped order row for the streaming feed (newest-first in UI). */
export interface ScanOrderRow {
  seq: number;
  acctOrdinal?: number | null;
  symbol?: string | null;
  side?: string | null;
  status: string;
  reasonCode?: string | null;
}

export interface ScanProgressState {
  steps: ScanStep[];
  accounts: ScanAccountRow[];
  orders: ScanOrderRow[];
  pct: number | null;
  connected: boolean;
  terminal: boolean;
  /** A confirmed IP-ban cooloff deadline (epoch s), surfaced for the countdown. */
  cooloffUntil: number | null;
}

const TERMINAL_STAGES = new Set(["complete", "failed", "cancelled"]);
const MAX_ORDER_ROWS = 200;

/** Validate a raw WS message is a well-formed progress event (guard-parse). */
function isProgressEvent(m: unknown): m is ScanAutoTradeProgressEvent {
  if (!m || typeof m !== "object") return false;
  const e = m as Record<string, unknown>;
  return (
    e.type === "scan_auto_trade_progress" &&
    typeof e.stage === "string" &&
    typeof e.status === "string" &&
    typeof e.scan_id === "string" &&
    typeof e.seq === "number"
  );
}

/**
 * Subscribe to a scan's post-scan auto-trade progress over
 * `/ws/v1/scanner/{scanId}/auto-trade`. Returns a coalesced, render-ready view.
 *
 * Mirrors useBacktestProgressWS but DIVERGES for a money feed:
 *  - close-code-aware reconnect (no reconnect on 1000/4403/4404/1011);
 *  - full-state reset on scanId change + drop events tagged with a prior scan_id;
 *  - guard-parse every payload so malformed data never reaches state;
 *  - exposes per-account + per-order projections, not just steps.
 *
 * Fail-soft: the WS is progressive enhancement. The caller keeps its 3s poll as
 * the source of truth; this hook simply adds live detail.
 */
export function useScanAutoTradeProgressWS(
  scanId: string | undefined,
  active: boolean,
): ScanProgressState {
  const [steps, setSteps] = React.useState<ScanStep[]>([]);
  const [accounts, setAccounts] = React.useState<ScanAccountRow[]>([]);
  const [orders, setOrders] = React.useState<ScanOrderRow[]>([]);
  const [pct, setPct] = React.useState<number | null>(null);
  const [connected, setConnected] = React.useState(false);
  const [terminal, setTerminal] = React.useState(false);
  const [cooloffUntil, setCooloffUntil] = React.useState<number | null>(null);

  const wsRef = React.useRef<WebSocket | null>(null);
  const reconnectTimer = React.useRef<ReturnType<typeof setTimeout>>(undefined);
  const reconnectDelay = React.useRef(RECONNECT_BASE_MS);
  const mounted = React.useRef(false);
  const byStage = React.useRef<Map<string, ScanStep>>(new Map());
  const byAccount = React.useRef<Map<number, ScanAccountRow>>(new Map());
  const currentScanId = React.useRef<string | undefined>(scanId);
  const terminalRef = React.useRef(terminal);
  React.useEffect(() => {
    terminalRef.current = terminal;
  }, [terminal]);

  // Full reset whenever the scan changes (drop ALL accumulated state).
  React.useEffect(() => {
    currentScanId.current = scanId;
    byStage.current = new Map();
    byAccount.current = new Map();
    setSteps([]);
    setAccounts([]);
    setOrders([]);
    setPct(null);
    setTerminal(false);
    setConnected(false);
    setCooloffUntil(null);
  }, [scanId]);

  // When the socket is gated off (active=false) without a scan change, clear the
  // connection flag so a non-terminal, capped-out tail doesn't show a stale "Live".
  React.useEffect(() => {
    if (!active) setConnected(false);
  }, [active]);

  React.useEffect(() => {
    mounted.current = true;
    if (!scanId || !active) {
      return () => {
        mounted.current = false;
      };
    }

    function applyEvent(ev: ScanAutoTradeProgressEvent) {
      // Drop events tagged with a stale scan_id (late frames from a prior socket).
      if (ev.scan_id && ev.scan_id !== currentScanId.current) return;

      // Step coalesce (latest per stage; a "done" is not overwritten by "active").
      // ONLY pure stage events drive the stepper — a per-account / per-symbol event
      // (carries acct_ordinal or symbol) reuses the stage key as a label channel and
      // must NOT register as a step, else phantom "batch"/"immediate" steps appear and
      // a per-symbol "failed" would flip a stage row to failed.
      const isStageEvent =
        ev.acct_ordinal === null || ev.acct_ordinal === undefined;
      const isOrderEvent = ev.symbol !== null && ev.symbol !== undefined;
      if (isStageEvent && !isOrderEvent) {
        const sm = byStage.current;
        const existing = sm.get(ev.stage);
        const status =
          existing?.status === "done" && ev.status === "active"
            ? existing.status
            : ev.status;
        sm.set(ev.stage, {
          stage: ev.stage,
          status,
          pct: ev.pct,
        });
        setSteps(Array.from(sm.values()));
      }

      if (typeof ev.pct === "number") {
        setPct((prev) => (prev === null ? ev.pct : Math.max(prev, ev.pct!)));
      }

      // Per-account row (keyed by ordinal). Counters are authoritative (from the
      // event), not derived from the truncated order feed.
      if (typeof ev.acct_ordinal === "number") {
        const am = byAccount.current;
        const cur = am.get(ev.acct_ordinal);
        am.set(ev.acct_ordinal, {
          acctOrdinal: ev.acct_ordinal,
          status: ev.status,
          tradesExecuted: ev.trades_executed ?? cur?.tradesExecuted ?? 0,
          tradesFailed: ev.trades_failed ?? cur?.tradesFailed ?? 0,
          tradesSkipped: ev.trades_skipped ?? cur?.tradesSkipped ?? 0,
          stoppedReason: ev.reason_code ?? cur?.stoppedReason ?? null,
          dryRun: ev.dry_run ?? cur?.dryRun ?? null,
          substatus: ev.substatus ?? cur?.substatus ?? null,
          cooloffUntil: ev.cooloff_until ?? cur?.cooloffUntil ?? null,
        });
        setAccounts(Array.from(am.values()).sort((a, b) => a.acctOrdinal - b.acctOrdinal));
      }

      // Per-order feed row (only for events carrying a symbol outcome).
      if (ev.symbol) {
        setOrders((prev) => {
          const next = [
            {
              seq: ev.seq,
              acctOrdinal: ev.acct_ordinal,
              symbol: ev.symbol,
              side: ev.side,
              status: ev.status,
              reasonCode: ev.reason_code,
            },
            ...prev,
          ];
          return next.length > MAX_ORDER_ROWS ? next.slice(0, MAX_ORDER_ROWS) : next;
        });
      }

      if (typeof ev.cooloff_until === "number") setCooloffUntil(ev.cooloff_until);

      // Terminal only on a true terminal stage + terminal status (matches the
      // backend's terminal detection: done/failed/cancelled).
      if (TERMINAL_STAGES.has(ev.stage) && (ev.status === "done" || ev.status === "failed" || ev.status === "cancelled")) {
        setTerminal(true);
      }
    }

    function connect() {
      if (!mounted.current) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(`${wsBaseUrl()}/ws/v1/scanner/${encodeURIComponent(scanId!)}/auto-trade`);
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
          try {
            ws.send("pong");
          } catch {
            /* socket closing */
          }
          return;
        }
        if (isProgressEvent(msg)) applyEvent(msg);
      };

      ws.onclose = (ev) => {
        if (!mounted.current) return;
        setConnected(false);
        wsRef.current = null;
        // A permanent close code (incl. the server's clean 1000 for an
        // unknown/terminal scan) marks us terminal and stops reconnecting.
        if (!shouldReconnect(ev.code)) {
          setTerminal(true);
          return;
        }
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
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      // StrictMode safety: defer close if mid-handshake (see useBacktestProgressWS).
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
  }, [scanId, active]);

  return { steps, accounts, orders, pct, connected, terminal, cooloffUntil };
}
