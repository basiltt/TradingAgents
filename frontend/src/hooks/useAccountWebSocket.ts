import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { useAppDispatch } from "@/store";
import { updateCardRealtime, handleCloseExecution } from "@/store/accounts-slice";
import {
  addActiveTrade,
  removeActiveTrade,
  updateActiveTrade,
  clearPendingAction,
  revertOptimisticUpdate,
  setWsConnected,
} from "@/store/trades-slice";

const WS_URL = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/v1/accounts`;
const RECONNECT_BASE = 2000;
const RECONNECT_MAX = 30000;

export function useAccountWebSocket() {
  const dispatch = useAppDispatch();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const mounted = useRef(true);
  const connectRef = useRef<() => void>();

  const connect = useCallback(() => {
    if (!mounted.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectDelay.current = RECONNECT_BASE;
      dispatch(setWsConnected(true));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "ping") {
          ws.send("pong");
          return;
        }
        if (msg.account_id && (msg.type === "wallet_update" || msg.type === "position_update")) {
          dispatch(updateCardRealtime(msg));
        }
        if (msg.account_id && msg.type === "close_execution") {
          dispatch(handleCloseExecution(msg));
        }

        if (msg.type === "trade.opened" && msg.data) {
          dispatch(addActiveTrade(msg.data));
        }
        if (msg.type === "trade.closed" && msg.trade_id) {
          dispatch(removeActiveTrade(msg.trade_id));
          dispatch(clearPendingAction(msg.trade_id));
        }
        if (msg.type === "trade.partially_closed" && msg.trade_id) {
          dispatch(updateActiveTrade({
            trade_id: msg.trade_id,
            updates: {
              filled_qty: msg.filled_qty,
              realized_pnl: msg.realized_pnl,
              version: msg.version,
              status: "partially_closed",
            },
          }));
          dispatch(clearPendingAction(msg.trade_id));
        }
        if (msg.type === "trade.close_failed" && msg.trade_id) {
          dispatch(revertOptimisticUpdate(msg.trade_id));
          dispatch(clearPendingAction(msg.trade_id));
          toast.error(`Close failed for trade ${msg.trade_id.slice(0, 8)}…`);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      dispatch(setWsConnected(false));
      if (!mounted.current) return;
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, RECONNECT_MAX);
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
