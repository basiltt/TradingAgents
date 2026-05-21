import { useState, useEffect, useRef, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, accountsApi, type AutoTradeSummary, type ScanRequest, type ScanStatus, type ScanResultItem, type CryptoInterval } from "@/api/client";
import { ModelSelect } from "@/components/ui/model-select";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { formatDuration } from "@/lib/format";
import { useScanFilters, ScanResultFiltersBar } from "@/components/scanner/ScanResultFilters";
import { PlaceTradeDialog } from "@/components/scanner/PlaceTradeDialog";
import { useModels } from "@/hooks/useModels";
import { useConnectivityCheck } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";
import { ConnBadge } from "@/components/ui/conn-badge";
import { loadEndpoints, saveEndpoint, removeEndpoint, type EndpointProfile } from "@/lib/endpoints";
import { PageHeader } from "@/components/layout/PageHeader";
import { MobileCollapse } from "@/components/analysis/MobileCollapse";
import { AgentModelOverrides, loadOverrides, filterOverridesForAssetType } from "@/components/analysis/AgentModelOverrides";
import { DIRECTION_CONFIG } from "@/components/scanner/constants";
import { AutoTradeSection } from "@/components/scanner/AutoTradeSection";

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
const SCANNER_PANEL_CLASS = "neu-surface-base neu-surface-raised overflow-hidden rounded-[var(--neu-radius-lg)]";
const SCANNER_SECTION_CLASS = "rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_8%,var(--neu-surface-muted))] p-4";
const SCANNER_LABEL_CLASS = "text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]";
const SCANNER_HINT_CLASS = "text-[11px] leading-5 text-[var(--neu-text-muted)]";
const SCANNER_SEGMENT_CLASS = "neu-surface-base neu-surface-inset flex min-h-12 items-center gap-1.5 rounded-[var(--neu-radius-md)] p-1.5";
const SCANNER_SEGMENT_BUTTON_CLASS = "neu-focus-ring flex-1 rounded-[calc(var(--neu-radius-md)-8px)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] transition-all";
const TONE_PILL_STYLES = {
  accent: "text-[var(--neu-accent)] border-[color:color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))]",
  success: "text-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-raised))]",
  warning: "text-[var(--neu-warning)] border-[color:color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-raised))]",
  danger: "text-[var(--neu-danger)] border-[color:color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-raised))]",
  neutral: "text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))]",
} as const;

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

function TonePill({
  tone = "neutral",
  className,
  children,
}: {
  tone?: keyof typeof TONE_PILL_STYLES;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-h-7 items-center rounded-[var(--neu-radius-pill)] border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        TONE_PILL_STYLES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

function ScannerPanelHeader({
  icon,
  title,
  description,
  tone = "accent",
}: {
  icon: ReactNode;
  title: string;
  description: string;
  tone?: keyof typeof TONE_PILL_STYLES;
}) {
  const toneColor = {
    accent: "text-[var(--neu-accent)]",
    success: "text-[var(--neu-success)]",
    warning: "text-[var(--neu-warning)]",
    danger: "text-[var(--neu-danger)]",
    neutral: "text-[var(--neu-text-muted)]",
  }[tone];

  return (
    <div className="flex items-center gap-3">
      <span className={cn("neu-surface-base neu-surface-raised flex size-10 items-center justify-center rounded-[var(--neu-radius-md)]", toneColor)}>
        {icon}
      </span>
      <div>
        <h4 className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">{title}</h4>
        <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">{description}</p>
      </div>
    </div>
  );
}

function ScannerMetricCard({
  tone,
  value,
  label,
}: {
  tone: keyof typeof TONE_PILL_STYLES;
  value: ReactNode;
  label: string;
}) {
  const toneText = {
    accent: "text-[var(--neu-accent)]",
    success: "text-[var(--neu-success)]",
    warning: "text-[var(--neu-warning)]",
    danger: "text-[var(--neu-danger)]",
    neutral: "text-[var(--neu-text-strong)]",
  }[tone];

  return (
    <div className={cn(SCANNER_SECTION_CLASS, "text-center")}>
      <p className={cn("text-2xl font-semibold leading-none tracking-[-0.04em]", toneText)}>{value}</p>
      <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">{label}</p>
    </div>
  );
}

function ScannerMetaItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_8%,var(--neu-surface-raised))] px-3.5 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">{label}</div>
      <div className="mt-1 text-sm font-semibold text-[var(--neu-text-strong)]">{value}</div>
    </div>
  );
}


