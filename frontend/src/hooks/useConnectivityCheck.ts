import { useEffect, useState, useRef } from "react";

export type ConnStatus = "idle" | "checking" | "ok" | "error";

export function useConnectivityCheck(url: string | undefined, debounceMs = 800) {
  const [status, setStatus] = useState<ConnStatus>("idle");
  const [latency, setLatency] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    setLatency(null);
    setErrorMsg(null);

    const trimmed = url?.trim();
    if (!trimmed) {
      setStatus("idle");
      return;
    }

    setStatus("checking");
    const ac = new AbortController();
    abortRef.current = ac;

    const timer = setTimeout(async () => {
      const start = performance.now();
      try {
        const base = trimmed.replace(/\/+$/, "");
        const res = await fetch(`${base}/v1/models`, {
          signal: ac.signal,
          headers: { Authorization: "Bearer dummy" },
        });
        const elapsed = Math.round(performance.now() - start);
        setLatency(elapsed);
        if (res.ok) {
          setStatus("ok");
          setErrorMsg(null);
        } else {
          setStatus("error");
          setErrorMsg(`HTTP ${res.status}`);
        }
      } catch (err) {
        if (ac.signal.aborted) return;
        setStatus("error");
        setLatency(null);
        setErrorMsg(err instanceof TypeError ? "Connection refused" : String(err));
      }
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [url, debounceMs]);

  return { status, latency, errorMsg };
}
