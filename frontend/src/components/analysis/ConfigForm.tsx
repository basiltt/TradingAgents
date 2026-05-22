import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { useForm, Controller } from "react-hook-form";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { apiClient, type StartAnalysisRequest, type AssetType, type CryptoInterval } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Combobox } from "@/components/ui/combobox";
import { useModels } from "@/hooks/useModels";
import { useSymbols } from "@/hooks/useSymbols";
import { useConnectivityCheck } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";
import { ConnBadge } from "@/components/ui/conn-badge";
import { loadEndpoints, saveEndpoint, removeEndpoint, type EndpointProfile } from "@/lib/endpoints";
import { ModelSelect } from "@/components/ui/model-select";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/layout/PageHeader";
import { WatchlistPanel } from "./WatchlistPanel";
import { AgentModelOverrides, loadOverrides, filterOverridesForAssetType } from "./AgentModelOverrides";
import { cn } from "@/lib/utils";

const TICKER_REGEX = /^[A-Z0-9.\-^]{1,15}$/;
const CRYPTO_TICKER_REGEX = /^[A-Z0-9]{2,20}$/;
const PROVIDERS_FALLBACK = ["openai", "anthropic", "google", "deepseek", "nvidia", "xai", "qwen", "glm", "openrouter", "azure", "ollama"];
const STOCK_ANALYSTS = ["market", "social", "news", "fundamentals"] as const;
const CRYPTO_ANALYSTS = ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"] as const;
const CRYPTO_INTERVALS: { value: CryptoInterval; label: string }[] = [
  { value: "15", label: "15 min" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "D", label: "1 day" },
];
const LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "Hindi", "Spanish", "Portuguese", "French", "German", "Arabic", "Russian"] as const;
const VENDOR_OPTIONS = ["yfinance", "alpha_vantage"] as const;

const STORAGE_KEY = "tradingagents_settings";

/* ---------- small helpers ---------- */

