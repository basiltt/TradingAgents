import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAppDispatch } from "@/store";
import { updateCardRealtime, handleCloseExecution } from "@/store/accounts-slice";
import type { Trade } from "@/components/trades/types";
import {
  addActiveTrade,
  removeActiveTrade,
  updateActiveTrade,
  clearPendingAction,
  revertOptimisticUpdate,
  setWsConnected,
  updateUnrealizedPnl,
} from "@/store/trades-slice";
import { fetchAllActiveTrades } from "@/components/trades/hooks/useTradePolling";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
const WS_URL = `${WS_BASE}/ws/v1/accounts`;
const RECONNECT_BASE = 2000;
const RECONNECT_MAX = 30000;

export function useAccountWebSocket() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const mounted = useRef(true);
  const queryClientRef = useRef(queryClient);
  const connectRef = useRef<() => void>(undefined);

  useEffect(() => { queryClientRef.current = queryClient; });

  const lastFetchRef = useRef(0);

  const connect = useCallback(() => {
    if (!mounted.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectDelay.current = RECONNECT_BASE;
      dispatch(setWsConnected(true));
      const now = Date.now();
      if (now - lastFetchRef.current > 5000) {
        lastFetchRef.current = now;
        fetchAllActiveTrades(dispatch);
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
      }
    };

    ws.onmessage = (event) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === "ping") {
        if (ws.readyState === WebSocket.OPEN) ws.send("pong");
        return;
      }
      if (msg.account_id && msg.type === "wallet_update") {
        dispatch(updateCardRealtime(msg as unknown as { account_id: string; type: string; data: Record<string, string> }));
      }
      if (msg.type === "position_update" && msg.account_id && msg.data) {
        const d = msg.data as Record<string, string>;
        if (d.symbol && d.side && d.unrealisedPnl !== undefined) {
          dispatch(updateUnrealizedPnl({
            account_id: msg.account_id as string,
            symbol: d.symbol,
            side: d.side,
            unrealized_pnl: parseFloat(d.unrealisedPnl),
          }));
        }
      }
      if (msg.account_id && msg.type === "close_execution") {
        const closed = typeof msg.closed === "number" ? msg.closed : 0;
        dispatch(handleCloseExecution({ account_id: msg.account_id as string, data: { closed } }));
      }

      if (msg.type === "trade.opened" && msg.data) {
        dispatch(addActiveTrade(msg.data as Trade));
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
      }
      if (msg.type === "trade.closed" && msg.trade_id) {
        dispatch(removeActiveTrade(msg.trade_id as string));
        dispatch(clearPendingAction(msg.trade_id as string));
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "history"] });
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
      }
      if (msg.type === "trade.partially_closed" && msg.trade_id) {
        dispatch(clearPendingAction(msg.trade_id as string));
        const childPnl = typeof msg.realized_pnl === "number" ? msg.realized_pnl : 0;
        dispatch(updateActiveTrade({
          trade_id: msg.trade_id as string,
          updates: {
            filled_qty: msg.filled_qty as number,
            version: msg.version as number,
            status: "partially_closed",
          },
          accumulatePnl: childPnl,
        }));
      }
      if (msg.type === "trade.close_failed" && msg.trade_id) {
        dispatch(revertOptimisticUpdate(msg.trade_id as string));
        dispatch(clearPendingAction(msg.trade_id as string));
        toast.error(`Close failed: ${(msg.error_message as string) || "unknown error"}`);
      }
    };

    ws.onclose = () => {
      dispatch(setWsConnected(false));
      if (!mounted.current) return;
      reconnectTimer.current = setTimeout(() => {
        const jitter = 0.5 + Math.random();
        reconnectDelay.current = Math.min(reconnectDelay.current * 2 * jitter, RECONNECT_MAX);
        connectRef.current?.();
      }, reconnectDelay.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [dispatch]);

  useEffect(() => {
    connectRef.current = connect;
  });

  useEffect(() => {
    mounted.current = true;
    connect();
    return () => {
      mounted.current = false;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
