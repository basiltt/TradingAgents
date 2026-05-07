import { useState, useEffect, useRef } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient, type ScanRequest, type ScanStatus, type ScanResultItem, type CryptoInterval } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModelSelect } from "@/components/ui/model-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useModels } from "@/hooks/useModels";
import { useConnectivityCheck, type ConnStatus } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";
import { MobileCollapse } from "@/components/analysis/MobileCollapse";
import { AgentModelOverrides, loadOverrides, filterOverridesForAssetType } from "@/components/analysis/AgentModelOverrides";

const PROVIDERS_FALLBACK = ["openai", "anthropic", "google", "deepseek", "nvidia", "xai", "qwen", "glm", "openrouter", "azure", "ollama"];
const CRYPTO_ANALYSTS = ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"] as const;
const CRYPTO_INTERVALS: { value: CryptoInterval; label: string }[] = [
  { value: "15", label: "15 min" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "D", label: "1 day" },
];

const LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "Spanish", "French", "German", "Portuguese", "Russian", "Arabic", "Hindi"] as const;

const STORAGE_KEY = "tradingagents_settings";
const SCANNER_KEY = "tradingagents_scanner";
const ENDPOINTS_KEY = "tradingagents_endpoints";

interface EndpointProfile {
  url: string;
  apiKey?: string;
  deepModel?: string;
  quickModel?: string;
}

