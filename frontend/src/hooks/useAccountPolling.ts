import { useEffect, useRef, useCallback } from "react";
import { accountsApi, type DashboardCard } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard } from "@/store/accounts-slice";

export function useAccountPolling() {
  const dispatch = useAppDispatch();
  const { pollingIntervalMs } = useAppSelector((s) => s.accounts);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const poll = useCallback(async () => {
    if (document.hidden) return;
    controllerRef.current?.abort();
    controllerRef.current = new AbortController();
    try {
      const cards = await accountsApi.getDashboard();
      dispatch(setDashboard(cards));
    } catch {
      // silent — dashboard still shows last data
    }
  }, [dispatch]);

  useEffect(() => {
    if (pollingIntervalMs <= 0) return;

    intervalRef.current = setInterval(poll, pollingIntervalMs);

    const onVisibilityChange = () => {
      if (!document.hidden) poll();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      controllerRef.current?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [poll, pollingIntervalMs]);

  return { refresh: poll };
}