function SectionToggle({ label, open, onToggle, badge }: { label: string; open: boolean; onToggle: () => void; badge?: string }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center gap-2.5 text-sm font-bold text-muted-foreground hover:text-foreground transition-colors w-full py-1 cursor-pointer select-none"
    >
      <svg className={`w-4 h-4 text-primary transition-transform duration-300 ${open ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
      </svg>
      {label}
      {badge && (
        <span className="ml-auto text-[10px] px-2.5 py-0.5 rounded-full bg-primary/10 text-primary font-extrabold uppercase tracking-wider">{badge}</span>
      )}
    </button>
  );
}

/* ---------- persistence ---------- */

interface SavedSettings {
  asset_type?: AssetType;
  provider?: string;
  llm_api_key?: string;
  backend_url?: string;
  ticker?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  analysts?: string[];
  research_depth?: number;
  output_language?: string;
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  max_recur_limit?: number;
  checkpoint_enabled?: boolean;
  interval?: CryptoInterval;
  data_vendors?: Record<string, string>;
  workflow_mode?: "quick_trade" | "deep_analysis";
  ta_prefilter_enabled?: boolean;
  ta_prefilter_threshold?: number;
}

function loadSettings(): SavedSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveSettings(s: SavedSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

/* ---------- form values ---------- */

interface FormValues {
  asset_type: AssetType;
  ticker: string;
  analysis_date: string;
  provider: string;
  llm_api_key: string;
  backend_url: string;
  deep_think_llm: string;
  quick_think_llm: string;
  analysts: string[];
  research_depth: number;
  output_language: string;
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
  max_recur_limit: number;
  checkpoint_enabled: boolean;
  interval: CryptoInterval;
  data_vendor_core: string;
  data_vendor_technical: string;
  data_vendor_fundamental: string;
  data_vendor_news: string;
  workflow_mode: "quick_trade" | "deep_analysis";
  ta_prefilter_enabled: boolean;
  ta_prefilter_threshold: number;
}

const ANALYST_DETAILS: Record<string, { label: string; desc: string; icon: React.ReactNode }> = {
  market: {
    label: "Technical Analyst",
    desc: "Studies price charts, moving averages, relative strength, and momentum indicators.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7 12l3-3 3 3 4-4M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
    ),
  },
  social: {
    label: "Social Sentiment Analyst",
    desc: "Scans social platforms, reddit, and news boards for community sentiment and retail interest.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z" />
      </svg>
    ),
  },
  news: {
    label: "News Sentiment Analyst",
    desc: "Analyzes breaking financial news headlines, articles, and press announcements.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
      </svg>
    ),
  },
  fundamentals: {
    label: "Fundamental Analyst",
    desc: "Audits company financial health, earnings reports, P/E ratios, and balance sheets.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h-2a2 2 0 00-2-2z" />
      </svg>
    ),
  },
  crypto_technical: {
    label: "Technical Specialist",
    desc: "Tracks order flow, volume trends, moving averages, and crypto-specific indicators.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h-2a2 2 0 00-2-2z" />
      </svg>
    ),
  },
  crypto_derivatives: {
    label: "Derivatives Specialist",
    desc: "Monitors futures funding rates, open interest trends, and liquidation volumes.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 7.89H17.5" />
      </svg>
    ),
  },
  crypto_news: {
    label: "News Evaluator",
    desc: "Evaluates flash reports, regulatory headlines, and major token events.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
      </svg>
    ),
  },
  crypto_fundamentals: {
    label: "Tokenomics Auditor",
    desc: "Checks token vesting schedules, treasury allocations, supply dynamics, and on-chain TVL.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M12 16c1.657 0 3-.895 3-2s-1.343-2-3-2-3 .895-3 2 1.343 2 3 2m0-8V7m0 8v1m-9-6a9 9 0 1118 0 9 9 0 01-18 0z" />
      </svg>
    ),
  },
  crypto_social: {
    label: "Sentiment Miner",
    desc: "Filters coin discussion channels, Telegram/Discord signals, and Twitter hype metrics.",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z" />
      </svg>
    ),
  },
};

export function ConfigForm() {
  const navigate = useNavigate();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const saved = useMemo(() => loadSettings(), []);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const isTest =
    (typeof window !== "undefined" && ((window as any).__vitest_worker__ || (window as any).process?.env?.NODE_ENV === "test")) ||
    (typeof globalThis !== "undefined" && ((globalThis as any).process?.env?.NODE_ENV === "test"));

  const [showLLM, setShowLLM] = useState(!!(saved.llm_api_key || saved.backend_url || saved.deep_think_llm || saved.quick_think_llm));
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [showData, setShowData] = useState(false);
  const [endpoints, setEndpoints] = useState(loadEndpoints);
  const [showEndpoints, setShowEndpoints] = useState(false);
  const [agentModelOverrides, setAgentModelOverrides] = useState<Record<string, string>>(loadOverrides);
  const endpointsRef = useRef<HTMLDivElement>(null);

  const { data: configData } = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 60_000,
  });

  const { data: providersData } = useQuery({
    queryKey: ["providers"],
    queryFn: ({ signal }) => apiClient.getProviders(signal),
    staleTime: 300_000,
  });
  const PROVIDERS = providersData?.providers ?? PROVIDERS_FALLBACK;

  const resolved = configData?.resolved ?? {};
  const envProvider = String(resolved.llm_provider ?? "openai");
  const envBackendUrl = resolved.backend_url ? String(resolved.backend_url) : "";
  const envDeepThink = String(resolved.deep_think_llm ?? "");
  const envQuickThink = String(resolved.quick_think_llm ?? "");

  const {
    register,
    handleSubmit,
    control,
    setValue,
    watch,
    trigger,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      asset_type: saved.asset_type || "stock",
      ticker: saved.ticker || "",
      analysis_date: new Date().toISOString().split("T")[0],
      provider: saved.provider || envProvider,
      llm_api_key: saved.llm_api_key || "",
      backend_url: saved.backend_url || "",
      deep_think_llm: saved.deep_think_llm || "",
      quick_think_llm: saved.quick_think_llm || "",
      analysts: saved.analysts || [...STOCK_ANALYSTS],
      research_depth: saved.research_depth ?? 3,
      output_language: saved.output_language || "English",
      max_debate_rounds: saved.max_debate_rounds ?? 1,
      max_risk_discuss_rounds: saved.max_risk_discuss_rounds ?? 1,
      max_recur_limit: saved.max_recur_limit ?? 100,
      checkpoint_enabled: saved.checkpoint_enabled ?? false,
      interval: saved.interval || "60",
      data_vendor_core: saved.data_vendors?.core_stock_apis || "yfinance",
      data_vendor_technical: saved.data_vendors?.technical_indicators || "yfinance",
      data_vendor_fundamental: saved.data_vendors?.fundamental_data || "yfinance",
      data_vendor_news: saved.data_vendors?.news_data || "yfinance",
      workflow_mode: saved.workflow_mode || "deep_analysis",
      ta_prefilter_enabled: saved.ta_prefilter_enabled ?? false,
      ta_prefilter_threshold: saved.ta_prefilter_threshold ?? 40,
    },
  });

  // eslint-disable-next-line react-hooks/incompatible-library -- react-hook-form watch() is not memoizable
  const selectedProvider = watch("provider");
  const watchedApiKey = watch("llm_api_key");
  const watchedAssetType = watch("asset_type");
  const watchedBackendUrl = watch("backend_url");
  const watchedDeep = watch("deep_think_llm");
  const watchedQuick = watch("quick_think_llm");
  const watchedAnalysts = watch("analysts");
  const watchedDepth = watch("research_depth");
  const watchedLang = watch("output_language");
  const watchedDebate = watch("max_debate_rounds");
  const watchedRisk = watch("max_risk_discuss_rounds");
  const watchedRecur = watch("max_recur_limit");
  const watchedCheckpoint = watch("checkpoint_enabled");
  const watchedInterval = watch("interval");
  const watchedTicker = watch("ticker");
  const watchedVendorCore = watch("data_vendor_core");
  const watchedVendorTech = watch("data_vendor_technical");
  const watchedVendorFund = watch("data_vendor_fundamental");
  const watchedVendorNews = watch("data_vendor_news");
  const watchedWorkflowMode = watch("workflow_mode");
  const watchedPrefilter = watch("ta_prefilter_enabled");
  const watchedPrefilterThreshold = watch("ta_prefilter_threshold");

  const isCrypto = watchedAssetType === "crypto";
  const activeAnalysts = isCrypto ? CRYPTO_ANALYSTS : STOCK_ANALYSTS;
  const { data: cryptoSymbols = [], isLoading: symbolsLoading } = useSymbols(watchedAssetType);

  useEffect(() => {
    saveSettings({
      asset_type: watchedAssetType,
      ticker: watchedTicker,
      provider: selectedProvider,
      llm_api_key: watchedApiKey,
      backend_url: watchedBackendUrl,
      deep_think_llm: watchedDeep,
      quick_think_llm: watchedQuick,
      analysts: watchedAnalysts,
      research_depth: watchedDepth,
      output_language: watchedLang,
      max_debate_rounds: watchedDebate,
      max_risk_discuss_rounds: watchedRisk,
      max_recur_limit: watchedRecur,
      checkpoint_enabled: watchedCheckpoint,
      interval: watchedInterval,
      data_vendors: {
        core_stock_apis: watchedVendorCore,
        technical_indicators: watchedVendorTech,
        fundamental_data: watchedVendorFund,
        news_data: watchedVendorNews,
      },
      workflow_mode: watchedWorkflowMode,
      ta_prefilter_enabled: watchedPrefilter,
      ta_prefilter_threshold: watchedPrefilterThreshold,
    });
  }, [watchedAssetType, watchedTicker, selectedProvider, watchedApiKey, watchedBackendUrl, watchedDeep, watchedQuick, watchedAnalysts, watchedDepth, watchedLang, watchedDebate, watchedRisk, watchedRecur, watchedCheckpoint, watchedInterval, watchedVendorCore, watchedVendorTech, watchedVendorFund, watchedVendorNews, watchedWorkflowMode, watchedPrefilter, watchedPrefilterThreshold]);

  useEffect(() => {
    if (watchedBackendUrl?.trim()) {
      saveEndpoint({
        url: watchedBackendUrl.trim(),
        apiKey: watchedApiKey?.trim() || undefined,
        deepModel: watchedDeep?.trim() || undefined,
        quickModel: watchedQuick?.trim() || undefined,
      });
      setEndpoints(loadEndpoints());
    }
  }, [watchedBackendUrl, watchedApiKey, watchedDeep, watchedQuick]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (endpointsRef.current && !endpointsRef.current.contains(e.target as Node)) setShowEndpoints(false);
    }
    if (showEndpoints) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showEndpoints]);

  const selectEndpoint = useCallback(
    (ep: EndpointProfile) => {
      setValue("backend_url", ep.url);
      if (ep.apiKey != null) setValue("llm_api_key", ep.apiKey);
      if (ep.deepModel) setValue("deep_think_llm", ep.deepModel);
      if (ep.quickModel) setValue("quick_think_llm", ep.quickModel);
      setShowEndpoints(false);
    },
    [setValue],
  );

  const deleteEndpoint = useCallback(
    (url: string) => {
      removeEndpoint(url);
      setEndpoints(loadEndpoints());
    },
    [],
  );

  const trimmedBackendUrl = useMemo(() => watchedBackendUrl?.trim() || undefined, [watchedBackendUrl]);
  const { data: proxyModels, isLoading: modelsLoading, isError: modelsError } = useModels(trimmedBackendUrl, watchedApiKey?.trim() || undefined);
  const backendConn = useConnectivityCheck(trimmedBackendUrl, watchedApiKey?.trim() || undefined, 800, selectedProvider);

  const deepOptions = useMemo(() => {
    if (proxyModels?.length) return proxyModels.map((m) => ({ label: m.name ?? m.id, value: m.id }));
    return getModelOptions(selectedProvider, "deep");
  }, [proxyModels, selectedProvider]);

  const quickOptions = useMemo(() => {
    if (proxyModels?.length) return proxyModels.map((m) => ({ label: m.name ?? m.id, value: m.id }));
    return getModelOptions(selectedProvider, "quick");
  }, [proxyModels, selectedProvider]);

  // Reset model selections when provider changes and current value isn't in new options
  useEffect(() => {
    if (deepOptions.length && watchedDeep && !deepOptions.some((o) => o.value === watchedDeep)) {
      setValue("deep_think_llm", deepOptions[0].value);
    }
    if (quickOptions.length && watchedQuick && !quickOptions.some((o) => o.value === watchedQuick)) {
      setValue("quick_think_llm", quickOptions[0].value);
    }
  }, [deepOptions, quickOptions, watchedDeep, watchedQuick, setValue]);

  async function onSubmit(data: FormValues) {
    setSubmitError(null);
    try {
      const isCryptoSubmit = data.asset_type === "crypto";
      const defaultAnalysts = isCryptoSubmit ? [...CRYPTO_ANALYSTS] : [...STOCK_ANALYSTS];
      const allSelected = data.analysts.length === defaultAnalysts.length &&
        defaultAnalysts.every((a) => data.analysts.includes(a));

      const body: StartAnalysisRequest = {
        ticker: data.ticker.toUpperCase(),
        analysis_date: data.analysis_date,
        asset_type: data.asset_type,
        provider: data.provider || undefined,
        llm_api_key: data.llm_api_key.trim() || undefined,
        backend_url: data.backend_url.trim() || undefined,
        deep_think_llm: data.deep_think_llm.trim() || undefined,
        quick_think_llm: data.quick_think_llm.trim() || undefined,
        analysts: allSelected ? undefined : data.analysts,
        research_depth: data.research_depth !== 3 ? data.research_depth : undefined,
        output_language: data.output_language !== "English" ? data.output_language : undefined,
        max_debate_rounds: data.max_debate_rounds,
        max_risk_discuss_rounds: data.max_risk_discuss_rounds,
        max_recur_limit: data.max_recur_limit !== 100 ? data.max_recur_limit : undefined,
        checkpoint_enabled: data.checkpoint_enabled || undefined,
        workflow_mode: data.workflow_mode !== "deep_analysis" ? data.workflow_mode : undefined,
        ta_prefilter_enabled: isCryptoSubmit ? data.ta_prefilter_enabled : undefined,
        ta_prefilter_threshold: isCryptoSubmit && data.ta_prefilter_enabled ? data.ta_prefilter_threshold : undefined,
        ...(isCryptoSubmit
          ? { interval: data.interval }
          : {
               data_vendors: {
                 core_stock_apis: data.data_vendor_core,
                 technical_indicators: data.data_vendor_technical,
                 fundamental_data: data.data_vendor_fundamental,
                 news_data: data.data_vendor_news,
               },
             }),
        agent_model_overrides: (() => {
          const filtered = filterOverridesForAssetType(agentModelOverrides, isCryptoSubmit ? "crypto" : "stock");
          return Object.keys(filtered).length > 0 ? filtered : undefined;
        })(),
      };
      const result = await apiClient.startAnalysis(body);
      navigate({ to: "/analysis/$runId", params: { runId: result.run_id } });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    }
  }

  return (
    <div className="page-shell space-y-4 sm:space-y-6 animate-fade-in-up pb-8">
      <PageHeader
        eyebrow="Analysis"
        title="New Analysis"
        description=""
        stats={[
          {
            label: "Asset Class",
            value: watchedAssetType === "crypto" ? "Crypto" : "Stock",
            tone: "accent",
          },
          {
            label: "Analysts",
            value: String(watchedAnalysts.length),
            tone: watchedAnalysts.length > 0 ? "success" : "neutral",
          },
          {
            label: "Workflow",
            value: watchedWorkflowMode === "quick_trade" ? "Quick Trade" : "Deep Analysis",
            tone: watchedWorkflowMode === "quick_trade" ? "warning" : "success",
          },
          {
            label: "Provider",
            value: selectedProvider || "Auto",
            tone: "neutral",
          },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{watchedTicker ? `Ticker ${watchedTicker.toUpperCase()}` : "Ticker pending"}</Badge>
          <Badge variant="outline">{watchedLang || "English"} output</Badge>
          {watchedAssetType === "crypto" && watchedInterval ? (
            <Badge variant="outline">{watchedInterval} interval</Badge>
          ) : null}
          <ConnBadge
            status={backendConn.status}
            latency={backendConn.latency}
            error={backendConn.errorMsg}
          />
        </div>
      </PageHeader>

      {/* Progress Stepper */}
      <div className="glass-card mb-3 sm:mb-5 flex w-full items-center justify-between gap-1.5 sm:gap-2 rounded-[calc(var(--radius)*1.4)] sm:rounded-[calc(var(--radius)*1.65)] border border-border/60 px-3 py-2.5 sm:px-5 sm:py-3">
        {[
          { stepNum: 1, title: "Target Asset" },
          { stepNum: 2, title: "Analyst Team" },
          { stepNum: 3, title: "Engine Setup" },
        ].map((s, idx) => (
          <div key={s.stepNum} className="flex items-center flex-1 last:flex-initial">
            <button
              type="button"
              onClick={async () => {
                if (s.stepNum < step) {
                  setStep(s.stepNum as 1 | 2 | 3);
                } else if (s.stepNum === 2 && step === 1) {
                  const isValid = await trigger(["ticker", "analysis_date"]);
                  if (isValid) setStep(2);
                } else if (s.stepNum === 3 && step === 2) {
                  const isValid1 = await trigger(["ticker", "analysis_date"]);
                  const isValid2 = await trigger(["analysts"]);
                  if (isValid1 && isValid2) setStep(3);
                }
              }}
              className="flex flex-col items-center gap-2 focus:outline-none cursor-pointer group"
            >
              <div
                className={cn(
                  "flex h-8 w-8 sm:h-10 sm:w-10 items-center justify-center rounded-[calc(var(--radius)*1.1)] border font-bold text-xs transition-all duration-300",
                  step === s.stepNum
                    ? "bg-primary border-primary text-primary-foreground shadow-lg shadow-primary/20 scale-110"
                    : step > s.stepNum
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
                    : "bg-muted/30 border-border/50 text-muted-foreground group-hover:border-muted-foreground/50"
                )}
              >
                {step > s.stepNum ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  s.stepNum
                )}
              </div>
              <span
                className={cn(
                  "text-[9px] font-black uppercase tracking-[0.24em] transition-all text-center",
                  step === s.stepNum ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {s.title}
              </span>
            </button>
            {idx < 2 && (
              <div
                className={cn(
                  "mx-3 h-[2px] flex-1 rounded-full transition-all duration-500 sm:mx-4",
                  step > s.stepNum ? "bg-emerald-500/30" : "bg-border/30"
                )}
              />
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
        {/* Step 1: Target Asset */}
        {(step === 1 || isTest) && (
          <div className="glass-card border border-border/50 rounded-xl sm:rounded-2xl shadow-sm overflow-hidden bg-card/65 animate-fade-in">
            <div className="px-3.5 sm:px-5 pt-3.5 sm:pt-5 pb-2.5 sm:pb-3.5 border-b border-border/40">
              <h2 className="text-base font-bold flex items-center gap-2 text-foreground">
                <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
                Core Target Settings
              </h2>
            </div>
            <div className="flex flex-col gap-4 sm:gap-5 p-3.5 sm:p-5">
              {/* Asset Type Toggle */}
              <div className="flex flex-col gap-2">
                <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Asset Type</Label>
                <Controller
                  name="asset_type"
                  control={control}
                  render={({ field }) => (
                    <div className="flex p-1 bg-muted/60 rounded-xl border border-border/40" role="radiogroup" aria-label="Asset type">
                      {(["stock", "crypto"] as const).map((t) => (
                        <button
                          key={t}
                          type="button"
                          role="radio"
                          aria-checked={field.value === t}
                          className={`flex-1 px-5 py-2.5 rounded-lg text-xs font-extrabold uppercase tracking-wider transition-all cursor-pointer ${
                            field.value === t
                              ? "bg-background text-foreground shadow shadow-black/5"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                          onClick={() => {
                            field.onChange(t);
                            const defaults = t === "crypto" ? [...CRYPTO_ANALYSTS] : [...STOCK_ANALYSTS];
                            setValue("analysts", defaults);
                            setValue("ticker", "");
                          }}
                        >
                          {t === "stock" ? "Stock" : "Crypto Futures"}
                        </button>
                      ))}
                    </div>
                  )}
                />
              </div>

              {/* Workflow Mode Toggle */}
              <div className="flex flex-col gap-2">
                <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Workflow Mode</Label>
                <Controller
                  name="workflow_mode"
                  control={control}
                  render={({ field }) => (
                    <div className="flex p-1 bg-muted/60 rounded-xl border border-border/40" role="radiogroup" aria-label="Workflow mode">
                      {([
                        { value: "quick_trade" as const, label: "Quick Trade Pipeline" },
                        { value: "deep_analysis" as const, label: "Deep Analysis Engine" },
                      ]).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          role="radio"
                          aria-checked={field.value === opt.value}
                          className={`flex-1 px-5 py-2.5 rounded-lg text-xs font-extrabold uppercase tracking-wider transition-all cursor-pointer ${
                            field.value === opt.value
                              ? "bg-background text-foreground shadow shadow-black/5"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                          onClick={() => field.onChange(opt.value)}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  )}
                />
                <p className="text-xs text-muted-foreground font-medium pl-1">
                  {watchedWorkflowMode === "quick_trade"
                    ? "⚡ Analysts → Research Debate → Instant Trade Card Generation"
                    : "🛡️ Comprehensive Pipeline with Risk Review, Compliance & Portfolio checks"}
                </p>
              </div>

              {/* TA Pre-Screen (crypto only) */}
              {isCrypto && (
                <div className="flex flex-col gap-2 bg-muted/30 border border-border/30 rounded-xl p-4 transition-all">
                  <div className="flex items-center gap-3">
                    <Controller
                      name="ta_prefilter_enabled"
                      control={control}
                      render={({ field }) => (
                        <Checkbox
                          id="ta_prefilter_enabled"
                          checked={field.value}
                          onCheckedChange={(checked) => field.onChange(!!checked)}
                        />
                      )}
                    />
                    <Label htmlFor="ta_prefilter_enabled" className="font-bold text-sm cursor-pointer select-none">
                      Smart TA Pre-Screening Filter
                    </Label>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed pl-7">
                    Executes instant indicators precheck. Skips advanced LLMs if zero-momentum setup is found. Saves token costs.
                  </p>
                  {watch("ta_prefilter_enabled") && (
                    <div className="flex items-center gap-3 pl-7 mt-2">
                      <Label htmlFor="ta_prefilter_threshold" className="text-xs font-semibold whitespace-nowrap">Admissibility Threshold</Label>
                      <Input
                        id="ta_prefilter_threshold"
                        type="number"
                        min={0}
                        max={100}
                        className="w-20 h-8 text-xs font-mono font-bold"
                        {...register("ta_prefilter_threshold", { valueAsNumber: true })}
                      />
                      <span className="text-xs text-muted-foreground font-medium">/ 100 (lower threshold = more permissive runs)</span>
                    </div>
                  )}
                </div>
              )}

              {/* Ticker and Date Side-by-Side */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {/* Ticker */}
                <div className="flex flex-col gap-2">
                  <Label htmlFor="ticker" className="font-bold text-xs uppercase tracking-wider text-muted-foreground">
                    {isCrypto ? "Bybit Trading Pair" : "Equity Ticker Symbol"}
                  </Label>
                  {isCrypto ? (
                    <Controller
                      name="ticker"
                      control={control}
                      rules={{
                        required: "Trading pair is required",
                        validate: (v) =>
                          CRYPTO_TICKER_REGEX.test(v) || "Enter a valid pair (2-20 chars: A-Z, 0-9)",
                      }}
                      render={({ field }) => (
                        <Combobox
                          options={cryptoSymbols}
                          value={field.value}
                          onChange={(v) => field.onChange(v)}
                          placeholder="Search Bybit pairs (e.g. BTCUSDT)..."
                          loading={symbolsLoading}
                          className="font-mono text-sm tracking-wide h-10"
                        />
                      )}
                    />
                  ) : (
                    <Input
                      id="ticker"
                      placeholder="e.g. AAPL, SPY, MSFT"
                      className="font-mono text-sm tracking-widest font-extrabold uppercase h-10 bg-card"
                      aria-invalid={!!errors.ticker}
                      {...register("ticker", {
                        required: "Ticker is required",
                        validate: (v) => {
                          if (!TICKER_REGEX.test(v)) {
                            return "Enter a valid ticker (1-15 chars: A-Z, 0-9, . - ^)";
                          }
                          return true;
                        },
                        onChange: (e) => setValue("ticker", e.target.value.toUpperCase(), { shouldValidate: false }),
                      })}
                    />
                  )}
                  {errors.ticker ? (
                    <p className="text-xs text-destructive font-semibold">{errors.ticker.message}</p>
                  ) : (
                    <p className="text-[10px] text-muted-foreground font-medium pl-1">
                      {isCrypto ? "Linear USDT Perpetual contracts" : "Global Stock symbol ticker listed on exchanges"}
                    </p>
                  )}
                </div>

                {/* Date */}
                <div className="flex flex-col gap-2">
                  <Label htmlFor="analysis_date" className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Analysis Date</Label>
                  <Input
                    id="analysis_date"
                    type="date"
                    max={new Date().toISOString().split("T")[0]}
                    className="h-10 bg-card text-sm font-semibold"
                    aria-invalid={!!errors.analysis_date}
                    {...register("analysis_date", {
                      required: "Date is required",
                      validate: (v) => v <= new Date().toISOString().split("T")[0] || "Date cannot be in the future",
                    })}
                  />
                  {errors.analysis_date ? (
                    <p className="text-xs text-destructive font-semibold">{errors.analysis_date.message}</p>
                  ) : (
                    <p className="text-[10px] text-muted-foreground font-medium pl-1">The focal execution date context for agents</p>
                  )}
                </div>
              </div>

              {/* Crypto Interval — only for crypto */}
              {isCrypto && (
                <div className="flex flex-col gap-2">
                  <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Kline Interval</Label>
                  <Controller
                    name="interval"
                    control={control}
                    render={({ field }) => (
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger className="h-10 bg-card"><SelectValue placeholder="Select interval" /></SelectTrigger>
                        <SelectContent>
                          {CRYPTO_INTERVALS.map((i) => (
                            <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                  <p className="text-xs text-muted-foreground font-medium pl-1">Base candle resolution parsed by technical evaluation engines</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Step 2: Analyst Team Config */}
        {(step === 2 || isTest) && (
          <div className="glass-card border border-border/50 rounded-2xl shadow-sm overflow-hidden bg-card/65 animate-fade-in p-5 space-y-5">
            <div className="border-b border-border/40 pb-4">
              <h2 className="text-base font-bold flex items-center gap-2 text-foreground">
                <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-3c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-3c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
                Analyst Team Configuration
              </h2>
              <p className="text-xs text-muted-foreground mt-1 font-medium">Activate specific expert agents to include in this debate pipeline.</p>
            </div>

            {/* Analyst Check-Cards */}
            <div className="flex flex-col gap-3">
              <Controller
                name="analysts"
                control={control}
                rules={{ validate: (v) => v.length > 0 || "Select at least one analyst" }}
                render={({ field }) => (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {activeAnalysts.map((a) => {
                      const isChecked = field.value.includes(a);
                      const details = ANALYST_DETAILS[a] || {
                        label: a.replace(/_/g, " ").replace(/\bcrypto\b/i, "").trim() || a,
                        desc: "Analyzes specific telemetry and submits independent reports.",
                        icon: (
                          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                          </svg>
                        ),
                      };
                      return (
                        <label
                          key={a}
                          className={cn(
                            "flex items-start gap-3.5 p-4 rounded-[calc(var(--radius)*1.4)] border text-left cursor-pointer transition-all active:scale-[0.98] select-none",
                            isChecked
                              ? "bg-primary/10 border-primary/40 shadow-md shadow-primary/5 text-foreground"
                              : "bg-card/45 border-border/50 text-muted-foreground hover:bg-muted/15"
                          )}
                        >
                          <div className="flex items-center h-5">
                            <Checkbox
                              checked={isChecked}
                              onCheckedChange={(checked) => {
                                const next = checked
                                  ? [...field.value, a]
                                  : field.value.filter((v: string) => v !== a);
                                field.onChange(next);
                              }}
                            />
                          </div>
                          <div className="space-y-1">
                            <div className="flex items-center gap-2 font-bold text-sm text-foreground">
                              <span className={cn("shrink-0", isChecked ? "text-primary" : "text-muted-foreground")}>
                                {details.icon}
                              </span>
                              {details.label}
                            </div>
                            <p className="text-xs text-muted-foreground/80 leading-relaxed font-medium">
                              {details.desc}
                            </p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              />
            </div>
            {errors.analysts && (
              <p className="text-xs text-destructive font-semibold">{errors.analysts.message}</p>
            )}

            {/* Research Depth & Report Language */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-3 border-t border-border/10">
              {/* Research Depth */}
              <div className="flex flex-col gap-2 bg-muted/15 border border-border/30 rounded-xl p-4">
                <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Debate / Research Depth</Label>
                <Controller
                  name="research_depth"
                  control={control}
                  render={({ field }) => (
                    <div className="flex items-center gap-4 mt-2">
                      <input
                        type="range"
                        min={1}
                        max={5}
                        value={field.value}
                        onChange={(e) => field.onChange(Number(e.target.value))}
                        className="flex-1 accent-primary h-1.5 bg-muted-foreground/20 rounded-lg appearance-none cursor-pointer"
                      />
                      <span className="w-8 text-center font-mono font-extrabold text-base text-primary bg-primary/10 rounded-md py-0.5">{field.value}</span>
                    </div>
                  )}
                />
                <p className="text-[10px] text-muted-foreground font-medium mt-1">Controls length & iterations of source queries (1 = Light, 5 = Max depth)</p>
              </div>

              {/* Output Language */}
              <div className="flex flex-col gap-2 justify-center">
                <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Report Language</Label>
                <Controller
                  name="output_language"
                  control={control}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger className="h-10 bg-card"><SelectValue placeholder="English" /></SelectTrigger>
                      <SelectContent>
                        {LANGUAGES.map((l) => (
                          <SelectItem key={l} value={l}>{l}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                <p className="text-[10px] text-muted-foreground font-medium pl-1">Final output delivery language (agent logs remain in English)</p>
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Engine Settings & Deploy */}
        {(step === 3 || isTest) && (
          <div className="space-y-6 animate-fade-in">
            {/* LLM Options Panel */}
            <div className="glass-card border border-border/50 rounded-2xl bg-card/65 p-5 space-y-4.5">
              <div className="border-b border-border/40 pb-4">
                <h2 className="text-base font-bold flex items-center gap-2 text-foreground">
                  <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  Model & Engine Presets
                </h2>
              </div>

              {/* Provider */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="provider" className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Default LLM Provider</Label>
                <Controller
                  name="provider"
                  control={control}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="provider" className="h-10 bg-card"><SelectValue placeholder="Select provider" /></SelectTrigger>
                      <SelectContent>
                        {PROVIDERS.map((p) => (
                          <SelectItem key={p} value={p} className="capitalize">
                            {p}{p === envProvider && <span className="ml-1 text-muted-foreground text-xs">(env default)</span>}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                <p className="text-xs text-muted-foreground font-medium pl-1">
                  Root engine provider for core reasoning tasks.
                  {envProvider !== "openai" && <span className="ml-1.5 text-primary font-bold">(Fallback: {envProvider})</span>}
                </p>
              </div>

              {/* LLM Models Selection */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-1">
                <div className="flex flex-col gap-2">
                  <Label className="font-semibold text-xs text-foreground/80">Deep Reasoning LLM</Label>
                  <Controller
                    name="deep_think_llm"
                    control={control}
                    render={({ field }) =>
                      deepOptions.length > 0 ? (
                        <ModelSelect
                          options={deepOptions}
                          value={field.value}
                          onChange={field.onChange}
                          placeholder={envDeepThink || "Select model"}
                        />
                      ) : (
                        <Input placeholder={envDeepThink || "e.g. gpt-4o"} className="font-mono text-sm h-10 bg-card" value={field.value} onChange={field.onChange} />
                      )
                    }
                  />
                  <p className="text-[10px] text-muted-foreground leading-normal mt-0.5">
                    Model dedicated to complex synthesis and debate rounds.
                    {envDeepThink && <span className="block font-semibold text-primary/75 mt-0.5">Env value: {envDeepThink}</span>}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-semibold text-xs text-foreground/80">Quick Intuition LLM</Label>
                  <Controller
                    name="quick_think_llm"
                    control={control}
                    render={({ field }) =>
                      quickOptions.length > 0 ? (
                        <ModelSelect
                          options={quickOptions}
                          value={field.value}
                          onChange={field.onChange}
                          placeholder={envQuickThink || "Select model"}
                        />
                      ) : (
                        <Input placeholder={envQuickThink || "e.g. gpt-4o-mini"} className="font-mono text-sm h-10 bg-card" value={field.value} onChange={field.onChange} />
                      )
                    }
                  />
                  <p className="text-[10px] text-muted-foreground leading-normal mt-0.5">
                    Model dedicated to high-speed summarization & sub-tasks.
                    {envQuickThink && <span className="block font-semibold text-primary/75 mt-0.5">Env value: {envQuickThink}</span>}
                  </p>
                </div>
              </div>
            </div>

            {/* Custom LLM API & Proxy Settings */}
            <div className="glass-card border border-border/50 rounded-2xl overflow-hidden bg-card/65">
              <div className="px-5 py-4">
                <SectionToggle
                  label="LLM & Proxy Settings"
                  open={showLLM}
                  onToggle={() => setShowLLM(!showLLM)}
                  badge={backendConn.status === "ok" ? "Connected" : envBackendUrl ? "Proxy configured" : undefined}
                />
                {showLLM && (
                  <div className="mt-5 space-y-5 pl-1 border-t border-border/30 pt-5 animate-fade-in">
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="backend_url" className="font-semibold text-xs text-foreground/80 flex items-center gap-2">
                        Backend URL / Custom API Base
                        <ConnBadge status={backendConn.status} latency={backendConn.latency} error={backendConn.errorMsg} />
                      </Label>
                      <div ref={endpointsRef} className="relative">
                        <div className="relative">
                          <Input
                            id="backend_url"
                            placeholder="e.g. http://localhost:8000/v1 or custom proxy url"
                            className="font-mono text-sm pr-9 placeholder:text-muted-foreground/30 bg-card h-10"
                            autoComplete="off"
                            {...register("backend_url")}
                            onFocus={() => endpoints.length > 1 && setShowEndpoints(true)}
                          />
                          {endpoints.length > 1 && (
                            <button
                              type="button"
                              onClick={() => setShowEndpoints(!showEndpoints)}
                              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg hover:bg-muted transition-colors cursor-pointer"
                            >
                              <svg className={`w-4 h-4 text-muted-foreground transition-transform ${showEndpoints ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                              </svg>
                            </button>
                          )}
                        </div>
                        {showEndpoints && endpoints.length > 1 && (
                          <div className="absolute z-50 mt-1.5 w-full rounded-xl border border-border/80 bg-popover shadow-xl overflow-hidden max-h-48 overflow-y-auto backdrop-blur-md">
                            {endpoints.map((ep) => (
                              <div
                                key={ep.url}
                                className={`flex items-center justify-between px-4 py-2.5 text-xs cursor-pointer hover:bg-muted transition-colors ${ep.url === watchedBackendUrl ? "bg-primary/10 text-primary font-bold" : ""}`}
                              >
                                <button
                                  type="button"
                                  className="flex-1 text-left truncate font-mono text-[11px]"
                                  onClick={() => selectEndpoint(ep)}
                                >
                                  {ep.url}
                                  {ep.deepModel && <span className="ml-2 text-muted-foreground/75 text-[10px]">({ep.deepModel})</span>}
                                </button>
                                {ep.url !== watchedBackendUrl && (
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); deleteEndpoint(ep.url); }}
                                    className="ml-2 p-1 rounded-md hover:bg-destructive/20 text-muted-foreground hover:text-destructive transition-colors shrink-0 cursor-pointer"
                                  >
                                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <p className="text-[10px] text-muted-foreground pl-1 mt-0.5">
                        Optional proxy host override. Models will query <code className="px-1 py-0.5 rounded bg-muted font-bold text-[10px]">/v1/models</code> automatically.
                        {modelsLoading && <span className="ml-1.5 text-primary font-semibold">Listing models...</span>}
                        {!modelsLoading && proxyModels && <span className="ml-1.5 text-primary font-bold">{proxyModels.length} models fetched</span>}
                        {modelsError && <span className="ml-1.5 text-destructive font-semibold">Failed querying endpoint</span>}
                        {envBackendUrl && <span className="block mt-1 text-primary/75 font-semibold">Environment preset: {envBackendUrl}</span>}
                      </p>
                    </div>

                    <div className="flex flex-col gap-2">
                      <Label htmlFor="llm_api_key" className="font-semibold text-xs text-foreground/80 flex items-center gap-2">
                        Custom Provider API Key
                        {watchedApiKey?.trim() && <ConnBadge status={backendConn.status} latency={null} error={backendConn.errorMsg} label="Key active" />}
                      </Label>
                      <Input
                        id="llm_api_key"
                        type="password"
                        placeholder="API key override (stored locally)"
                        className="font-mono text-sm bg-card h-10"
                        {...register("llm_api_key")}
                      />
                      <p className="text-[10px] text-muted-foreground pl-1">
                        API key credentials for the selected provider (replaces environment variable).
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Advanced Workflow Configuration */}
            <div className="glass-card border border-border/50 rounded-2xl overflow-hidden bg-card/65">
              <div className="px-5 py-4">
                <SectionToggle label="Advanced Workflow Configuration" open={showWorkflow} onToggle={() => setShowWorkflow(!showWorkflow)} />
                {showWorkflow && (
                  <div className="mt-5 space-y-5 pl-1 border-t border-border/30 pt-5 animate-fade-in">
                    <div className={`grid ${watchedWorkflowMode === "quick_trade" ? "grid-cols-1" : "grid-cols-2"} gap-5`}>
                      <div className="flex flex-col gap-2">
                        <Label className="font-semibold text-xs text-foreground/80">Max Debate Rounds</Label>
                        <Input type="number" min={1} max={10} className="bg-card h-10 font-mono" {...register("max_debate_rounds", { valueAsNumber: true })} />
                        <p className="text-[10px] text-muted-foreground leading-normal">Maximum rounds of analyst cross-examinations</p>
                      </div>
                      {watchedWorkflowMode !== "quick_trade" && (
                        <div className="flex flex-col gap-2">
                          <Label className="font-semibold text-xs text-foreground/80">Max Risk Discussion Rounds</Label>
                          <Input type="number" min={1} max={10} className="bg-card h-10 font-mono" {...register("max_risk_discuss_rounds", { valueAsNumber: true })} />
                          <p className="text-[10px] text-muted-foreground leading-normal">Maximum rounds of compliance & sizing reviews</p>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="font-semibold text-xs text-foreground/80">Max Execution Step Limit</Label>
                      <Input type="number" min={10} max={500} className="bg-card h-10 font-mono" {...register("max_recur_limit", { valueAsNumber: true })} />
                      <p className="text-[10px] text-muted-foreground leading-normal">Upper boundary on total graph state recursion cycles</p>
                    </div>
                    <div className="flex items-center gap-3.5 bg-muted/20 border border-border/30 rounded-xl p-4 mt-2">
                      <Controller
                        name="checkpoint_enabled"
                        control={control}
                        render={({ field }) => (
                          <Checkbox checked={field.value} onCheckedChange={field.onChange} id="checkpoint" />
                        )}
                      />
                      <div>
                        <Label htmlFor="checkpoint" className="font-bold text-sm cursor-pointer select-none">Enable Resilient State Checkpointing</Label>
                        <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">Saves step-wise run context to DB allowing recovery/resumption after connection or proxy timeouts.</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Agent Model Overrides */}
            <div className="glass-card border border-border/50 rounded-2xl bg-card/65 p-5">
              <AgentModelOverrides
                assetType={isCrypto ? "crypto" : "stock"}
                modelOptions={deepOptions}
                overrides={agentModelOverrides}
                onChange={setAgentModelOverrides}
              />
            </div>

            {/* Market Data Feeds Overrides (Stock only) */}
            {!isCrypto && (
              <div className="glass-card border border-border/50 rounded-2xl overflow-hidden bg-card/65">
                <div className="px-5 py-4">
                  <SectionToggle label="Market Data Feeds Overrides" open={showData} onToggle={() => setShowData(!showData)} />
                  {showData && (
                    <div className="mt-5 space-y-4 pl-1 border-t border-border/30 pt-5 animate-fade-in">
                      {(
                        [
                          ["data_vendor_core", "Core Stock Pricing API"],
                          ["data_vendor_technical", "Technical Indicators Math Feed"],
                          ["data_vendor_fundamental", "Fundamental Statements Feed"],
                          ["data_vendor_news", "Financial Sentiment News Feed"],
                        ] as const
                      ).map(([name, label]) => (
                        <div key={name} className="flex flex-col gap-2">
                          <Label className="font-semibold text-xs text-foreground/80">{label}</Label>
                          <Controller
                            name={name}
                            control={control}
                            render={({ field }) => (
                              <Select value={field.value} onValueChange={field.onChange}>
                                <SelectTrigger className="text-sm h-10 bg-card"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                  {VENDOR_OPTIONS.map((v) => (
                                    <SelectItem key={v} value={v} className="text-sm">{v}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            )}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Submit Error ── */}
        {submitError && (
          <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive flex items-start gap-2.5 animate-pulse-slow animate-fade-in" role="alert">
            <svg className="w-5 h-5 shrink-0 mt-0.5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="font-semibold">{submitError}</div>
          </div>
        )}

        {/* Wizard Footer Controls */}
        <div className="flex gap-4 items-center justify-end mt-4">
          {(step > 1 && !isTest) && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setStep((prev) => (prev - 1) as 1 | 2 | 3)}
              className="px-5 h-10 rounded-xl font-bold uppercase tracking-wider text-xs border-border/50 hover:bg-muted/10 cursor-pointer active:scale-95 transition-all"
            >
              Back
            </Button>
          )}
          {(step < 3 && !isTest) ? (
            <Button
              type="button"
              onClick={async () => {
                if (step === 1) {
                  const isValid = await trigger(["ticker", "analysis_date"]);
                  if (isValid) setStep(2);
                } else if (step === 2) {
                  const isValid = await trigger(["analysts"]);
                  if (isValid) setStep(3);
                }
              }}
              className="flex-1 h-10 rounded-xl font-bold uppercase tracking-wider text-xs cursor-pointer active:scale-95 transition-all hover:scale-[1.01] shadow-lg shadow-primary/10"
            >
              Continue
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 font-bold h-10 rounded-xl text-xs uppercase tracking-wider transition-all duration-300 hover:scale-[1.01] active:scale-[0.98] cursor-pointer shadow-lg shadow-primary/15 flex items-center justify-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <svg className="w-4 h-4 animate-spin text-current" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Starting...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 text-current" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Start Analysis Engine
                </>
              )}
            </Button>
          )}
          {(step === 1 || isTest) && (
            <Button
              type="button"
              variant="outline"
              className="h-10 px-5 rounded-xl font-bold uppercase tracking-wider text-xs border-border/50 hover:bg-muted/10 cursor-pointer active:scale-95 transition-all"
              onClick={() => navigate({ to: "/" })}
            >
              Cancel
            </Button>
          )}
        </div>
      </form>

      <WatchlistPanel
        config={{
          asset_type: watchedAssetType,
          analysis_date: watch("analysis_date"),
          provider: selectedProvider,
          llm_api_key: watchedApiKey,
          deep_think_llm: watchedDeep,
          quick_think_llm: watchedQuick,
          backend_url: watchedBackendUrl,
          analysts: watchedAnalysts,
          research_depth: watchedDepth,
          output_language: watchedLang,
          interval: watchedInterval,
          data_vendors: isCrypto ? undefined : {
            core_stock_apis: watchedVendorCore,
            technical_indicators: watchedVendorTech,
            fundamental_data: watchedVendorFund,
            news_data: watchedVendorNews,
          },
          agent_model_overrides: (() => {
            const filtered = filterOverridesForAssetType(agentModelOverrides, watchedAssetType);
            return Object.keys(filtered).length > 0 ? filtered : undefined;
          })(),
        }}
      />
    </div>
  );
}