function loadEndpoints(): EndpointProfile[] {
  try {
    return JSON.parse(localStorage.getItem(ENDPOINTS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveEndpoint(ep: EndpointProfile) {
  const list = loadEndpoints();
  const idx = list.findIndex((e) => e.url === ep.url);
  if (idx >= 0) list[idx] = ep;
  else list.push(ep);
  localStorage.setItem(ENDPOINTS_KEY, JSON.stringify(list));
}

function removeEndpoint(url: string) {
  const list = loadEndpoints().filter((e) => e.url !== url);
  localStorage.setItem(ENDPOINTS_KEY, JSON.stringify(list));
}

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
  llmApiKey?: string;
  backendUrl?: string;
  deepModel?: string;
  quickModel?: string;
  interval?: CryptoInterval;
  analysts?: string[];
  researchDepth?: number;
  outputLanguage?: string;
  maxDebateRounds?: number;
  maxRiskRounds?: number;
  maxRecurLimit?: number;
  checkpointEnabled?: boolean;
  maxParallel?: number;
  workflowMode?: "quick_trade" | "deep_analysis";
  taPrefilterEnabled?: boolean;
  taPrefilterThreshold?: number;
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

function ConnBadge({ status, latency, error, label = "Connected" }: { status: ConnStatus; latency: number | null; error: string | null; label?: string }) {
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
        {label}{latency != null && ` (${latency}ms)`}
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

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function ScanDurationBadge({ startedAt, completedAt, isRunning }: { startedAt?: string; completedAt?: string | null; isRunning: boolean }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!isRunning || !startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isRunning, startedAt]);

  if (!startedAt) return null;

  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : now;
  const elapsed = Math.max(0, end - start);

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground font-mono tabular-nums">
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      {formatDuration(elapsed)}
    </span>
  );
}

const SCAN_ID_KEY = "tradingagents_active_scan";

function loadActiveScanId(): string | null {
  return localStorage.getItem(SCAN_ID_KEY);
}

function saveActiveScanId(id: string | null) {
  if (id) localStorage.setItem(SCAN_ID_KEY, id);
  else localStorage.removeItem(SCAN_ID_KEY);
}

export function ScannerPage() {
  const [saved] = useState(loadSavedSettings);
  const [scanner] = useState(loadScannerSettings);
  const [analysisDate, setAnalysisDate] = useState(scanner.analysisDate ?? getToday());
  const [provider, setProvider] = useState(scanner.provider ?? saved.provider ?? "anthropic");
  const [llmApiKey, setLlmApiKey] = useState(scanner.llmApiKey ?? saved.llm_api_key ?? "");
  const [backendUrl, setBackendUrl] = useState(scanner.backendUrl ?? saved.backend_url ?? "http://localhost:4141");
  const [deepModel, setDeepModel] = useState(scanner.deepModel ?? saved.deep_think_llm ?? "");
  const [quickModel, setQuickModel] = useState(scanner.quickModel ?? saved.quick_think_llm ?? "");
  const [interval, setInterval] = useState<CryptoInterval>(scanner.interval ?? "D");
  const [analysts, setAnalysts] = useState<string[]>(scanner.analysts ?? [...CRYPTO_ANALYSTS]);
  const [researchDepth, setResearchDepth] = useState(scanner.researchDepth ?? 3);
  const [outputLanguage, setOutputLanguage] = useState(scanner.outputLanguage ?? "English");
  const [maxDebateRounds, setMaxDebateRounds] = useState(scanner.maxDebateRounds ?? 1);
  const [maxRiskRounds, setMaxRiskRounds] = useState(scanner.maxRiskRounds ?? 1);
  const [maxRecurLimit, setMaxRecurLimit] = useState(scanner.maxRecurLimit ?? 100);
  const [checkpointEnabled, setCheckpointEnabled] = useState(scanner.checkpointEnabled ?? false);
  const [maxParallel, setMaxParallel] = useState(scanner.maxParallel ?? 10);
  const [workflowMode, setWorkflowMode] = useState<"quick_trade" | "deep_analysis">(scanner.workflowMode ?? "deep_analysis");
  const [taPrefilterEnabled, setTaPrefilterEnabled] = useState(scanner.taPrefilterEnabled ?? false);
  const [taPrefilterThreshold, setTaPrefilterThreshold] = useState(scanner.taPrefilterThreshold ?? 40);
  const [activeScanId, _setActiveScanId] = useState<string | null>(loadActiveScanId);
  const [showLlm, setShowLlm] = useState(true);
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [llmMaxConcurrent, setLlmMaxConcurrent] = useState<number>(0);
  const [endpoints, setEndpoints] = useState(loadEndpoints);
  const [showEndpoints, setShowEndpoints] = useState(false);
  const [agentModelOverrides, setAgentModelOverrides] = useState<Record<string, string>>(loadOverrides);
  const endpointsRef = useRef<HTMLDivElement>(null);

  const { data: providersData } = useQuery({
    queryKey: ["providers"],
    queryFn: ({ signal }) => apiClient.getProviders(signal),
    staleTime: 300_000,
  });
  const PROVIDERS = providersData?.providers ?? PROVIDERS_FALLBACK;

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (endpointsRef.current && !endpointsRef.current.contains(e.target as Node)) setShowEndpoints(false);
    }
    if (showEndpoints) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showEndpoints]);

  useEffect(() => {
    saveScannerSettings({ analysisDate, provider, llmApiKey, backendUrl, deepModel, quickModel, interval, analysts, researchDepth, outputLanguage, maxDebateRounds, maxRiskRounds, maxRecurLimit, checkpointEnabled, maxParallel, workflowMode, taPrefilterEnabled, taPrefilterThreshold });
    if (backendUrl.trim()) {
      saveEndpoint({ url: backendUrl.trim(), apiKey: llmApiKey, deepModel, quickModel });
      setEndpoints(loadEndpoints());
    }
  }, [analysisDate, provider, llmApiKey, backendUrl, deepModel, quickModel, interval, analysts, researchDepth, outputLanguage, maxDebateRounds, maxRiskRounds, maxRecurLimit, checkpointEnabled, maxParallel, workflowMode, taPrefilterEnabled, taPrefilterThreshold]);

  function selectEndpoint(ep: EndpointProfile) {
    setBackendUrl(ep.url);
    if (ep.apiKey != null) setLlmApiKey(ep.apiKey);
    if (ep.deepModel) setDeepModel(ep.deepModel);
    if (ep.quickModel) setQuickModel(ep.quickModel);
    setShowEndpoints(false);
  }

  function deleteEndpoint(url: string) {
    removeEndpoint(url);
    setEndpoints(loadEndpoints());
  }

  const setActiveScanId = (id: string | null) => {
    _setActiveScanId(id);
    saveActiveScanId(id);
  };

  // On mount, if no scan ID is stored locally, discover any running scan from the
  // backend so other devices on the network automatically attach to the active scan.
  useEffect(() => {
    if (activeScanId) return;
    apiClient.listScans().then((data) => {
      const running = data.scans.find((s) => s.status === "running");
      if (running) setActiveScanId(running.scan_id);
    }).catch(() => { /* network unavailable — ignore */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const conn = useConnectivityCheck(backendUrl, llmApiKey || undefined, 800, provider);
  const { data: remoteModels } = useModels(backendUrl, llmApiKey || undefined);

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

  const [lostScan, setLostScan] = useState(false);
  useEffect(() => {
    if (scanQuery.isError && activeScanId) {
      setActiveScanId(null);
      setLostScan(true);
    }
  }, [scanQuery.isError, activeScanId]);

  const scan: ScanStatus | undefined = scanQuery.data;
  const isRunning = scan?.status === "running";
  const isDone = scan?.status === "completed" || scan?.status === "cancelled" || scan?.status === "failed";

  useEffect(() => {
    if (scan?.status === "cancelled" && scan.results.length === 0) {
      setActiveScanId(null);
    }
  }, [scan?.status, scan?.results.length]);

  const handleStart = () => {
    const body: ScanRequest = {
      analysis_date: analysisDate,
      asset_type: "crypto",
      interval,
      provider: provider || undefined,
      llm_api_key: llmApiKey || undefined,
      deep_think_llm: deepModel || undefined,
      quick_think_llm: quickModel || undefined,
      backend_url: backendUrl || undefined,
      analysts,
      research_depth: researchDepth,
      output_language: outputLanguage !== "English" ? outputLanguage : undefined,
      max_debate_rounds: maxDebateRounds,
      max_risk_discuss_rounds: maxRiskRounds,
      max_recur_limit: maxRecurLimit !== 100 ? maxRecurLimit : undefined,
      checkpoint_enabled: checkpointEnabled || undefined,
      max_parallel: maxParallel !== 10 ? maxParallel : undefined,
      workflow_mode: workflowMode !== "deep_analysis" ? workflowMode : undefined,
      ta_prefilter_enabled: taPrefilterEnabled,
      ta_prefilter_threshold: taPrefilterEnabled ? taPrefilterThreshold : undefined,
      agent_model_overrides: (() => {
        const filtered = filterOverridesForAssetType(agentModelOverrides, "crypto");
        return Object.keys(filtered).length > 0 ? filtered : undefined;
      })(),
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
            Scan all available Bybit USDT perpetual futures and find the best trading opportunities.
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
          {lostScan && (
            <Card className="border-amber-500/30 bg-amber-500/5">
              <CardContent className="flex items-center gap-3 py-4">
                <svg className="w-5 h-5 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <div>
                  <p className="font-medium text-amber-500 text-sm">Previous scan was lost</p>
                  <p className="text-xs text-muted-foreground">The backend restarted (hot reload or restart) while a scan was running. Completed results are saved in History. Start a new scan to continue.</p>
                </div>
                <button onClick={() => setLostScan(false)} className="ml-auto text-muted-foreground hover:text-foreground p-1">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </CardContent>
            </Card>
          )}
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
                  <Select value={provider} onValueChange={(value) => { if (value !== null) setProvider(value); }}>
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

              {/* Workflow Mode Toggle */}
              <div className="flex flex-col gap-2">
                <Label className="font-medium">Workflow Mode</Label>
                <div className="flex rounded-lg border overflow-hidden" role="radiogroup" aria-label="Workflow mode">
                  {([
                    { value: "quick_trade" as const, label: "Quick Trade" },
                    { value: "deep_analysis" as const, label: "Deep Analysis" },
                  ]).map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      role="radio"
                      aria-checked={workflowMode === opt.value}
                      className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
                        workflowMode === opt.value
                          ? "bg-primary text-primary-foreground"
                          : "bg-background hover:bg-muted"
                      }`}
                      onClick={() => setWorkflowMode(opt.value)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {workflowMode === "quick_trade"
                    ? "Analysts → Research Debate → Trade Card"
                    : "Full pipeline with risk debate, compliance & portfolio management"}
                </p>
              </div>

              {/* Smart Pre-Screen */}
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="scanner_ta_prefilter"
                    checked={taPrefilterEnabled}
                    onChange={(e) => setTaPrefilterEnabled(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <Label htmlFor="scanner_ta_prefilter" className="font-medium cursor-pointer">
                    Smart Pre-Screen
                  </Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  Run TA analysis first per symbol. Skips LLM calls for assets with no clear signal — saves costs on bulk scans.
                </p>
                {taPrefilterEnabled && (
                  <div className="flex items-center gap-2 mt-1">
                    <Label htmlFor="scanner_ta_threshold" className="text-xs whitespace-nowrap">Threshold</Label>
                    <Input
                      id="scanner_ta_threshold"
                      type="number"
                      min={0}
                      max={100}
                      value={taPrefilterThreshold}
                      onChange={(e) => setTaPrefilterThreshold(Number(e.target.value))}
                      className="w-20 h-7 text-xs"
                    />
                    <span className="text-xs text-muted-foreground">/ 100</span>
                  </div>
                )}
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

          {/* Workflow Settings — collapsible */}
          <Card>
            <CardHeader className="pb-0">
              <button
                type="button"
                onClick={() => setShowWorkflow(!showWorkflow)}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
              >
                <svg className={cn("w-4 h-4 transition-transform duration-200", showWorkflow && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                Workflow Settings
              </button>
            </CardHeader>
            {showWorkflow && (
              <CardContent className="pt-4 space-y-4">
                <div className="flex flex-col gap-2">
                  <Label className="font-medium">Research Depth</Label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={1}
                      max={5}
                      step={1}
                      value={researchDepth}
                      onChange={(e) => setResearchDepth(Number(e.target.value))}
                      className="flex-1 accent-primary"
                    />
                    <span className="text-sm font-mono w-4 text-right">{researchDepth}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">1 = Quick scan, 5 = Deep analysis</p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-medium">Output Language</Label>
                  <Select value={outputLanguage} onValueChange={(value) => { if (value !== null) setOutputLanguage(value); }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {LANGUAGES.map((l) => (
                        <SelectItem key={l} value={l}>{l}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">Language for the final report (agent debate stays in English)</p>
                </div>

                <div className={`grid ${workflowMode === "quick_trade" ? "grid-cols-1" : "grid-cols-2"} gap-4`}>
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium text-sm">Max Debate Rounds</Label>
                    <Input type="number" min={1} max={10} value={maxDebateRounds} onChange={(e) => setMaxDebateRounds(Number(e.target.value))} />
                    <p className="text-xs text-muted-foreground">Bull vs Bear debate iterations</p>
                  </div>
                  {workflowMode !== "quick_trade" && (
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium text-sm">Max Risk Rounds</Label>
                    <Input type="number" min={1} max={10} value={maxRiskRounds} onChange={(e) => setMaxRiskRounds(Number(e.target.value))} />
                    <p className="text-xs text-muted-foreground">Risk team discussion iterations</p>
                  </div>
                  )}
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-medium text-sm">Max Recursion Limit</Label>
                  <Input type="number" min={1} max={500} value={maxRecurLimit} onChange={(e) => setMaxRecurLimit(Number(e.target.value))} />
                  <p className="text-xs text-muted-foreground">Upper bound on LangGraph recursion steps</p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-medium text-sm">Max Parallel Analyses</Label>
                  <Input type="number" min={1} max={25} value={maxParallel} onChange={(e) => setMaxParallel(Math.min(25, Math.max(1, Number(e.target.value))))} />
                  <p className="text-xs text-muted-foreground">How many symbols to analyse concurrently (1–25)</p>
                </div>

                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checkpointEnabled}
                    onChange={(e) => setCheckpointEnabled(e.target.checked)}
                    className="mt-1 w-4 h-4 rounded border-border accent-primary"
                  />
                  <div>
                    <span className="font-medium text-sm">Enable Checkpoints</span>
                    <p className="text-xs text-muted-foreground">Save state after each step so crashed runs can resume</p>
                  </div>
                </label>
              </CardContent>
            )}
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
              </button>
            </CardHeader>
            {showLlm && (
              <CardContent className="pt-4 space-y-4">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <Label className="font-medium">Backend URL / Proxy Endpoint</Label>
                    <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
                  </div>
                  <div className="relative" ref={endpointsRef}>
                    <Input
                      value={backendUrl}
                      onChange={(e) => setBackendUrl(e.target.value)}
                      onFocus={() => endpoints.length > 1 && setShowEndpoints(true)}
                      placeholder="Enter your LLM provider override URL"
                      className="pr-9 placeholder:text-muted-foreground/40"
                    />
                    {endpoints.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setShowEndpoints(!showEndpoints)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-muted transition-colors"
                      >
                        <svg className={cn("w-4 h-4 text-muted-foreground transition-transform", showEndpoints && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                    )}
                    {showEndpoints && endpoints.length > 1 && (
                      <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-popover shadow-lg overflow-hidden">
                        {endpoints.map((ep) => (
                          <div
                            key={ep.url}
                            className={cn(
                              "flex items-center justify-between px-3 py-2 text-sm cursor-pointer hover:bg-muted transition-colors",
                              ep.url === backendUrl && "bg-primary/10 text-primary",
                            )}
                          >
                            <button
                              type="button"
                              className="flex-1 text-left truncate font-mono text-xs"
                              onClick={() => selectEndpoint(ep)}
                            >
                              {ep.url}
                              {ep.deepModel && <span className="ml-2 text-muted-foreground">({ep.deepModel})</span>}
                            </button>
                            {ep.url !== backendUrl && (
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); deleteEndpoint(ep.url); }}
                                className="ml-2 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                                title="Remove endpoint"
                              >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Custom API endpoint. Models are fetched from <code className="text-[11px] px-1 py-0.5 rounded bg-muted">/v1/models</code> automatically.
                    {remoteIds.length > 0 && (
                      <span className="ml-1 text-primary">{remoteIds.length} models loaded</span>
                    )}
                  </p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <Label className="font-medium">API Key</Label>
                    {llmApiKey.trim() && <ConnBadge status={conn.status} latency={null} error={conn.errorMsg} label="Authenticated" />}
                  </div>
                  <Input
                    type="password"
                    value={llmApiKey}
                    onChange={(e) => setLlmApiKey(e.target.value)}
                    placeholder="Provider API key (overrides env var)"
                  />
                  <p className="text-xs text-muted-foreground">
                    Optional. Overrides the environment variable for the selected provider.
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium">Deep Think Model</Label>
                    <ModelSelect
                      options={deepOptions}
                      value={deepModel}
                      onChange={(value) => setDeepModel(value ?? "")}
                      placeholder="Select model..."
                    />
                    <p className="text-xs text-muted-foreground">Model for complex reasoning tasks</p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium">Quick Think Model</Label>
                    <ModelSelect
                      options={quickOptions}
                      value={quickModel}
                      onChange={(value) => setQuickModel(value ?? "")}
                      placeholder="Select model..."
                    />
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

          {/* Agent Model Overrides */}
          <Card className="shadow-sm">
            <CardContent className="pt-5">
              <AgentModelOverrides
                assetType="crypto"
                modelOptions={deepOptions}
                overrides={agentModelOverrides}
                onChange={setAgentModelOverrides}
              />
            </CardContent>
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
      {scan && scan.status !== "cancelled" && (
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
                  <h3 className="font-semibold flex items-center gap-3">
                    {isRunning ? "Scanning Market..." : scan.status === "completed" ? "Scan Complete" : scan.status === "cancelled" ? "Scan Cancelled" : "Scan Failed"}
                    <ScanDurationBadge startedAt={scan.started_at} completedAt={scan.completed_at} isRunning={isRunning} />
                  </h3>

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
            <>
              {/* Mobile: collapsible */}
              <MobileCollapse
                storageKey="scanner:collapse:buy"
                defaultOpen
                className="md:hidden"
                title={
                  <span className="text-sm font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                    <span className="text-emerald-500">Buy Signals</span>
                    <span className="text-xs text-muted-foreground font-normal">({buyResults.length})</span>
                  </span>
                }
              >
                <ResultsTable results={buyResults} />
              </MobileCollapse>
              {/* Desktop: collapsible card */}
              <CollapsibleResultCard
                className="hidden md:block border-emerald-500/20"
                storageKey="scanner:collapse:buy:desktop"
                defaultOpen
                color="emerald"
                title={`Buy Signals (${buyResults.length})`}
              >
                <ResultsTable results={buyResults} />
              </CollapsibleResultCard>
            </>
          )}

          {/* Sell signals */}
          {sellResults.length > 0 && (
            <>
              <MobileCollapse
                storageKey="scanner:collapse:sell"
                defaultOpen
                className="md:hidden"
                title={
                  <span className="text-sm font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
                    <span className="text-red-500">Sell Signals</span>
                    <span className="text-xs text-muted-foreground font-normal">({sellResults.length})</span>
                  </span>
                }
              >
                <ResultsTable results={sellResults} />
              </MobileCollapse>
              <CollapsibleResultCard
                className="hidden md:block border-red-500/20"
                storageKey="scanner:collapse:sell:desktop"
                defaultOpen
                color="red"
                title={`Sell Signals (${sellResults.length})`}
              >
                <ResultsTable results={sellResults} />
              </CollapsibleResultCard>
            </>
          )}

          {/* Hold / Unknown */}
          {holdResults.length > 0 && (
            <>
              <MobileCollapse
                storageKey="scanner:collapse:hold"
                defaultOpen={false}
                className="md:hidden"
                title={
                  <span className="text-sm font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
                    <span className="text-amber-500">Hold / Neutral</span>
                    <span className="text-xs text-muted-foreground font-normal">({holdResults.length})</span>
                  </span>
                }
              >
                <ResultsTable results={holdResults} />
              </MobileCollapse>
              <CollapsibleResultCard
                className="hidden md:block"
                storageKey="scanner:collapse:hold:desktop"
                defaultOpen={false}
                color="amber"
                title={`Hold / Neutral (${holdResults.length})`}
              >
                <ResultsTable results={holdResults} />
              </CollapsibleResultCard>
            </>
          )}
        </>
      )}
    </div>
  );
}

const COLOR_MAP: Record<string, string> = {
  emerald: "bg-emerald-500",
  red: "bg-red-500",
  amber: "bg-amber-500",
};

function CollapsibleResultCard({
  className,
  storageKey,
  defaultOpen,
  color,
  title,
  children,
}: {
  className?: string;
  storageKey: string;
  defaultOpen: boolean;
  color: string;
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(storageKey);
      return v !== null ? v === "true" : defaultOpen;
    } catch {
      return defaultOpen;
    }
  });

  function toggle() {
    setOpen((prev) => {
      localStorage.setItem(storageKey, String(!prev));
      return !prev;
    });
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <button type="button" onClick={toggle} className="flex items-center gap-2 w-full text-left">
          <svg className={cn("w-4 h-4 transition-transform duration-200 text-muted-foreground", open && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <CardTitle className="text-base flex items-center gap-2">
            <span className={cn("w-2 h-2 rounded-full", COLOR_MAP[color] ?? "bg-muted-foreground")} />
            {title}
          </CardTitle>
        </button>
      </CardHeader>
      {open && (
        <CardContent className="p-0">
          {children}
        </CardContent>
      )}
    </Card>
  );
}

function copyToClipboard(text: string): Promise<void> {
  // Modern async clipboard API (HTTPS / localhost)
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // iOS Safari + legacy fallback
  return new Promise((resolve, reject) => {
    const el = document.createElement("textarea");
    el.value = text;
    el.style.cssText = "position:fixed;top:0;left:0;opacity:0;font-size:16px;";
    document.body.appendChild(el);
    el.focus();
    // iOS requires setSelectionRange after focus
    el.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    ok ? resolve() : reject(new Error("execCommand failed"));
  });
}

function ResultsTable({ results }: { results: ScanResultItem[] }) {
  const [copiedTicker, setCopiedTicker] = useState<string | null>(null);

  function handleCopy(ticker: string) {
    copyToClipboard(ticker).then(() => {
      setCopiedTicker(ticker);
      setTimeout(() => setCopiedTicker(null), 1500);
    });
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 text-xs text-muted-foreground">
            <th className="text-left px-4 py-2.5 font-medium">#</th>
            <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Signal</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Confidence</th>
            <th className="text-left px-4 py-2.5 font-medium">Strength</th>
            <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">Status</th>
            <th className="text-right px-4 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            const copied = copiedTicker === r.ticker;
            return (
              <tr key={r.ticker} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => handleCopy(r.ticker)}
                    title="Tap to copy"
                    className={cn(
                      "font-mono font-semibold transition-all duration-150 rounded px-1 -mx-1 active:scale-95",
                      copied
                        ? "text-emerald-400 bg-emerald-500/10"
                        : "hover:text-primary hover:bg-primary/10",
                    )}
                  >
                    {copied ? (
                      <span className="flex items-center gap-1">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {r.ticker}
                      </span>
                    ) : r.ticker}
                  </button>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <span className={cn("px-2 py-0.5 rounded text-xs font-bold", dir.bg, dir.color)}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs capitalize hidden md:table-cell">{r.confidence}</td>
                <td className="px-4 py-3"><ScoreBar score={r.score} /></td>
                <td className="px-4 py-3 hidden md:table-cell">
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
