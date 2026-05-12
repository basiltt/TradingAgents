import { useEffect, useState, useRef } from "react";

export type ConnStatus = "idle" | "checking" | "ok" | "error";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function useConnectivityCheck(
  url: string | undefined,
  apiKey?: string,
  debounceMs = 800,
  provider?: string,
) {
  const [status, setStatus] = useState<ConnStatus>("idle");
  const [latency, setLatency] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();

    const trimmed = url?.trim();

    // Need either a custom URL or a provider+key to check
    if (!trimmed && !provider) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting state for new check cycle
      setStatus("idle");
      return;
    }
    if (!trimmed && !apiKey?.trim()) {
      setStatus("idle");
      return;
    }

    setStatus("checking");
    const ac = new AbortController();
    abortRef.current = ac;

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/v1/connectivity-check`, {
          method: "POST",
          signal: ac.signal,
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({
            provider: provider || "",
            api_key: apiKey || null,
            custom_url: trimmed || null,
          }),
        });
        if (!res.ok) {
          setStatus("error");
          setErrorMsg(`Backend error: HTTP ${res.status}`);
          return;
        }
        const data = await res.json();
        if (data.status === "ok") {
          setStatus("ok");
          setLatency(data.latency_ms ?? null);
          setErrorMsg(null);
        } else {
          setStatus("error");
          setLatency(data.latency_ms ?? null);
          setErrorMsg(data.error || "Unknown error");
        }
      } catch {
        if (ac.signal.aborted) return;
        setStatus("error");
        setLatency(null);
        setErrorMsg("Backend unavailable");
      }
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [url, apiKey, debounceMs, provider]);

  return { status, latency, errorMsg };
}
