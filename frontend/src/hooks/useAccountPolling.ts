import { useEffect, useRef, useCallback, useState } from "react";
import { accountsApi } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard } from "@/store/accounts-slice";

const MANUAL_REFRESH_COOLDOWN_MS = 10_000;

export function useAccountPolling() {
  const dispatch = useAppDispatch();
  const { pollingIntervalMs } = useAppSelector((s) => s.accounts);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const lastManualRef = useRef<number>(0);
  const cooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [refreshCooldown, setRefreshCooldown] = useState(false);

  const poll = useCallback(async () => {
    if (document.hidden) return;
    controllerRef.current?.abort();
    controllerRef.current = new AbortController();
    try {
      const cards = await accountsApi.getDashboard(undefined, controllerRef.current.signal);
      dispatch(setDashboard(cards));
    } catch {
      // silent — dashboard still shows last data
    }
  }, [dispatch]);

  const manualRefresh = useCallback(async () => {
    const now = Date.now();
    if (now - lastManualRef.current < MANUAL_REFRESH_COOLDOWN_MS) {
      return;
    }
    lastManualRef.current = now;
    setRefreshCooldown(true);
    if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
    cooldownTimerRef.current = setTimeout(() => setRefreshCooldown(false), MANUAL_REFRESH_COOLDOWN_MS);
    await poll();
  }, [poll]);

  useEffect(() => {
    if (pollingIntervalMs <= 0) return;

    poll();
    intervalRef.current = setInterval(poll, pollingIntervalMs);

    const onVisibilityChange = () => {
      if (!document.hidden) poll();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
      controllerRef.current?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [poll, pollingIntervalMs]);

  return { refresh: manualRefresh, isRefreshDisabled: refreshCooldown };
}
