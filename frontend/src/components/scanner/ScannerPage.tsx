import { useState, useEffect } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient, type ScanRequest, type ScanStatus, type ScanResultItem, type CryptoInterval } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useModels } from "@/hooks/useModels";
import { useConnectivityCheck, type ConnStatus } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";

const PROVIDERS = ["openai", "anthropic", "google", "deepseek", "xai", "qwen", "glm", "openrouter", "azure", "ollama"] as const;
const CRYPTO_ANALYSTS = ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"] as const;
const CRYPTO_INTERVALS: { value: CryptoInterval; label: string }[] = [
  { value: "15", label: "15 min" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "D", label: "1 day" },
];

const STORAGE_KEY = "tradingagents_settings";
const SCANNER_KEY = "tradingagents_scanner";

function getToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function loadSavedSettings(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

interface ScannerSettings {
  analysisDate?: string;
  provider?: string;
  backendUrl?: string;
  deepModel?: string;
  quickModel?: string;
  interval?: CryptoInterval;
  analysts?: string[];
}

function loadScannerSettings(): ScannerSettings {
  try {
    return JSON.parse(localStorage.getItem(SCANNER_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function saveScannerSettings(s: ScannerSettings) {
  localStorage.setItem(SCANNER_KEY, JSON.stringify(s));
}

const DIRECTION_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  buy: { label: "BUY", color: "text-emerald-400", bg: "bg-emerald-500/10" },
  sell: { label: "SELL", color: "text-red-400", bg: "bg-red-500/10" },
  hold: { label: "HOLD", color: "text-amber-400", bg: "bg-amber-500/10" },
  unknown: { label: "—", color: "text-muted-foreground", bg: "bg-muted" },
};

function ScoreBar({ score }: { score: number }) {
  const abs = Math.min(Math.abs(score), 10);
  const pct = (abs / 10) * 100;
  const color = score > 0 ? "bg-emerald-500" : score < 0 ? "bg-red-500" : "bg-muted-foreground";
  return (
    <div className="flex items-center gap-2 w-24">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-6 text-right">{score > 0 ? "+" : ""}{score}</span>
    </div>
  );
}

function ConnBadge({ status, latency, error }: { status: ConnStatus; latency: number | null; error: string | null }) {
  if (status === "idle") return null;
  if (status === "checking") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground ml-auto">
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Checking...
      </span>
    );
  }
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 font-medium ml-auto">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        Connected{latency != null && ` (${latency}ms)`}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-destructive font-medium ml-auto">
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      {error || "Unreachable"}
    </span>
  );
}

const SCAN_ID_KEY = "tradingagents_active_scan";

function loadActiveScanId(): string | null {
  return sessionStorage.getItem(SCAN_ID_KEY);
}

function saveActiveScanId(id: string | null) {
  if (id) sessionStorage.setItem(SCAN_ID_KEY, id);
  else sessionStorage.removeItem(SCAN_ID_KEY);
}

export function ScannerPage() {
  const [saved] = useState(loadSavedSettings);
  const [scanner] = useState(loadScannerSettings);
  const [analysisDate, setAnalysisDate] = useState(scanner.analysisDate ?? getToday());
  const [provider, setProvider] = useState(scanner.provider ?? saved.provider ?? "anthropic");
  const [backendUrl, setBackendUrl] = useState(scanner.backendUrl ?? saved.backend_url ?? "http://localhost:4141");
  const [deepModel, setDeepModel] = useState(scanner.deepModel ?? saved.deep_think_llm ?? "");
  const [quickModel, setQuickModel] = useState(scanner.quickModel ?? saved.quick_think_llm ?? "");
  const [interval, setInterval] = useState<CryptoInterval>(scanner.interval ?? "D");
  const [analysts, setAnalysts] = useState<string[]>(scanner.analysts ?? [...CRYPTO_ANALYSTS]);
  const [activeScanId, _setActiveScanId] = useState<string | null>(loadActiveScanId);
  const [showLlm, setShowLlm] = useState(true);
  const [llmMaxConcurrent, setLlmMaxConcurrent] = useState<number>(0);

  useEffect(() => {
    saveScannerSettings({ analysisDate, provider, backendUrl, deepModel, quickModel, interval, analysts });
  }, [analysisDate, provider, backendUrl, deepModel, quickModel, interval, analysts]);

  const setActiveScanId = (id: string | null) => {
    _setActiveScanId(id);
    saveActiveScanId(id);
  };

  const conn = useConnectivityCheck(backendUrl);
  const { data: remoteModels } = useModels(backendUrl);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 60_000,
  });
  useEffect(() => {
    if (configQuery.data?.resolved?.llm_max_concurrent != null) {
      setLlmMaxConcurrent(Number(configQuery.data.resolved.llm_max_concurrent));
    }
  }, [configQuery.data]);
  const remoteIds = (remoteModels ?? []).map((m) => m.id);
  const catalogDeep = getModelOptions(provider, "deep");
  const catalogQuick = getModelOptions(provider, "quick");
  const deepOptions = remoteIds.length > 0
    ? remoteIds.map((id) => ({ label: id, value: id }))
    : catalogDeep;
  const quickOptions = remoteIds.length > 0
    ? remoteIds.map((id) => ({ label: id, value: id }))
    : catalogQuick;

  const startMutation = useMutation({
    mutationFn: (body: ScanRequest) => apiClient.startScan(body),
    onSuccess: (data) => setActiveScanId(data.scan_id),
  });

  const cancelMutation = useMutation({
    mutationFn: (scanId: string) => apiClient.cancelScan(scanId),
  });

  const saveLlmConcurrency = (value: number) => {
    setLlmMaxConcurrent(value);
    apiClient.updateConfig({ llm_max_concurrent: value });
  };

  const scanQuery = useQuery({
    queryKey: ["scan", activeScanId],
    queryFn: ({ signal }) => apiClient.getScan(activeScanId!, signal),
    enabled: !!activeScanId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 3000 : false;
    },
    retry: false,
  });

  useEffect(() => {
    if (scanQuery.isError && activeScanId) {
      setActiveScanId(null);
    }
  }, [scanQuery.isError, activeScanId]);

  const scan: ScanStatus | undefined = scanQuery.data;
  const isRunning = scan?.status === "running";
  const isDone = scan?.status === "completed" || scan?.status === "cancelled" || scan?.status === "failed";

  const handleStart = () => {
    const body: ScanRequest = {
      analysis_date: analysisDate,
      asset_type: "crypto",
      interval,
      provider: provider || undefined,
      deep_think_llm: deepModel || undefined,
      quick_think_llm: quickModel || undefined,
      backend_url: backendUrl || undefined,
      analysts,
      research_depth: 1,
    };
    startMutation.mutate(body);
  };

  const toggleAnalyst = (a: string) => {
    setAnalysts((prev) => prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]);
  };

  const buyResults = (scan?.results ?? []).filter((r) => r.direction === "buy").sort((a, b) => b.score - a.score);
  const sellResults = (scan?.results ?? []).filter((r) => r.direction === "sell").sort((a, b) => a.score - b.score);
  const holdResults = (scan?.results ?? []).filter((r) => r.direction === "hold" || r.direction === "unknown");

  return (
    <div className="space-y-6 max-w-5xl mx-auto py-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <svg className="w-6 h-6 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Market Scanner
          </h1>
          <p className="text-muted-foreground mt-1">
            Scan all available Bybit USDT perpetual futures in batches of 10 and find the best trading opportunities.
          </p>
        </div>
        {activeScanId && isDone && (
          <Button variant="outline" onClick={() => setActiveScanId(null)} className="shrink-0">
            <svg className="w-4 h-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Scan
          </Button>
        )}
      </div>

      {/* Config */}
      {!activeScanId && (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-4">
              <CardTitle className="text-base flex items-center gap-2">
                <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Scan Configuration
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                <div className="flex flex-col gap-2">
                  <Label className="font-medium">Analysis Date</Label>
                  <Input type="date" value={analysisDate} max={getToday()} onChange={(e) => setAnalysisDate(e.target.value)} />
                  <p className="text-xs text-muted-foreground">Historical date for analysis</p>
                </div>
                <div className="flex flex-col gap-2">
                  <Label className="font-medium">Kline Interval</Label>
                  <Select value={interval} onValueChange={(v) => setInterval(v as CryptoInterval)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {CRYPTO_INTERVALS.map((i) => (
                        <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">Candlestick interval for technicals</p>
                </div>
                <div className="flex flex-col gap-2">
                  <Label className="font-medium">LLM Provider</Label>
                  <Select value={provider} onValueChange={setProvider}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PROVIDERS.map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">AI provider for agent reasoning</p>
                </div>
              </div>

              {/* Analyst team */}
              <div className="flex flex-col gap-2">
                <Label className="font-medium">Analyst Team</Label>
                <div className="flex flex-wrap gap-2">
                  {CRYPTO_ANALYSTS.map((a) => {
                    const active = analysts.includes(a);
                    const label = a.replace("crypto_", "");
                    return (
                      <button
                        key={a}
                        type="button"
                        onClick={() => toggleAnalyst(a)}
                        className={cn(
                          "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                          active
                            ? "bg-primary text-primary-foreground border-primary shadow-sm"
                            : "bg-muted/50 text-muted-foreground border-border hover:border-primary/50 hover:text-foreground",
                        )}
                      >
                        <span className={cn("w-3.5 h-3.5 rounded border-2 flex items-center justify-center transition-colors", active ? "border-primary-foreground bg-primary-foreground/20" : "border-current")}>
                          {active && (
                            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={4}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </span>
                        {label}
                      </button>
                    );
                  })}
                </div>
                <p className="text-xs text-muted-foreground">
                  Select which analyst agents to include ({analysts.length}/{CRYPTO_ANALYSTS.length})
                </p>
              </div>
            </CardContent>
          </Card>

          {/* LLM & Proxy section — collapsible */}
          <Card>
            <CardHeader className="pb-0">
              <button
                type="button"
                onClick={() => setShowLlm(!showLlm)}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
              >
                <svg className={cn("w-4 h-4 transition-transform duration-200", showLlm && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                LLM &amp; Proxy Settings
                <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
              </button>
            </CardHeader>
            {showLlm && (
              <CardContent className="pt-4 space-y-4">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <Label className="font-medium">Backend URL / Proxy Endpoint</Label>
                    <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
                  </div>
                  <Input
                    value={backendUrl}
                    onChange={(e) => setBackendUrl(e.target.value)}
                    placeholder="http://localhost:4141"
                  />
                  <p className="text-xs text-muted-foreground">
                    Custom API endpoint. Models are fetched from <code className="text-[11px] px-1 py-0.5 rounded bg-muted">/v1/models</code> automatically.
                    {remoteIds.length > 0 && (
                      <span className="ml-1 text-primary">{remoteIds.length} models loaded</span>
                    )}
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium">Deep Think Model</Label>
                    <Select value={deepModel} onValueChange={setDeepModel}>
                      <SelectTrigger><SelectValue placeholder="Select model..." /></SelectTrigger>
                      <SelectContent>
                        {deepOptions.map((m) => (
                          <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">Model for complex reasoning tasks</p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium">Quick Think Model</Label>
                    <Select value={quickModel} onValueChange={setQuickModel}>
                      <SelectTrigger><SelectValue placeholder="Select model..." /></SelectTrigger>
                      <SelectContent>
                        {quickOptions.map((m) => (
                          <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">Model for fast, lightweight tasks</p>
                  </div>
                </div>

                {/* LLM Concurrency Limit */}
                <div className="flex flex-col gap-2 pt-2">
                  <Label className="font-medium">LLM Concurrency Limit</Label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={llmMaxConcurrent}
                    onChange={(e) => saveLlmConcurrency(Number(e.target.value))}
                    className="w-32"
                  />
                  <p className="text-xs text-muted-foreground">
                    Max concurrent LLM API calls. Set to 0 for unlimited (pay-as-you-go plans).
                  </p>
                </div>
              </CardContent>
            )}
          </Card>

          {/* Start button */}
          <Button
            onClick={handleStart}
            disabled={startMutation.isPending || analysts.length === 0}
            className="w-full h-12 text-base font-semibold"
            size="lg"
          >
            {startMutation.isPending ? (
              <>
                <svg className="w-5 h-5 mr-2 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Starting Scan...
              </>
            ) : (
              <>
                <svg className="w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                Start Full Market Scan
              </>
            )}
          </Button>
          {startMutation.isError && (
            <p className="text-xs text-destructive text-center">
              Failed to start scan: {(startMutation.error as Error).message}
            </p>
          )}
        </div>
      )}

      {/* Progress */}
      {scan && (
        <Card>
          <CardContent className="py-5 space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isRunning && (
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <svg className="w-4 h-4 text-primary animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  </div>
                )}
                {scan.status === "completed" && (
                  <div className="w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center">
                    <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                )}
                <div>
                  <h3 className="font-semibold">
                    {isRunning ? "Scanning Market..." : scan.status === "completed" ? "Scan Complete" : scan.status === "cancelled" ? "Scan Cancelled" : "Scan Failed"}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Batch {scan.current_batch} of {scan.total_batches}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {isRunning && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => cancelMutation.mutate(scan.scan_id)}
                    disabled={cancelMutation.isPending}
                    className="text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>

            {/* Progress bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{scan.completed + scan.failed} / {scan.total} symbols</span>
                <span>{scan.total > 0 ? Math.round(((scan.completed + scan.failed) / scan.total) * 100) : 0}%</span>
              </div>
              <div className="h-2.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${scan.total > 0 ? ((scan.completed + scan.failed) / scan.total) * 100 : 0}%` }}
                />
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 p-3 text-center">
                <p className="text-2xl font-bold text-emerald-500">{buyResults.length}</p>
                <p className="text-xs text-muted-foreground">Buy Signals</p>
              </div>
              <div className="rounded-lg bg-red-500/5 border border-red-500/10 p-3 text-center">
                <p className="text-2xl font-bold text-red-500">{sellResults.length}</p>
                <p className="text-xs text-muted-foreground">Sell Signals</p>
              </div>
              <div className="rounded-lg bg-amber-500/5 border border-amber-500/10 p-3 text-center">
                <p className="text-2xl font-bold text-amber-500">{holdResults.length}</p>
                <p className="text-xs text-muted-foreground">Hold / Neutral</p>
              </div>
            </div>

            {/* Current batch tickers */}
            {isRunning && scan.current_tickers.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground font-medium">Currently analyzing:</p>
                <div className="flex flex-wrap gap-1.5">
                  {scan.current_tickers.map((t) => (
                    <Badge key={t} variant="outline" className="text-xs font-mono gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {scan && scan.results.length > 0 && (
        <>
          {/* Buy signals */}
          {buyResults.length > 0 && (
            <Card className="border-emerald-500/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Buy Signals ({buyResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={buyResults} />
              </CardContent>
            </Card>
          )}

          {/* Sell signals */}
          {sellResults.length > 0 && (
            <Card className="border-red-500/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                  Sell Signals ({sellResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={sellResults} />
              </CardContent>
            </Card>
          )}

          {/* Hold / Unknown */}
          {holdResults.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber-500" />
                  Hold / Neutral ({holdResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={holdResults} />
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function ResultsTable({ results }: { results: ScanResultItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 text-xs text-muted-foreground">
            <th className="text-left px-4 py-2.5 font-medium">#</th>
            <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
            <th className="text-left px-4 py-2.5 font-medium">Signal</th>
            <th className="text-left px-4 py-2.5 font-medium">Confidence</th>
            <th className="text-left px-4 py-2.5 font-medium">Strength</th>
            <th className="text-left px-4 py-2.5 font-medium">Status</th>
            <th className="text-right px-4 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            return (
              <tr key={r.ticker} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="px-4 py-3 font-mono font-semibold">{r.ticker}</td>
                <td className="px-4 py-3">
                  <span className={cn("px-2 py-0.5 rounded text-xs font-bold", dir.bg, dir.color)}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs capitalize">{r.confidence}</td>
                <td className="px-4 py-3"><ScoreBar score={r.score} /></td>
                <td className="px-4 py-3">
                  <Badge variant={r.status === "completed" ? "secondary" : "destructive"} className="text-xs">
                    {r.status}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  {r.run_id && (
                    <Link
                      to="/analysis/$runId"
                      params={{ runId: r.run_id }}
                      className="text-xs text-primary hover:underline"
                    >
                      View
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
