import { useEffect, useRef, useCallback, useState } from "react";
import { accountsApi } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setLoading } from "@/store/accounts-slice";
import { logger } from "@/lib/logger";

/** Minimum delay between manual refresh calls to prevent API flooding (ms). */
const MANUAL_REFRESH_COOLDOWN_MS = 10_000;

/**
 * Polls the accounts dashboard API on a configurable interval.
 * Pauses when tab is hidden. Returns `{ refresh, isRefreshDisabled }` for
 * manual refresh with a 10s cooldown.
 */
export function useAccountPolling() {
  const dispatch = useAppDispatch();
  const { pollingIntervalMs } = useAppSelector((s) => s.accounts);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const lastManualRef = useRef<number>(0);
  const cooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [refreshCooldown, setRefreshCooldown] = useState(false);

  const poll = useCallback(async () => {
    if (document.hidden) return;
    // AI-CONTEXT: In-flight guard. Previously every tick aborted the prior request;
    // if the backend was slower than the poll interval, each tick killed the
    // still-running request before it could resolve, so the dashboard NEVER updated
    // under load — exactly when freshness matters most. Now a tick is skipped while a
    // request is in flight, letting it complete. The controller is retained only so
    // the unmount cleanup can abort a pending request.
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    controllerRef.current = new AbortController();
    try {
      const cards = await accountsApi.getDashboard(undefined, controllerRef.current.signal);
      dispatch(setDashboard(cards));
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        logger.warn("useAccountPolling", "poll failed", { message: err.message });
      }
    } finally {
      inFlightRef.current = false;
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

  const isFirstPollRef = useRef(true);

  useEffect(() => {
    if (pollingIntervalMs <= 0) return;

    if (isFirstPollRef.current) {
      dispatch(setLoading());
      isFirstPollRef.current = false;
    }
    poll();
    intervalRef.current = setInterval(poll, pollingIntervalMs);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      controllerRef.current?.abort();
      // AI-CONTEXT: Do NOT clear cooldownTimerRef here. This effect re-runs whenever
      // pollingIntervalMs changes; clearing the manual-refresh cooldown timer on that
      // re-run would leave refreshCooldown stuck `true` forever (the reset timer is
      // gone, so the button never re-enables). The cooldown timer is owned by
      // manualRefresh and torn down only on unmount — see the effect below.
    };
  }, [dispatch, poll, pollingIntervalMs]);

  // AI-CONTEXT: Unmount-only cleanup for the manual-refresh cooldown timer, kept
  // separate from the interval effect so an interval change can't strand it.
  useEffect(() => {
    return () => {
      if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
    };
  }, []);

  return { refresh: manualRefresh, isRefreshDisabled: refreshCooldown };
}
