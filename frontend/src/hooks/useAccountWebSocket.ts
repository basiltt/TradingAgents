import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAppDispatch } from "@/store";
import { updateCardRealtime, handleCloseExecution, setDashboard } from "@/store/accounts-slice";
import {
  onStateChange as onAIStateChange,
  onExecution as onAIExecution,
  fetchAIManagerStatus,
  fetchDecisions,
  fetchLogs,
  onLLMStarted,
  onLLMCompleted,
  onCapabilityUpdate,
  onMarketCommentary,
  addAttentionItem,
  fetchInsights,
} from "@/store/ai-manager-slice";
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
import { accountsApi } from "@/api/client";

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
  const pingWatchdog = useRef<ReturnType<typeof setTimeout>>(undefined);
  const mounted = useRef(true);
  const queryClientRef = useRef(queryClient);
  const connectRef = useRef<() => void>(undefined);
  const dashboardRefreshTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const refreshDashboard = useCallback(() => {
    clearTimeout(dashboardRefreshTimer.current);
    dashboardRefreshTimer.current = setTimeout(async () => {
      if (!mounted.current) return;
      try {
        const cards = await accountsApi.getDashboard();
        if (mounted.current) dispatch(setDashboard(cards));
      } catch { /* polling will catch up */ }
    }, 1500);
  }, [dispatch]);

  useEffect(() => { queryClientRef.current = queryClient; });

  const lastFetchRef = useRef(0);

  const connect = useCallback(() => {
    if (!mounted.current) return;
    const existing = wsRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectDelay.current = RECONNECT_BASE;
      dispatch(setWsConnected(true));
      const now = Date.now();
      if (now - lastFetchRef.current > 5000) {
        lastFetchRef.current = now;
        fetchAllActiveTrades(dispatch).catch(() => {});
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
      }
      refreshDashboard();
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
        clearTimeout(pingWatchdog.current);
        pingWatchdog.current = setTimeout(() => {
          ws.close();
        }, 45000);
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
        refreshDashboard();
      }

      if (msg.type === "master_close_progress" || msg.type === "master_close_complete" || msg.type === "demo_reset_progress" || msg.type === "demo_reset_complete") {
        window.dispatchEvent(new CustomEvent(msg.type as string, { detail: msg }));
      }

      if (msg.type === "trade.opened" && msg.data) {
        dispatch(addActiveTrade(msg.data as Trade));
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
        refreshDashboard();
      }
      if (msg.type === "trade.closed" && msg.trade_id) {
        dispatch(removeActiveTrade(msg.trade_id as string));
        dispatch(clearPendingAction(msg.trade_id as string));
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "history"] });
        queryClientRef.current.invalidateQueries({ queryKey: ["trades", "stats"] });
        refreshDashboard();
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
      if (msg.type === "ai_manager.state_change" && msg.account_id) {
        const accountId = msg.account_id as string;
        dispatch(onAIStateChange(msg as unknown as { account_id: string; state: string; enabled: boolean }));
        dispatch(fetchAIManagerStatus(accountId));
        dispatch(fetchLogs({ accountId, limit: 50 }));
      }
      if (msg.type === "ai_manager.execution" && msg.account_id) {
        const accountId = msg.account_id as string;
        dispatch(onAIExecution(msg as unknown as { account_id: string; action: string; symbol: string; pnl: number }));
        dispatch(fetchAIManagerStatus(accountId));
        // Refresh decisions to show the newly recorded decision; limit=15 matches panel default
        dispatch(fetchDecisions({ accountId, limit: 15 }));
        dispatch(fetchLogs({ accountId, limit: 50 }));
        // Note: fetchPerformance is intentionally not called here because we don't know
        // the user's selected period (1d/7d/30d). The AIMonitorPanel polls status every 30s
        // and the user can switch periods manually.
      }

      // Dashboard enhancement WS handlers
      if (msg.type === "ai_manager.llm_started" && msg.account_id) {
        dispatch(onLLMStarted({ account_id: msg.account_id as string, call_id: msg.call_id as string }));
      }
      if (msg.type === "ai_manager.llm_call_complete" && msg.account_id) {
        dispatch(onLLMCompleted(msg as unknown as Parameters<typeof onLLMCompleted>[0]));
      }
      if (msg.type === "ai_manager.capability_update" && msg.account_id) {
        dispatch(onCapabilityUpdate(msg as unknown as Parameters<typeof onCapabilityUpdate>[0]));
      }
      if (msg.type === "ai_manager.market_commentary" && msg.account_id) {
        dispatch(onMarketCommentary(msg as unknown as Parameters<typeof onMarketCommentary>[0]));
        dispatch(fetchInsights(msg.account_id as string));
      }
      if (msg.type === "ai_manager.attention_needed" && msg.account_id) {
        dispatch(addAttentionItem({ account_id: msg.account_id as string, ...(msg.item as Record<string, unknown>) } as unknown as Parameters<typeof addAttentionItem>[0]));
      }
    };

    ws.onclose = () => {
      dispatch(setWsConnected(false));
      clearTimeout(pingWatchdog.current);
      if (!mounted.current) return;
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, RECONNECT_MAX) * (0.75 + Math.random() * 0.5);
        connectRef.current?.();
      }, reconnectDelay.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [dispatch, refreshDashboard]);

  useEffect(() => {
    connectRef.current = connect;
  });

  useEffect(() => {
    mounted.current = true;
    connect();

    function handleVisibilityChange() {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
      clearTimeout(reconnectTimer.current);
      connectRef.current?.();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      mounted.current = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      clearTimeout(reconnectTimer.current);
      clearTimeout(pingWatchdog.current);
      clearTimeout(dashboardRefreshTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
