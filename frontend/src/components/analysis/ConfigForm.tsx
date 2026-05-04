import { useState, useMemo, useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { apiClient, type StartAnalysisRequest, type AssetType, type CryptoInterval } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Combobox } from "@/components/ui/combobox";
import { useModels } from "@/hooks/useModels";
import { useSymbols } from "@/hooks/useSymbols";
import { useConnectivityCheck, type ConnStatus } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";
import { WatchlistPanel } from "./WatchlistPanel";

const TICKER_REGEX = /^[A-Z0-9.\-^]{1,15}$/;
const CRYPTO_TICKER_REGEX = /^[A-Z0-9]{2,20}$/;
const PROVIDERS = ["openai", "anthropic", "google", "deepseek", "xai", "qwen", "glm", "openrouter", "azure", "ollama"] as const;
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

function ConnBadge({ status, latency, error, label = "Connected" }: { status: ConnStatus; latency: number | null; error: string | null; label?: string }) {
  if (status === "idle") return null;
  if (status === "checking") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
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
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        {label}{latency != null && ` (${latency}ms)`}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-destructive font-medium">
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      {error || "Unreachable"}
    </span>
  );
}

function SectionToggle({ label, open, onToggle, badge }: { label: string; open: boolean; onToggle: () => void; badge?: string }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
    >
      <svg className={`w-4 h-4 transition-transform duration-200 ${open ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
      </svg>
      {label}
      {badge && (
        <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">{badge}</span>
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
}

export function ConfigForm() {
  const navigate = useNavigate();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const saved = useMemo(() => loadSettings(), []);

  const [showLLM, setShowLLM] = useState(!!(saved.llm_api_key || saved.backend_url || saved.deep_think_llm || saved.quick_think_llm));
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [showData, setShowData] = useState(false);

  const { data: configData } = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 60_000,
  });

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
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      asset_type: saved.asset_type || "stock",
      ticker: "",
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
    },
  });

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
  const watchedVendorCore = watch("data_vendor_core");
  const watchedVendorTech = watch("data_vendor_technical");
  const watchedVendorFund = watch("data_vendor_fundamental");
  const watchedVendorNews = watch("data_vendor_news");

  const isCrypto = watchedAssetType === "crypto";
  const activeAnalysts = isCrypto ? CRYPTO_ANALYSTS : STOCK_ANALYSTS;
  const { data: cryptoSymbols = [], isLoading: symbolsLoading } = useSymbols(watchedAssetType);

  useEffect(() => {
    saveSettings({
      asset_type: watchedAssetType,
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
    });
  }, [watchedAssetType, selectedProvider, watchedApiKey, watchedBackendUrl, watchedDeep, watchedQuick, watchedAnalysts, watchedDepth, watchedLang, watchedDebate, watchedRisk, watchedRecur, watchedCheckpoint, watchedInterval, watchedVendorCore, watchedVendorTech, watchedVendorFund, watchedVendorNews]);

  const trimmedBackendUrl = useMemo(() => watchedBackendUrl?.trim() || undefined, [watchedBackendUrl]);
  const { data: proxyModels, isLoading: modelsLoading, isError: modelsError } = useModels(trimmedBackendUrl, watchedApiKey?.trim() || undefined);
  const backendConn = useConnectivityCheck(trimmedBackendUrl, watchedApiKey?.trim() || undefined);

  const deepOptions = useMemo(() => {
    if (proxyModels?.length) return proxyModels.map((m) => ({ label: m.name ?? m.id, value: m.id }));
    return getModelOptions(selectedProvider, "deep");
  }, [proxyModels, selectedProvider]);

  const quickOptions = useMemo(() => {
    if (proxyModels?.length) return proxyModels.map((m) => ({ label: m.name ?? m.id, value: m.id }));
    return getModelOptions(selectedProvider, "quick");
  }, [proxyModels, selectedProvider]);

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
        max_debate_rounds: data.max_debate_rounds !== 1 ? data.max_debate_rounds : undefined,
        max_risk_discuss_rounds: data.max_risk_discuss_rounds !== 1 ? data.max_risk_discuss_rounds : undefined,
        max_recur_limit: data.max_recur_limit !== 100 ? data.max_recur_limit : undefined,
        checkpoint_enabled: data.checkpoint_enabled || undefined,
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
      };
      const result = await apiClient.startAnalysis(body);
      navigate({ to: "/analysis/$runId", params: { runId: result.run_id } });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">New Analysis</h1>
        <p className="text-muted-foreground mt-1">Configure and start a new multi-agent trading analysis.</p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
        {/* ── Core Settings ── */}
        <Card className="shadow-sm">
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
              Core Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {/* Asset Type Toggle */}
            <div className="flex flex-col gap-2">
              <Label className="font-medium">Asset Type</Label>
              <Controller
                name="asset_type"
                control={control}
                render={({ field }) => (
                  <div className="flex rounded-lg border overflow-hidden" role="radiogroup" aria-label="Asset type">
                    {(["stock", "crypto"] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        role="radio"
                        aria-checked={field.value === t}
                        className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
                          field.value === t
                            ? "bg-primary text-primary-foreground"
                            : "bg-background hover:bg-muted"
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

            {/* Ticker */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="ticker" className="font-medium">{isCrypto ? "Trading Pair" : "Ticker Symbol"}</Label>
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
                      placeholder="Search Bybit pairs..."
                      loading={symbolsLoading}
                      className="font-mono text-base tracking-wide"
                    />
                  )}
                />
              ) : (
                <Input
                  id="ticker"
                  placeholder="e.g. AAPL, SPY, TSLA"
                  className="font-mono text-base tracking-wide"
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
                <p className="text-sm text-destructive">{errors.ticker.message}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {isCrypto ? "Bybit perpetual futures pair" : "Enter the stock ticker symbol to analyze"}
                </p>
              )}
            </div>

            {/* Date */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="analysis_date" className="font-medium">Analysis Date</Label>
              <Input
                id="analysis_date"
                type="date"
                max={new Date().toISOString().split("T")[0]}
                aria-invalid={!!errors.analysis_date}
                {...register("analysis_date", {
                  required: "Date is required",
                  validate: (v) => v <= new Date().toISOString().split("T")[0] || "Date cannot be in the future",
                })}
              />
              {errors.analysis_date ? (
                <p className="text-sm text-destructive">{errors.analysis_date.message}</p>
              ) : (
                <p className="text-xs text-muted-foreground">Historical date for the analysis</p>
              )}
            </div>

            {/* Provider */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="provider" className="font-medium">LLM Provider</Label>
              <Controller
                name="provider"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="provider"><SelectValue placeholder="Select provider" /></SelectTrigger>
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
              <p className="text-xs text-muted-foreground">
                AI provider for agent reasoning
                {envProvider !== "openai" && <span className="ml-1 text-primary font-medium">(env: {envProvider})</span>}
              </p>
            </div>

            {/* Analyst Team */}
            <div className="flex flex-col gap-2">
              <Label className="font-medium">Analyst Team</Label>
              <div className="flex flex-wrap gap-4">
                <Controller
                  name="analysts"
                  control={control}
                  rules={{ validate: (v) => v.length > 0 || "Select at least one analyst" }}
                  render={({ field }) => (
                    <>
                      {activeAnalysts.map((a) => (
                        <label key={a} className="flex items-center gap-2 text-sm cursor-pointer">
                          <Checkbox
                            checked={field.value.includes(a)}
                            onCheckedChange={(checked) => {
                              const next = checked
                                ? [...field.value, a]
                                : field.value.filter((v: string) => v !== a);
                              field.onChange(next);
                            }}
                          />
                          {a.replace(/_/g, " ").replace(/\bcrypto\b/i, "").trim() || a}
                        </label>
                      ))}
                    </>
                  )}
                />
              </div>
              <p className="text-xs text-muted-foreground">Select which analyst agents to include ({watchedAnalysts.length}/{activeAnalysts.length})</p>
              {errors.analysts && (
                <p className="text-sm text-destructive">{errors.analysts.message}</p>
              )}
            </div>

            {/* Research Depth */}
            <div className="flex flex-col gap-2">
              <Label className="font-medium">Research Depth</Label>
              <Controller
                name="research_depth"
                control={control}
                render={({ field }) => (
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={1}
                      max={5}
                      value={field.value}
                      onChange={(e) => field.onChange(Number(e.target.value))}
                      className="flex-1 accent-primary"
                    />
                    <span className="w-8 text-center font-mono font-bold text-sm">{field.value}</span>
                  </div>
                )}
              />
              <p className="text-xs text-muted-foreground">1 = Quick scan, 5 = Deep analysis</p>
            </div>

            {/* Output Language */}
            <div className="flex flex-col gap-2">
              <Label className="font-medium">Output Language</Label>
              <Controller
                name="output_language"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger><SelectValue placeholder="English" /></SelectTrigger>
                    <SelectContent>
                      {LANGUAGES.map((l) => (
                        <SelectItem key={l} value={l}>{l}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              <p className="text-xs text-muted-foreground">Language for the final report (agent debate stays in English)</p>
            </div>

            {/* Crypto Interval — only for crypto */}
            {isCrypto && (
              <div className="flex flex-col gap-2">
                <Label className="font-medium">Kline Interval</Label>
                <Controller
                  name="interval"
                  control={control}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger><SelectValue placeholder="Select interval" /></SelectTrigger>
                      <SelectContent>
                        {CRYPTO_INTERVALS.map((i) => (
                          <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                <p className="text-xs text-muted-foreground">Candlestick interval for technical analysis</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Workflow Settings ── */}
        <Card className="shadow-sm">
          <CardContent className="pt-5">
            <SectionToggle label="Workflow Settings" open={showWorkflow} onToggle={() => setShowWorkflow(!showWorkflow)} />
            {showWorkflow && (
              <div className="mt-4 space-y-4 pl-1">
                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium text-sm">Max Debate Rounds</Label>
                    <Input type="number" min={1} max={10} {...register("max_debate_rounds", { valueAsNumber: true })} />
                    <p className="text-xs text-muted-foreground">Bull vs Bear debate iterations</p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label className="font-medium text-sm">Max Risk Rounds</Label>
                    <Input type="number" min={1} max={10} {...register("max_risk_discuss_rounds", { valueAsNumber: true })} />
                    <p className="text-xs text-muted-foreground">Risk team discussion iterations</p>
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <Label className="font-medium text-sm">Max Recursion Limit</Label>
                  <Input type="number" min={10} max={500} {...register("max_recur_limit", { valueAsNumber: true })} />
                  <p className="text-xs text-muted-foreground">Upper bound on LangGraph recursion steps</p>
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <Controller
                    name="checkpoint_enabled"
                    control={control}
                    render={({ field }) => (
                      <Checkbox checked={field.value} onCheckedChange={field.onChange} id="checkpoint" />
                    )}
                  />
                  <div>
                    <Label htmlFor="checkpoint" className="font-medium text-sm cursor-pointer">Enable Checkpoints</Label>
                    <p className="text-xs text-muted-foreground">Save state after each step so crashed runs can resume</p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── LLM & Proxy Settings ── */}
        <Card className="shadow-sm">
          <CardContent className="pt-5">
            <SectionToggle
              label="LLM & Proxy Settings"
              open={showLLM}
              onToggle={() => setShowLLM(!showLLM)}
              badge={backendConn.status === "ok" ? "Connected" : envBackendUrl ? "Custom endpoint" : undefined}
            />
            {showLLM && (
              <div className="mt-4 space-y-4 pl-1">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="backend_url" className="font-medium text-sm flex items-center gap-2">
                    Backend URL / Proxy Endpoint
                    <ConnBadge status={backendConn.status} latency={backendConn.latency} error={backendConn.errorMsg} />
                  </Label>
                  <Input id="backend_url" placeholder={envBackendUrl || "http://localhost:4141"} className="font-mono text-sm" {...register("backend_url")} />
                  <p className="text-xs text-muted-foreground">
                    Custom API endpoint. Models are fetched from <code className="px-1 py-0.5 rounded bg-muted">/v1/models</code> automatically.
                    {modelsLoading && <span className="ml-1 text-primary font-medium">Loading models...</span>}
                    {!modelsLoading && proxyModels && <span className="ml-1 text-primary font-medium">{proxyModels.length} models loaded</span>}
                    {modelsError && <span className="ml-1 text-destructive font-medium">Could not fetch models</span>}
                    {envBackendUrl && <span className="block mt-0.5 text-primary font-medium">Env default: {envBackendUrl}</span>}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label htmlFor="llm_api_key" className="font-medium text-sm flex items-center gap-2">
                    API Key
                    {watchedApiKey?.trim() && <ConnBadge status={backendConn.status} latency={null} error={backendConn.errorMsg} label="Authenticated" />}
                  </Label>
                  <Input
                    id="llm_api_key"
                    type="password"
                    placeholder="Provider API key (overrides env var)"
                    className="font-mono text-sm"
                    {...register("llm_api_key")}
                  />
                  <p className="text-xs text-muted-foreground">
                    Optional. Overrides the environment variable for the selected provider.
                    Useful for Anthropic-compatible endpoints like MiniMax.
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-medium text-sm">Deep Think Model</Label>
                  <Controller
                    name="deep_think_llm"
                    control={control}
                    render={({ field }) =>
                      deepOptions.length > 0 ? (
                        <Select value={field.value} onValueChange={field.onChange}>
                          <SelectTrigger className="font-mono text-sm"><SelectValue placeholder={envDeepThink || "Select model"} /></SelectTrigger>
                          <SelectContent className="min-w-[28rem] max-h-72">
                            {deepOptions.map((m) => (
                              <SelectItem key={m.value} value={m.value} className="font-mono text-sm">{m.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input placeholder={envDeepThink || "e.g. claude-opus-4-6"} className="font-mono text-sm" value={field.value} onChange={field.onChange} />
                      )
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Model for complex reasoning tasks.
                    {envDeepThink && <span className="ml-1 text-primary font-medium">(env: {envDeepThink})</span>}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="font-medium text-sm">Quick Think Model</Label>
                  <Controller
                    name="quick_think_llm"
                    control={control}
                    render={({ field }) =>
                      quickOptions.length > 0 ? (
                        <Select value={field.value} onValueChange={field.onChange}>
                          <SelectTrigger className="font-mono text-sm"><SelectValue placeholder={envQuickThink || "Select model"} /></SelectTrigger>
                          <SelectContent className="min-w-[28rem] max-h-72">
                            {quickOptions.map((m) => (
                              <SelectItem key={m.value} value={m.value} className="font-mono text-sm">{m.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input placeholder={envQuickThink || "e.g. claude-sonnet-4-6"} className="font-mono text-sm" value={field.value} onChange={field.onChange} />
                      )
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Model for fast, lightweight tasks.
                    {envQuickThink && <span className="ml-1 text-primary font-medium">(env: {envQuickThink})</span>}
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Data Sources (stock only) ── */}
        {!isCrypto && (
        <Card className="shadow-sm">
          <CardContent className="pt-5">
            <SectionToggle label="Data Sources" open={showData} onToggle={() => setShowData(!showData)} />
            {showData && (
              <div className="mt-4 space-y-4 pl-1">
                {(
                  [
                    ["data_vendor_core", "Core Stock APIs", "core_stock_apis"],
                    ["data_vendor_technical", "Technical Indicators", "technical_indicators"],
                    ["data_vendor_fundamental", "Fundamental Data", "fundamental_data"],
                    ["data_vendor_news", "News Data", "news_data"],
                  ] as const
                ).map(([name, label]) => (
                  <div key={name} className="flex flex-col gap-2">
                    <Label className="font-medium text-sm">{label}</Label>
                    <Controller
                      name={name}
                      control={control}
                      render={({ field }) => (
                        <Select value={field.value} onValueChange={field.onChange}>
                          <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
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
          </CardContent>
        </Card>
        )}

        {/* ── Submit ── */}
        {submitError && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive flex items-start gap-2" role="alert">
            <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {submitError}
          </div>
        )}

        <div className="flex gap-3">
          <Button type="submit" disabled={isSubmitting} className="flex-1 font-medium">
            {isSubmitting ? (
              <>
                <svg className="w-4 h-4 mr-2 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Starting...
              </>
            ) : (
              <>
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Start Analysis
              </>
            )}
          </Button>
          <Button type="button" variant="outline" onClick={() => navigate({ to: "/" })}>Cancel</Button>
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
        }}
      />
    </div>
  );
}