function ScoreBar({ score }: { score: number }) {
  const abs = Math.min(Math.abs(score), 10);
  const pct = (abs / 10) * 100;
  const color = score > 0
    ? "bg-[var(--neu-success)] shadow-[0_8px_16px_color-mix(in_oklch,var(--neu-success)_22%,transparent)]"
    : score < 0
      ? "bg-[var(--neu-danger)] shadow-[0_8px_16px_color-mix(in_oklch,var(--neu-danger)_22%,transparent)]"
      : "bg-[var(--neu-text-soft)]";
  return (
    <div className="flex w-28 items-center gap-2.5">
      <div className="neu-surface-base neu-surface-inset flex-1 rounded-full p-1">
        <div className={cn("h-2 rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn("w-8 text-right font-mono text-xs font-semibold tabular-nums", score > 0 ? "text-[var(--neu-success)]" : score < 0 ? "text-[var(--neu-danger)]" : "text-[var(--neu-text-muted)]")}>
        {score > 0 ? "+" : ""}{score}
      </span>
    </div>
  );
}

function ScanDurationBadge({ startedAt, completedAt, isRunning }: { startedAt?: string; completedAt?: string | null; isRunning: boolean }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isRunning || !startedAt) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initializing timer value at effect start
    setNow(Date.now());
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
  return null;
}

function saveActiveScanId(id: string | null) {
  if (id) localStorage.setItem(SCAN_ID_KEY, id);
  else localStorage.removeItem(SCAN_ID_KEY);
}

function ScanConfigBanner({ scan }: { scan: ScanStatus }) {
  const [open, setOpen] = useState(false);

  const provider = scan.provider ?? "—";
  const mode = scan.workflow_mode === "quick_trade" ? "Quick Trade" : "Deep Analysis";

  return (
    <div className="neu-surface-base neu-surface-inset overflow-hidden rounded-[var(--neu-radius-md)]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span className="neu-surface-base neu-surface-raised flex size-8 shrink-0 items-center justify-center rounded-[var(--neu-radius-sm)] text-[var(--neu-accent)]">
          <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">Scan configuration snapshot</div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Provider, workflow, and model assignments</div>
        </div>
        <div className="hidden flex-wrap items-center gap-2 lg:flex">
          <TonePill tone="neutral">{provider}</TonePill>
          <TonePill tone={scan.workflow_mode === "quick_trade" ? "warning" : "accent"}>{mode}</TonePill>
          {scan.deep_think_llm ? <TonePill tone="accent">Deep · {scan.deep_think_llm}</TonePill> : null}
          {scan.quick_think_llm ? <TonePill tone="success">Quick · {scan.quick_think_llm}</TonePill> : null}
        </div>
        <svg
          className={cn("ml-auto size-4 shrink-0 text-[var(--neu-text-muted)] transition-transform", open && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-[color:var(--neu-stroke-soft)]/80 px-4 pb-4 pt-3">
          <div className="mb-3 flex flex-wrap gap-2 lg:hidden">
            <TonePill tone="neutral">{provider}</TonePill>
            <TonePill tone={scan.workflow_mode === "quick_trade" ? "warning" : "accent"}>{mode}</TonePill>
            {scan.deep_think_llm ? <TonePill tone="accent">Deep · {scan.deep_think_llm}</TonePill> : null}
            {scan.quick_think_llm ? <TonePill tone="success">Quick · {scan.quick_think_llm}</TonePill> : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {scan.backend_url ? <ScannerMetaItem label="Backend URL" value={scan.backend_url} /> : null}
            <ScannerMetaItem label="Workflow mode" value={mode} />
            <ScannerMetaItem label="Asset type" value={scan.asset_type ?? "crypto"} />
            {scan.research_depth != null ? <ScannerMetaItem label="Research depth" value={scan.research_depth} /> : null}
            {scan.max_debate_rounds != null ? <ScannerMetaItem label="Debate rounds" value={scan.max_debate_rounds} /> : null}
            {scan.interval ? <ScannerMetaItem label="Interval" value={scan.interval} /> : null}
          </div>
        </div>
      )}
    </div>
  );
}

export function ScannerPage() {
  const queryClient = useQueryClient();
  const { data: accountsList = [] } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(), staleTime: 60_000 });
  const accountLabelMap = Object.fromEntries(accountsList.map((a) => [a.id, a.label]));
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
  const [llmMinSpacingMs, setLlmMinSpacingMs] = useState<number>(0);
  const [endpoints, setEndpoints] = useState(loadEndpoints);
  const [showEndpoints, setShowEndpoints] = useState(false);
  const [agentModelOverrides, setAgentModelOverrides] = useState<Record<string, string>>(loadOverrides);
  const [autoTradeConfigs, setAutoTradeConfigs] = useState<import("@/api/client").AutoTradeConfig[]>(() => {
    try { return JSON.parse(localStorage.getItem("tradingagents_auto_trade_configs") ?? "[]"); } catch { return []; }
  });
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
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing localStorage into state after write
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
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing server config into local state
      setLlmMaxConcurrent(Number(configQuery.data.resolved.llm_max_concurrent));
    }
    if (configQuery.data?.resolved?.llm_min_spacing_ms != null) {
      setLlmMinSpacingMs(Number(configQuery.data.resolved.llm_min_spacing_ms));
    }
  }, [configQuery.data]);
  const remoteIds = (remoteModels ?? []).map((m) => m.id);
  const catalogDeep = getModelOptions(provider, "deep");
  const catalogQuick = getModelOptions(provider, "quick");
  const deepOptions = remoteModels?.length
    ? remoteModels.map((m) => ({ label: m.name ?? m.id, value: m.id }))
    : catalogDeep;
  const quickOptions = remoteModels?.length
    ? remoteModels.map((m) => ({ label: m.name ?? m.id, value: m.id }))
    : catalogQuick;

  const startMutation = useMutation({
    mutationFn: (body: ScanRequest) => apiClient.startScan(body),
    onSuccess: (data) => setActiveScanId(data.scan_id),
  });

  const cancelMutation = useMutation({
    mutationFn: (scanId: string) => apiClient.cancelScan(scanId),
    onSuccess: () => {
      if (activeScanId) queryClient.invalidateQueries({ queryKey: ["scan", activeScanId] });
      queryClient.invalidateQueries({ queryKey: ["scans"] });
    },
  });

  const saveLlmConcurrency = (value: number) => {
    setLlmMaxConcurrent(value);
    apiClient.updateConfig({ llm_max_concurrent: value });
  };

  const saveLlmMinSpacing = (value: number) => {
    const v = Math.max(0, Math.floor(value || 0));
    setLlmMinSpacingMs(v);
    apiClient.updateConfig({ llm_min_spacing_ms: v });
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
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clearing stale scan on query error
      setActiveScanId(null);
      setLostScan(true);
    }
  }, [scanQuery.isError, activeScanId]);

  const scan: ScanStatus | undefined = scanQuery.data;
  const isRunning = scan?.status === "running";
  const isDone = scan?.status === "completed" || scan?.status === "cancelled" || scan?.status === "failed";

  useEffect(() => {
    if (scan?.status === "cancelled" && scan.results.length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clearing empty cancelled scan
      setActiveScanId(null);
    }
  }, [scan?.status, scan?.results.length]);

  const handleStart = () => {
    const body: ScanRequest = {
      analysis_date: analysisDate,
      asset_type: "crypto",
      interval,
      provider: provider || undefined,
      llm_api_key: llmApiKey.trim() || undefined,
      deep_think_llm: deepModel.trim() || undefined,
      quick_think_llm: quickModel.trim() || undefined,
      backend_url: backendUrl.trim() || undefined,
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
      auto_trade_configs: autoTradeConfigs.length > 0 ? autoTradeConfigs.filter(c => c.account_id) : undefined,
    };
    startMutation.mutate(body);
  };

  const toggleAnalyst = (a: string) => {
    setAnalysts((prev) => prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]);
  };

  const allResults = scan?.results ?? [];
  const { filters: scanFilters, update: updateFilter, hasActive: hasActiveFilters, filtered: filteredResults, clearAll: clearFilters } = useScanFilters(allResults, "scanner");

  const buyResults = filteredResults.filter((r) => r.direction === "buy").sort((a, b) => b.score - a.score);
  const sellResults = filteredResults.filter((r) => r.direction === "sell").sort((a, b) => a.score - b.score);
  const holdResults = filteredResults.filter((r) => r.direction === "hold" || r.direction === "unknown");
  const [tradeTarget, setTradeTarget] = useState<{ symbol: string; direction: "buy" | "sell" } | null>(null);
  const [tradedSymbols, setTradedSymbols] = useState<Set<string>>(new Set());
  const handleTradeSuccess = (symbol: string) => setTradedSymbols((prev) => new Set(prev).add(symbol));
  const isCrypto = (scan?.asset_type ?? "crypto") === "crypto" || allResults.some((r) => /USDT$/.test(r.ticker));
  const handleTrade = isCrypto ? (symbol: string, direction: "buy" | "sell") => setTradeTarget({ symbol, direction }) : undefined;

  return (
    <div className="page-shell space-y-5 py-3">
      <PageHeader
        eyebrow="Scanner desk"
        title="Market Scanner"
        description="Sweep the Bybit USDT perpetual universe, review signal strength, and route the strongest setups from a denser scanner workstation."
        stats={[
          {
            label: "Mode",
            value: workflowMode === "quick_trade" ? "Quick Trade" : "Deep Analysis",
            tone: workflowMode === "quick_trade" ? "warning" : "success",
          },
          {
            label: "Interval",
            value: interval,
            tone: "accent",
          },
          {
            label: "Analysts",
            value: String(analysts.length),
            tone: analysts.length > 0 ? "success" : "neutral",
          },
          {
            label: "Scan State",
            value: activeScanId ? (isDone ? "Ready" : "Running") : "Idle",
            tone: activeScanId ? (isDone ? "success" : "accent") : "neutral",
          },
        ]}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              to="/scanner/history"
              className={cn(buttonVariants({ variant: "outline", size: "default" }), "touch-target")}
            >
              <svg className="mr-2 size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              History
            </Link>
            {activeScanId && isDone ? (
              <Button variant="outline" onClick={() => setActiveScanId(null)}>
                <svg className="mr-1.5 size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New Scan
              </Button>
            ) : null}
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{provider} provider</Badge>
          <Badge variant="outline">{maxParallel} max parallel</Badge>
          {taPrefilterEnabled ? (
            <Badge variant="outline">TA prefilter {taPrefilterThreshold}</Badge>
          ) : (
            <Badge variant="outline">Prefilter off</Badge>
          )}
          <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
        </div>
      </PageHeader>

      {/* Config */}
      {!activeScanId && (
        <div className="space-y-4">
          {lostScan && (
            <div className={cn(SCANNER_PANEL_CLASS, "border border-[color:color-mix(in_oklch,var(--neu-warning)_22%,var(--neu-stroke-soft))]")}>
              <div className="flex items-start gap-3 px-5 py-4">
                <span className="neu-surface-base neu-surface-raised flex size-10 shrink-0 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-warning)]">
                  <svg className="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-[var(--neu-warning)]">Previous scan was lost</p>
                  <p className="mt-1 text-[12px] leading-6 text-[var(--neu-text-muted)]">The backend restarted while a scan was running. Completed results remain in History. Start a fresh scan to continue.</p>
                </div>
                <Button type="button" variant="ghost" size="icon-xs" onClick={() => setLostScan(false)} aria-label="Dismiss lost scan notice">
                  <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </Button>
              </div>
            </div>
          )}
          <div className={cn(SCANNER_PANEL_CLASS, "p-5 space-y-5")}>
            <ScannerPanelHeader
              icon={(
                <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              )}
              title="Scan configuration"
              description="Core market sweep inputs, workflow routing, and analyst team composition"
            />

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
              <div className="space-y-4">
                <div className={SCANNER_SECTION_CLASS}>
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    <div className="space-y-2">
                      <Label className={SCANNER_LABEL_CLASS}>Analysis date</Label>
                      <Input type="date" value={analysisDate} max={getToday()} onChange={(e) => setAnalysisDate(e.target.value)} className="h-10 text-sm" />
                      <p className={SCANNER_HINT_CLASS}>Historical market date for replay analysis.</p>
                    </div>
                    <div className="space-y-2">
                      <Label className={SCANNER_LABEL_CLASS}>Kline interval</Label>
                      <Select value={interval} onValueChange={(v) => setInterval(v as CryptoInterval)}>
                        <SelectTrigger size="sm" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CRYPTO_INTERVALS.map((i) => (
                            <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className={SCANNER_HINT_CLASS}>Candlestick interval used by technical signals.</p>
                    </div>
                    <div className="space-y-2">
                      <Label className={SCANNER_LABEL_CLASS}>LLM provider</Label>
                      <Select value={provider} onValueChange={(value) => { if (value !== null) setProvider(value); }}>
                        <SelectTrigger size="sm" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PROVIDERS.map((p) => (
                            <SelectItem key={p} value={p}>{p}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className={SCANNER_HINT_CLASS}>Provider for scanner orchestration and debate agents.</p>
                    </div>
                  </div>
                </div>

                <div className={SCANNER_SECTION_CLASS}>
                  <div className="space-y-2">
                    <Label className={SCANNER_LABEL_CLASS}>Workflow mode</Label>
                    <div className={SCANNER_SEGMENT_CLASS} role="radiogroup" aria-label="Workflow mode">
                      {([
                        { value: "quick_trade" as const, label: "Quick trade" },
                        { value: "deep_analysis" as const, label: "Deep analysis" },
                      ]).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          role="radio"
                          aria-checked={workflowMode === opt.value}
                          className={cn(
                            SCANNER_SEGMENT_BUTTON_CLASS,
                            workflowMode === opt.value
                              ? "neu-surface-base neu-surface-raised shadow-[var(--neu-shadow-pill)] text-[var(--neu-text-strong)]"
                              : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]",
                          )}
                          onClick={() => setWorkflowMode(opt.value)}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                    <p className={SCANNER_HINT_CLASS}>
                      {workflowMode === "quick_trade"
                        ? "Shorter path from analyst consensus to trade card routing."
                        : "Full research, risk, and portfolio debate pipeline."}
                    </p>
                  </div>

                  <div className="mt-4 space-y-3">
                    <label className="flex items-start gap-3 rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))] px-3.5 py-3">
                      <input
                        type="checkbox"
                        id="scanner_ta_prefilter"
                        checked={taPrefilterEnabled}
                        onChange={(e) => setTaPrefilterEnabled(e.target.checked)}
                        className="peer sr-only"
                      />
                      <span className="relative mt-0.5 flex h-6 w-11 shrink-0 items-center rounded-full border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_12%,var(--neu-surface-muted))] p-1 transition-colors peer-checked:border-[color:color-mix(in_oklch,var(--neu-accent)_24%,var(--neu-stroke-soft))] peer-checked:bg-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-surface-raised))]">
                        <span className="neu-surface-base neu-surface-raised block size-4 rounded-full transition-transform peer-checked:translate-x-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="text-sm font-semibold text-[var(--neu-text-strong)]">Smart pre-screen</span>
                        <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">Run TA filtering before LLM debates so bulk scans skip low-conviction assets and reduce token spend.</p>
                      </div>
                    </label>

                    {taPrefilterEnabled ? (
                      <div className="flex flex-wrap items-center gap-3 rounded-[var(--neu-radius-md)] border border-[color:color-mix(in_oklch,var(--neu-accent)_16%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))] px-4 py-3">
                        <Label htmlFor="scanner_ta_threshold" className={SCANNER_LABEL_CLASS}>Threshold</Label>
                        <Input
                          id="scanner_ta_threshold"
                          type="number"
                          min={0}
                          max={100}
                          value={taPrefilterThreshold}
                          onChange={(e) => setTaPrefilterThreshold(Number(e.target.value))}
                          className="h-10 w-24"
                        />
                        <TonePill tone="accent">/ 100</TonePill>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className={SCANNER_SECTION_CLASS}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">Analyst team</div>
                    <div className="mt-1 text-sm font-semibold text-[var(--neu-text-strong)]">Select the specialists that participate in the scan.</div>
                  </div>
                  <Badge variant="secondary" className="px-3 py-1 text-[10px] tracking-[0.16em]">
                    {analysts.length}/{CRYPTO_ANALYSTS.length}
                  </Badge>
                </div>
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
                          "neu-focus-ring inline-flex min-h-10 items-center gap-2 rounded-[var(--neu-radius-pill)] border px-3.5 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] transition-all",
                          active
                            ? "neu-surface-base neu-surface-raised text-[var(--neu-accent)] border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]"
                            : "neu-surface-base neu-surface-flat text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] hover:text-[var(--neu-text-strong)]",
                        )}
                      >
                        <span className={cn("flex size-4 items-center justify-center rounded-full border", active ? "border-current bg-current/10" : "border-current/40")}>
                          {active ? (
                            <svg className="size-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={4}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          ) : null}
                        </span>
                        {label}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-4 text-[11px] leading-5 text-[var(--neu-text-muted)]">Technical, derivatives, news, fundamentals, and social analysts can be combined or trimmed depending on speed versus depth.</p>
              </div>
            </div>
          </div>

          <div className={SCANNER_PANEL_CLASS}>
            <button
              type="button"
              onClick={() => setShowWorkflow(!showWorkflow)}
              className="flex w-full items-center gap-3 px-5 py-4 text-left"
            >
              <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
                <svg className={cn("size-4 transition-transform duration-200", showWorkflow && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </span>
              <div className="flex min-w-0 items-center gap-3">
                <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
                  <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                  </svg>
                </span>
                <div>
                  <div className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">Workflow settings</div>
                  <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Research depth, debate rounds, checkpointing, and runtime limits</div>
                </div>
              </div>
            </button>
            {showWorkflow ? (
              <div className="border-t border-[color:var(--neu-stroke-soft)]/80 px-5 pb-5 pt-4">
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <div className="space-y-4">
                    <div className={SCANNER_SECTION_CLASS}>
                      <div className="flex items-center justify-between gap-3">
                        <Label className={SCANNER_LABEL_CLASS}>Research depth</Label>
                        <TonePill tone="accent" className="font-mono">{researchDepth}</TonePill>
                      </div>
                      <input
                        type="range"
                        min={1}
                        max={5}
                        step={1}
                        value={researchDepth}
                        onChange={(e) => setResearchDepth(Number(e.target.value))}
                        className="neu-slider mt-3 w-full"
                      />
                      <p className="mt-3 text-[11px] leading-5 text-[var(--neu-text-muted)]">1 is fastest. 5 spends the most time on multi-agent analysis.</p>
                    </div>

                    <div className={SCANNER_SECTION_CLASS}>
                      <Label className={SCANNER_LABEL_CLASS}>Output language</Label>
                      <Select value={outputLanguage} onValueChange={(value) => { if (value !== null) setOutputLanguage(value); }}>
                        <SelectTrigger size="sm" className="mt-2 w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {LANGUAGES.map((l) => (
                            <SelectItem key={l} value={l}>{l}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Final report language. Internal agent debate remains in English.</p>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className={SCANNER_SECTION_CLASS}>
                      <div className={cn("grid gap-4", workflowMode === "quick_trade" ? "grid-cols-1" : "sm:grid-cols-2")}>
                        <div className="space-y-2">
                          <Label className={SCANNER_LABEL_CLASS}>Max debate rounds</Label>
                          <Input type="number" min={1} max={10} value={maxDebateRounds} onChange={(e) => setMaxDebateRounds(Number(e.target.value))} className="h-10" />
                          <p className={SCANNER_HINT_CLASS}>Bull versus bear debate iterations.</p>
                        </div>
                        {workflowMode !== "quick_trade" ? (
                          <div className="space-y-2">
                            <Label className={SCANNER_LABEL_CLASS}>Max risk rounds</Label>
                            <Input type="number" min={1} max={10} value={maxRiskRounds} onChange={(e) => setMaxRiskRounds(Number(e.target.value))} className="h-10" />
                            <p className={SCANNER_HINT_CLASS}>Risk team discussion cycles.</p>
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <div className={SCANNER_SECTION_CLASS}>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-2">
                          <Label className={SCANNER_LABEL_CLASS}>Max recursion limit</Label>
                          <Input type="number" min={1} max={500} value={maxRecurLimit} onChange={(e) => setMaxRecurLimit(Number(e.target.value))} className="h-10" />
                          <p className={SCANNER_HINT_CLASS}>Upper bound on LangGraph execution steps.</p>
                        </div>
                        <div className="space-y-2">
                          <Label className={SCANNER_LABEL_CLASS}>Max parallel analyses</Label>
                          <Input type="number" min={1} max={15} value={maxParallel} onChange={(e) => setMaxParallel(Math.min(15, Math.max(1, Number(e.target.value))))} className="h-10" />
                          <p className={SCANNER_HINT_CLASS}>Concurrent symbol analyses from 1 to 15.</p>
                        </div>
                      </div>
                    </div>

                    <label className="flex items-start gap-3 rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))] px-3.5 py-3">
                      <input
                        type="checkbox"
                        checked={checkpointEnabled}
                        onChange={(e) => setCheckpointEnabled(e.target.checked)}
                        className="peer sr-only"
                      />
                      <span className="relative mt-0.5 flex h-6 w-11 shrink-0 items-center rounded-full border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_12%,var(--neu-surface-muted))] p-1 transition-colors peer-checked:border-[color:color-mix(in_oklch,var(--neu-accent)_24%,var(--neu-stroke-soft))] peer-checked:bg-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-surface-raised))]">
                        <span className="neu-surface-base neu-surface-raised block size-4 rounded-full transition-transform peer-checked:translate-x-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="text-sm font-semibold text-[var(--neu-text-strong)]">Enable checkpoints</span>
                        <p className="mt-1 text-[11px] leading-5 text-[var(--neu-text-muted)]">Persist progress after each major step so interrupted scans can resume instead of restarting.</p>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className={SCANNER_PANEL_CLASS}>
            <button
              type="button"
              onClick={() => setShowLlm(!showLlm)}
              className="flex w-full items-center gap-3 px-5 py-4 text-left"
            >
              <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
                <svg className={cn("size-4 transition-transform duration-200", showLlm && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </span>
              <div className="flex min-w-0 items-center gap-3">
                <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
                  <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </span>
                <div>
                  <div className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">LLM and proxy settings</div>
                  <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Endpoint routing, API credentials, model selection, and throttle controls</div>
                </div>
              </div>
            </button>
            {showLlm ? (
              <div className="border-t border-[color:var(--neu-stroke-soft)]/80 px-5 pb-5 pt-4">
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
                  <div className="space-y-4">
                    <div className={SCANNER_SECTION_CLASS}>
                      <div className="flex items-center justify-between gap-3">
                        <Label className={SCANNER_LABEL_CLASS}>Backend URL / proxy endpoint</Label>
                        <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
                      </div>
                      <div className="relative mt-2" ref={endpointsRef}>
                        <Input
                          value={backendUrl}
                          onChange={(e) => setBackendUrl(e.target.value)}
                          onFocus={() => endpoints.length > 1 && setShowEndpoints(true)}
                          placeholder="Enter backend URL"
                          className="h-10 pr-10"
                        />
                        {endpoints.length > 1 ? (
                          <button
                            type="button"
                            onClick={() => setShowEndpoints(!showEndpoints)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-[var(--neu-radius-sm)] p-1.5 text-[var(--neu-text-muted)] transition-colors hover:text-[var(--neu-text-strong)]"
                          >
                            <svg className={cn("size-4 transition-transform", showEndpoints && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                            </svg>
                          </button>
                        ) : null}
                        {showEndpoints && endpoints.length > 1 ? (
                          <div className="neu-surface-base neu-surface-raised absolute z-50 mt-2 max-h-56 w-full overflow-y-auto rounded-[var(--neu-radius-md)] p-2 shadow-[var(--neu-shadow-float)]">
                            {endpoints.map((ep) => (
                              <div
                                key={ep.url}
                                className={cn(
                                  "flex items-center gap-2 rounded-[var(--neu-radius-sm)] px-2.5 py-2 transition-colors",
                                  ep.url === backendUrl && "bg-[color:color-mix(in_oklch,var(--neu-accent)_12%,var(--neu-surface-raised))]",
                                )}
                              >
                                <button
                                  type="button"
                                  className={cn("min-w-0 flex-1 truncate text-left font-mono text-[12px]", ep.url === backendUrl ? "text-[var(--neu-accent)]" : "text-[var(--neu-text-strong)]")}
                                  onClick={() => selectEndpoint(ep)}
                                >
                                  {ep.url}
                                  {ep.deepModel ? <span className="ml-2 text-[var(--neu-text-muted)]">({ep.deepModel})</span> : null}
                                </button>
                                {ep.url !== backendUrl ? (
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-xs"
                                    onClick={(e) => { e.stopPropagation(); deleteEndpoint(ep.url); }}
                                    aria-label={`Remove ${ep.url}`}
                                  >
                                    <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                  </Button>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <TonePill tone="neutral">/v1/models auto-discovery</TonePill>
                        {remoteIds.length > 0 ? <TonePill tone="accent">{remoteIds.length} models loaded</TonePill> : null}
                      </div>
                    </div>

                    <div className={SCANNER_SECTION_CLASS}>
                      <div className="flex items-center justify-between gap-3">
                        <Label className={SCANNER_LABEL_CLASS}>API key</Label>
                        {llmApiKey.trim() ? <ConnBadge status={conn.status} latency={null} error={conn.errorMsg} label="Authenticated" /> : null}
                      </div>
                      <Input
                        type="password"
                        value={llmApiKey}
                        onChange={(e) => setLlmApiKey(e.target.value)}
                        placeholder="Provider API key"
                        className="mt-2 h-10"
                      />
                      <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Optional override for the selected provider. Leave empty to use environment credentials.</p>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className={SCANNER_SECTION_CLASS}>
                      <Label className={SCANNER_LABEL_CLASS}>Deep think model</Label>
                      <div className="mt-2">
                        <ModelSelect
                          options={deepOptions}
                          value={deepModel}
                          onChange={(value) => setDeepModel(value ?? "")}
                          placeholder="Select model..."
                        />
                      </div>
                      <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Used for heavier research management and synthesis.</p>
                    </div>

                    <div className={SCANNER_SECTION_CLASS}>
                      <Label className={SCANNER_LABEL_CLASS}>Quick think model</Label>
                      <div className="mt-2">
                        <ModelSelect
                          options={quickOptions}
                          value={quickModel}
                          onChange={(value) => setQuickModel(value ?? "")}
                          placeholder="Select model..."
                        />
                      </div>
                      <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Used for lightweight analyst passes and faster orchestration steps.</p>
                    </div>
                  </div>
                </div>

                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className={SCANNER_SECTION_CLASS}>
                    <Label className={SCANNER_LABEL_CLASS}>LLM concurrency limit</Label>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={llmMaxConcurrent}
                      onChange={(e) => saveLlmConcurrency(Number(e.target.value))}
                      className="mt-2 h-10 w-full sm:w-40"
                    />
                    <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Set to 0 for unlimited concurrent provider calls.</p>
                  </div>

                  <div className={SCANNER_SECTION_CLASS}>
                    <Label className={SCANNER_LABEL_CLASS}>Minimum spacing</Label>
                    <Input
                      type="number"
                      min={0}
                      max={60000}
                      value={llmMinSpacingMs}
                      onChange={(e) => saveLlmMinSpacing(Number(e.target.value))}
                      className="mt-2 h-10 w-full sm:w-40"
                    />
                    <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">Milliseconds between consecutive LLM API requests. Use 0 for no enforced spacing.</p>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className={cn(SCANNER_PANEL_CLASS, "p-5")}>
            <AgentModelOverrides
              assetType="crypto"
              modelOptions={deepOptions}
              overrides={agentModelOverrides}
              onChange={setAgentModelOverrides}
            />
          </div>

          <AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />

          <Button
            onClick={handleStart}
            disabled={startMutation.isPending || analysts.length === 0}
            className="w-full justify-center text-[0.78rem] font-semibold uppercase tracking-[0.18em]"
            size="lg"
          >
            {startMutation.isPending ? (
              <>
                <svg className="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Starting scan
              </>
            ) : (
              <>
                <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                Start full market scan
              </>
            )}
          </Button>
          {startMutation.isError && (
            <p className="text-center text-sm font-semibold text-[var(--neu-danger)]">
              Failed to start scan: {(startMutation.error as Error).message}
            </p>
          )}
        </div>
      )}

      {/* Progress */}
      {scan && scan.status !== "cancelled" && (
        <div className={cn(SCANNER_PANEL_CLASS, "p-5 space-y-5")}>
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {isRunning && (
                  <div className="neu-surface-base neu-surface-raised flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent)]">
                    <svg className="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  </div>
                )}
                {scan.status === "completed" && (
                  <div className="neu-surface-base neu-surface-raised flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-success)]">
                    <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                )}
                {scan.status === "failed" && (
                  <div className="neu-surface-base neu-surface-raised flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-danger)]">
                    <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                )}
                <div>
                  <h3 className="flex items-center gap-2.5 text-lg font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">
                    {isRunning ? "Scanning Market..." : scan.status === "completed" ? "Scan Complete" : scan.status === "cancelled" ? "Scan Cancelled" : "Scan Failed"}
                    <ScanDurationBadge startedAt={scan.started_at} completedAt={scan.completed_at} isRunning={isRunning} />
                  </h3>
                  <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Progress, outcomes, and live scanner telemetry</p>
                </div>
              </div>
              {isRunning ? (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => cancelMutation.mutate(scan.scan_id)}
                  disabled={cancelMutation.isPending}
                  className="uppercase tracking-[0.14em]"
                >
                  Cancel
                </Button>
              ) : null}
            </div>

            {/* Config summary */}
            {(scan.provider || scan.workflow_mode || scan.deep_think_llm) && (
              <ScanConfigBanner scan={scan} />
            )}

            {/* Progress bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
                <span>{scan.completed + scan.failed} / {scan.total} symbols completed</span>
                <span>{scan.total > 0 ? Math.round(((scan.completed + scan.failed) / scan.total) * 100) : 0}%</span>
              </div>
              <div className="neu-surface-base neu-surface-inset rounded-full p-1">
                <div
                  className="h-3 rounded-full bg-[linear-gradient(90deg,color-mix(in_oklch,var(--neu-accent)_38%,var(--neu-accent-muted)),var(--neu-accent))] transition-all duration-500 shadow-[0_10px_18px_color-mix(in_oklch,var(--neu-accent)_18%,transparent)]"
                  style={{ width: `${scan.total > 0 ? ((scan.completed + scan.failed) / scan.total) * 100 : 0}%` }}
                />
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <ScannerMetricCard tone="success" value={buyResults.length} label="Buy signals" />
              <ScannerMetricCard tone="danger" value={sellResults.length} label="Sell signals" />
              <ScannerMetricCard tone="warning" value={holdResults.length} label="Hold / neutral" />
            </div>

            {/* Auto-trade results */}
            {scan.auto_trade_results && scan.auto_trade_results.length > 0 && (
              <div className="space-y-3 border-t border-[color:var(--neu-stroke-soft)]/70 pt-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">Auto-trade executions</p>
                  <TonePill tone="accent">{scan.auto_trade_results.length} routes</TonePill>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <ScannerMetricCard tone="success" value={scan.auto_trade_results.filter(r => r.status === "success").length} label="Executed" />
                  <ScannerMetricCard tone="danger" value={scan.auto_trade_results.filter(r => r.status === "failed").length} label="Failed" />
                </div>
                <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
                  {scan.auto_trade_results.map((r, i) => (
                    <div key={i} className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[color:color-mix(in_oklch,var(--neu-highlight)_8%,var(--neu-surface-raised))] px-3.5 py-3" title={r.error || undefined}>
                      <div className="flex items-center gap-2 text-xs font-medium">
                        <span className="font-mono font-semibold text-[var(--neu-text-strong)]">{r.symbol}</span>
                        <TonePill tone={r.side === "buy" ? "success" : "danger"}>{r.side}</TonePill>
                        <span className="truncate text-[11px] text-[var(--neu-text-muted)]">{accountLabelMap[r.account_id] || r.account_id.slice(0, 8)}</span>
                        <span className={cn("ml-auto shrink-0 text-sm font-semibold", r.status === "success" ? "text-[var(--neu-success)]" : "text-[var(--neu-danger)]")}>
                          {r.status === "success" ? "✓" : "✗"}
                        </span>
                      </div>
                      {r.error ? <p className="mt-2 text-[11px] leading-5 text-[var(--neu-text-muted)]">{r.error}</p> : null}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Auto-trade account summaries (stopped reasons, rule failures) */}
            {scan.auto_trade_summaries && scan.auto_trade_summaries.length > 0 && (
              <div className="space-y-3 border-t border-[color:var(--neu-stroke-soft)]/70 pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">Account status</p>
                <div className="space-y-2">
                  {scan.auto_trade_summaries.filter((s: AutoTradeSummary) => s.stopped_reason).map((s: AutoTradeSummary, i: number) => (
                    <div key={i} className="rounded-[var(--neu-radius-md)] border border-[color:color-mix(in_oklch,var(--neu-warning)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-raised))] px-3.5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-semibold text-[var(--neu-text-strong)]">{accountLabelMap[s.account_id] || s.account_id?.slice(0, 8)}</span>
                        <TonePill tone="warning" className="ml-auto">{s.stopped_reason?.replace(/_/g, " ")}</TonePill>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Current batch tickers */}
            {isRunning && scan.current_tickers.length > 0 && (
              <div className="space-y-3 border-t border-[color:var(--neu-stroke-soft)]/70 pt-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">Currently analyzing</p>
                  <TonePill tone="accent">{scan.current_tickers.length} live</TonePill>
                </div>
                <div className="flex flex-wrap gap-2">
                  {scan.current_tickers.map((t) => (
                    <Badge key={t} variant="secondary" className="gap-2 px-3 py-1 text-[11px] tracking-[0.16em]">
                      <span className="size-2 rounded-full bg-[var(--neu-accent)] animate-pulse" />
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Results */}
      {scan && scan.results.length > 0 && (
        <>
          {/* Filter bar */}
          <ScanResultFiltersBar
            filters={scanFilters}
            update={updateFilter}
            hasActive={hasActiveFilters}
            totalCount={allResults.length}
            filteredCount={filteredResults.length}
            clearAll={clearFilters}
          />

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
                <ResultsTable results={buyResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </MobileCollapse>
              {/* Desktop: collapsible card */}
              <CollapsibleResultCard
                className="hidden md:block"
                storageKey="scanner:collapse:buy:desktop"
                defaultOpen
                color="emerald"
                title={`Buy Signals (${buyResults.length})`}
              >
                <ResultsTable results={buyResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
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
                <ResultsTable results={sellResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </MobileCollapse>
              <CollapsibleResultCard
                className="hidden md:block"
                storageKey="scanner:collapse:sell:desktop"
                defaultOpen
                color="red"
                title={`Sell Signals (${sellResults.length})`}
              >
                <ResultsTable results={sellResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
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
                <ResultsTable results={holdResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </MobileCollapse>
              <CollapsibleResultCard
                className="hidden md:block"
                storageKey="scanner:collapse:hold:desktop"
                defaultOpen={false}
                color="amber"
                title={`Hold / Neutral (${holdResults.length})`}
              >
                <ResultsTable results={holdResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </CollapsibleResultCard>
            </>
          )}
        </>
      )}

      {tradeTarget && (
        <PlaceTradeDialog
          open={!!tradeTarget}
          onOpenChange={(open) => { if (!open) setTradeTarget(null); }}
          symbol={tradeTarget.symbol}
          signalDirection={tradeTarget.direction}
          onTradeSuccess={handleTradeSuccess}
        />
      )}
    </div>
  );
}

const COLOR_MAP: Record<string, { dot: string; tone: keyof typeof TONE_PILL_STYLES }> = {
  emerald: { dot: "bg-[var(--neu-success)]", tone: "success" },
  red: { dot: "bg-[var(--neu-danger)]", tone: "danger" },
  amber: { dot: "bg-[var(--neu-warning)]", tone: "warning" },
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

  const tone = COLOR_MAP[color] ?? { dot: "bg-[var(--neu-text-soft)]", tone: "neutral" as const };

  return (
    <div className={cn(SCANNER_PANEL_CLASS, className)}>
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-3 px-5 py-4 text-left"
      >
        <span className="neu-surface-base neu-surface-raised flex size-9 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-text-muted)]">
          <svg className={cn("size-4 transition-transform duration-200", open && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <span className={cn("size-2.5 rounded-full shrink-0", tone.dot)} />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold tracking-[-0.03em] text-[var(--neu-text-strong)]">{title}</div>
          <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">Scanner results section</div>
        </div>
        <TonePill tone={tone.tone}>{color}</TonePill>
      </button>
      {open && (
        <div className="border-t border-[color:var(--neu-stroke-soft)]/80">
          {children}
        </div>
      )}
    </div>
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
    if (ok) { resolve(); } else { reject(new Error("execCommand failed")); }
  });
}

function ResultsTable({ results, isCrypto, onTrade, tradedSymbols }: { results: ScanResultItem[]; isCrypto?: boolean; onTrade?: (symbol: string, direction: "buy" | "sell") => void; tradedSymbols?: Set<string> }) {
  const [copiedTicker, setCopiedTicker] = useState<string | null>(null);

  function handleCopy(ticker: string) {
    copyToClipboard(ticker).then(() => {
      setCopiedTicker(ticker);
      setTimeout(() => setCopiedTicker(null), 1500);
    });
  }

  return (
    <div className="neu-table-wrap overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[color:var(--neu-stroke-soft)]/80 bg-[color:color-mix(in_oklch,var(--neu-highlight)_8%,var(--neu-surface-muted))] text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
            <th className="px-4 py-3 text-left">#</th>
            <th className="px-4 py-3 text-left">Symbol</th>
            <th className="hidden px-4 py-3 text-left md:table-cell">Signal</th>
            <th className="hidden px-4 py-3 text-left md:table-cell">Confidence</th>
            <th className="px-4 py-3 text-left">Strength</th>
            <th className="hidden px-4 py-3 text-left md:table-cell">Status</th>
            <th className="px-4 py-3 text-right"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--neu-stroke-soft)]/60">
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            const copied = copiedTicker === r.ticker;
            return (
              <tr key={r.ticker} className="group transition-colors hover:bg-[color:color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))]">
                <td className="px-4 py-3 font-mono text-xs text-[var(--neu-text-muted)]">{i + 1}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => handleCopy(r.ticker)}
                    title="Tap to copy"
                    className={cn(
                      "neu-focus-ring inline-flex items-center rounded-[var(--neu-radius-pill)] border px-3 py-1.5 text-sm font-semibold font-mono transition-all",
                      copied
                        ? "text-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_22%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-raised))]"
                        : "neu-surface-base neu-surface-flat text-[var(--neu-text-strong)] border-[color:var(--neu-stroke-soft)] group-hover:text-[var(--neu-accent)]",
                    )}
                  >
                    {copied ? (
                      <span className="flex items-center gap-1.5">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {r.ticker}
                      </span>
                    ) : r.ticker}
                  </button>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <TonePill tone={dir.label === "Buy" ? "success" : dir.label === "Sell" ? "danger" : "warning"}>{dir.label}</TonePill>
                </td>
                <td className="hidden px-4 py-3 text-xs font-semibold capitalize text-[var(--neu-text-muted)] md:table-cell">{r.confidence}</td>
                <td className="px-4 py-3"><ScoreBar score={r.score} /></td>
                <td className="px-4 py-3 hidden md:table-cell">
                  {r.status !== "completed" && r.decision_summary ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <TonePill tone={r.status === "completed" ? "success" : "danger"}>{r.status}</TonePill>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-sm text-xs leading-6">
                          {r.decision_summary}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    <TonePill tone={r.status === "completed" ? "success" : "danger"}>{r.status}</TonePill>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2.5">
                    {isCrypto && onTrade && (r.direction === "buy" || r.direction === "sell") && (
                      tradedSymbols?.has(r.ticker) ? (
                        <span className="inline-flex items-center gap-1">
                          <TonePill tone="success" className="gap-1.5">
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                          Traded
                          </TonePill>
                        </span>
                      ) : (
                        <Button
                          type="button"
                          onClick={() => onTrade(r.ticker, r.direction as "buy" | "sell")}
                          variant="secondary"
                          size="xs"
                          className={cn(
                            "uppercase tracking-[0.14em]",
                            r.direction === "buy"
                              ? "text-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-raised))]"
                              : "text-[var(--neu-danger)] border-[color:color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-raised))]",
                          )}
                        >
                          Trade
                        </Button>
                      )
                    )}
                    {r.run_id && (
                      <Link
                        to="/analysis/$runId"
                        params={{ runId: r.run_id }}
                        className={buttonVariants({ variant: "outline", size: "xs" })}
                      >
                        View
                      </Link>
                    )}
                    {!r.run_id && r.status !== "completed" && r.decision_summary && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger>
                            <span className="text-xs font-semibold text-[var(--neu-text-muted)] underline decoration-dotted underline-offset-4">
                              Why?
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="left" className="max-w-sm text-xs leading-6">
                            {r.decision_summary}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
