import { useState, useRef, useEffect } from "react";
import { accountsApi } from "@/api/client";

interface Props {
  accountId: string | null;
  onComplete: () => void;
  onClose: () => void;
}

const PRESETS = [
  { value: "1w", label: "Older than 1W" },
  { value: "1m", label: "Older than 1M" },
  { value: "3m", label: "Older than 3M" },
  { value: "6m", label: "Older than 6M" },
  { value: "1y", label: "Older than 1Y" },
  { value: "all", label: "All Data" },
] as const;

type Step = "select" | "confirm" | "double-confirm" | "done";

export function CleanupDialog({ accountId, onComplete, onClose }: Props) {
  const [step, setStep] = useState<Step>("select");
  const [mode, setMode] = useState<"preset" | "custom">("preset");
  const [preset, setPreset] = useState<string>("");
  const [beforeDate, setBeforeDate] = useState("");
  const [afterDate, setAfterDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [count, setCount] = useState(0);
  const [result, setResult] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const safeClose = () => {
    if (!loading) onClose();
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [loading, onClose]);

  const scopeLabel = accountId ? "this account" : "all accounts";

  const handlePreview = async () => {
    setError(null);
    setLoading(true);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const params = mode === "preset"
        ? { preset }
        : { before: beforeDate || undefined, after: afterDate || undefined };
      const resp = await accountsApi.countSnapshots(accountId, params, controller.signal);
      setCount(resp.total);
      if (preset === "all" || resp.total >= 100) {
        setStep("double-confirm");
      } else {
        setStep("confirm");
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Failed to count snapshots");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setError(null);
    setLoading(true);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const params = mode === "preset"
        ? { preset }
        : { before: beforeDate || undefined, after: afterDate || undefined };
      const resp = await accountsApi.cleanupSnapshots(accountId, params, controller.signal);
      setResult(resp.total);
      setStep("done");
    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Failed to cleanup snapshots");
    } finally {
      setLoading(false);
    }
  };

  const canProceed = mode === "preset" ? !!preset : !!(beforeDate || afterDate);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Cleanup history" onClick={safeClose}>
      <div className="bg-card rounded-2xl border border-border shadow-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold">Cleanup History</h3>
          <button onClick={safeClose} disabled={loading} className="p-1 rounded-lg hover:bg-muted transition-colors disabled:opacity-50">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-destructive/10 text-destructive text-sm">{error}</div>
        )}

        {step === "select" && (
          <>
            <div className="flex gap-2 mb-4">
              <button
                onClick={() => setMode("preset")}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  mode === "preset" ? "bg-primary text-white" : "bg-muted/50 text-muted-foreground hover:text-foreground"
                }`}
              >
                Presets
              </button>
              <button
                onClick={() => setMode("custom")}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  mode === "custom" ? "bg-primary text-white" : "bg-muted/50 text-muted-foreground hover:text-foreground"
                }`}
              >
                Custom Range
              </button>
            </div>

            {mode === "preset" ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4">
                {PRESETS.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => setPreset(p.value)}
                    className={`px-3 py-2 rounded-xl text-sm font-medium transition-all ${
                      preset === p.value
                        ? p.value === "all" ? "bg-destructive text-white" : "bg-primary text-white"
                        : "bg-muted/50 text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            ) : (
              <div className="space-y-3 mb-4">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Delete after (oldest)</label>
                  <input
                    type="date"
                    value={afterDate}
                    onChange={(e) => setAfterDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-muted/50 text-sm border border-border outline-none focus:ring-1 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Delete before (newest)</label>
                  <input
                    type="date"
                    value={beforeDate}
                    onChange={(e) => setBeforeDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-muted/50 text-sm border border-border outline-none focus:ring-1 focus:ring-primary/50"
                  />
                </div>
              </div>
            )}

            <p className="text-xs text-muted-foreground mb-4">
              Scope: {scopeLabel}
            </p>

            <button
              onClick={handlePreview}
              disabled={!canProceed || loading}
              className="w-full px-4 py-2.5 rounded-xl bg-primary text-white font-medium text-sm hover:brightness-110 transition-all disabled:opacity-50"
            >
              {loading ? "Counting..." : "Preview Cleanup"}
            </button>
          </>
        )}

        {(step === "confirm" || step === "double-confirm") && (
          <div className="text-center">
            <div className="w-12 h-12 mx-auto rounded-full bg-amber-500/20 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <p className="text-sm mb-1">
              This will delete <span className="font-bold text-foreground">{count.toLocaleString()}</span> snapshot{count !== 1 ? "s" : ""} from {scopeLabel}.
            </p>
            {step === "double-confirm" && (
              <p className="text-xs text-destructive font-medium mb-3">This will delete ALL snapshot data. This action cannot be undone.</p>
            )}
            <p className="text-xs text-muted-foreground mb-5">This action cannot be undone.</p>
            <div className="flex gap-2">
              <button
                onClick={() => { setStep("select"); setError(null); }}
                className="flex-1 px-4 py-2.5 rounded-xl bg-muted text-sm font-medium hover:bg-muted/80 transition-colors"
              >
                Back
              </button>
              <button
                onClick={loading ? () => abortRef.current?.abort() : handleDelete}
                className={`flex-1 px-4 py-2.5 rounded-xl text-white text-sm font-medium hover:brightness-110 transition-all ${
                  loading ? "bg-muted-foreground" : "bg-destructive"
                }`}
              >
                {loading ? "Cancel" : step === "double-confirm" ? "Yes, Delete All" : "Delete"}
              </button>
            </div>
          </div>
        )}

        {step === "done" && (
          <div className="text-center">
            <div className="w-12 h-12 mx-auto rounded-full bg-emerald-500/20 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-sm mb-4">
              Successfully deleted <span className="font-bold">{result.toLocaleString()}</span> snapshot{result !== 1 ? "s" : ""}.
            </p>
            <button
              onClick={() => { onComplete(); onClose(); }}
              className="w-full px-4 py-2.5 rounded-xl bg-primary text-white text-sm font-medium hover:brightness-110 transition-all"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
