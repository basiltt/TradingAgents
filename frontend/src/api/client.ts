const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const DEFAULT_HEADERS: HeadersInit = {
  "X-Requested-With": "XMLHttpRequest",
};

async function throwApiError(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      detail = body.detail
        .map((e: { loc?: string[]; msg?: string }) =>
          `${(e.loc ?? []).slice(-1).join(".")}: ${e.msg ?? "invalid"}`
        )
        .join("; ");
    } else if (body.detail != null) {
      detail = JSON.stringify(body.detail);
    }
  } catch {
    // non-JSON error body
  }
  throw new ApiError(res.status, detail);
}

const _DEFAULT_TIMEOUT = 30_000;

async function request<T>(
  path: string,
  init?: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    signal: signal ?? init?.signal ?? AbortSignal.timeout(_DEFAULT_TIMEOUT),
    headers: { ...DEFAULT_HEADERS, ...init?.headers },
  });
  if (!res.ok) return throwApiError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function requestText(
  path: string,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: DEFAULT_HEADERS,
    signal: signal ?? AbortSignal.timeout(_DEFAULT_TIMEOUT),
  });
  if (!res.ok) return throwApiError(res);
  return res.text();
}

function mutate<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method,
    headers: { ...DEFAULT_HEADERS, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }, signal);
}

export interface HealthResponse {
  status: string;
  db: string;
}

export type AssetType = "stock" | "crypto";

export interface AnalysisListItem {
  run_id: string;
  ticker: string;
  analysis_date: string;
  status: string;
  started_at: string;
  completed_at?: string;
  asset_type?: AssetType;
  config?: Record<string, unknown>;
}

export interface AnalysisListResponse {
  items: AnalysisListItem[];
  total: number;
  page: number;
  limit: number;
}

export interface AnalysisRun {
  run_id: string;
  ticker: string;
  analysis_date: string;
  status: string;
  config: Record<string, unknown>;
  started_at: string;
  completed_at?: string;
  error?: string;
  asset_type?: AssetType;
}

export interface AnalysisCreateResponse {
  run_id: string;
  status: string;
}

export type CryptoInterval = "15" | "60" | "240" | "D";

export interface StartAnalysisRequest {
  ticker: string;
  analysis_date: string;
  provider?: string;
  llm_api_key?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  backend_url?: string;
  analysts?: string[];
  research_depth?: number;
  output_language?: string;
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  max_recur_limit?: number;
  checkpoint_enabled?: boolean;
  data_vendors?: Record<string, string>;
  asset_type?: AssetType;
  interval?: CryptoInterval;
  workflow_mode?: "quick_trade" | "deep_analysis";
  agent_model_overrides?: Record<string, string>;
  ta_prefilter_enabled?: boolean;
  ta_prefilter_threshold?: number;
}

export interface ConfigResponse {
  defaults: Record<string, unknown>;
  overrides: Record<string, unknown>;
  resolved: Record<string, unknown>;
}

export interface MemoryEntry {
  ticker: string;
  date: string;
  decision: string;
  confidence: string;
  status: string;
  reasoning?: string;
}

export interface MemoryListResponse {
  items: MemoryEntry[];
  total: number;
  page: number;
  limit: number;
}

export interface CheckpointResponse {
  exists: boolean;
  ticker?: string;
  date?: string;
}

export interface AnalysisSnapshot {
  agents: Record<string, string>;
  messages: Array<{ sender: string; content: string; seq: number }>;
  stats: { tokens_in: number; tokens_out: number; llm_calls: number; tool_calls: number } | null;
  reports: Record<string, string>;
}

export interface ScanRequest {
  analysis_date: string;
  asset_type?: AssetType;
  interval?: CryptoInterval;
  provider?: string;
  llm_api_key?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  backend_url?: string;
  analysts?: string[];
  research_depth?: number;
  output_language?: string;
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  max_recur_limit?: number;
  checkpoint_enabled?: boolean;
  data_vendors?: Record<string, string>;
  max_parallel?: number;
  workflow_mode?: "quick_trade" | "deep_analysis";
  agent_model_overrides?: Record<string, string>;
  ta_prefilter_enabled?: boolean;
  ta_prefilter_threshold?: number;
}

export interface ScanResultItem {
  ticker: string;
  run_id: string | null;
  status: string;
  direction: string;
  confidence: string;
  score: number;
  decision_summary: string;
}

export interface ScanStatus {
  scan_id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  current_batch: number;
  total_batches: number;
  current_tickers: string[];
  results: ScanResultItem[];
  direction_counts?: Record<string, number>;
  started_at: string;
  completed_at: string | null;
  interval?: string;
  asset_type?: string;
  provider?: string;
  workflow_mode?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  backend_url?: string;
  research_depth?: number;
  max_debate_rounds?: number;
}

export type StrategyCategory = "scalping" | "intraday" | "swing" | "positional" | "grid" | "dca" | "hedging" | "arbitrage";
export type StrategyStatus = "active" | "paused" | "archived" | "draft";

export interface StrategyConfig {
  trading_mode?: string;
  asset_whitelist?: string[];
  asset_blacklist?: string[];
  signal_adherence?: string;
  trade_directionality?: string;
  signal_confirmations?: string[];
  order_type?: string;
  slippage_tolerance?: number;
  partial_fills?: boolean;
  max_spread?: number;
  capital_allocation_mode?: string;
  base_capital_pct?: number;
  absolute_position_size?: number;
  position_sizing_method?: string;
  compounding_enabled?: boolean;
  leverage_multiplier?: number;
  max_leverage_cap?: number;
  max_global_exposure_pct?: number;
  max_simultaneous_trades?: number;
  max_exposure_per_asset?: number;
  risk_per_trade_pct?: number;
  risk_per_trade_amount?: number;
  global_drawdown_limit_pct?: number;
  daily_drawdown_limit_pct?: number;
  weekly_drawdown_limit_pct?: number;
  equity_protection_threshold?: number;
  sl_type?: string;
  sl_value?: number;
  sl_leverage_adjusted?: boolean;
  breakeven_trigger_pct?: number;
  trailing_sl_activation_pct?: number;
  trailing_sl_distance_pct?: number;
  multi_sl_enabled?: boolean;
  multi_sl_levels?: Array<{ pct: number; weight: number }>;
  multi_sl_distribution?: string;
  tp_type?: string;
  tp_value?: number;
  multi_tp_enabled?: boolean;
  multi_tp_levels?: Array<{ pct: number; weight: number }>;
  multi_tp_distribution?: string;
  pyramiding_enabled?: boolean;
  pyramiding_max_entries?: number;
  dca_mode?: string;
  max_trades_per_day?: number;
  max_trades_per_hour?: number;
  cooldown_after_loss_hours?: number;
  cooldown_after_consecutive_losses?: number;
  max_consecutive_losses?: number;
  signal_expiration_hours?: number;
  re_entry_cooldown_hours?: number;
  trend_only?: boolean;
  range_only?: boolean;
  volatility_threshold?: number;
  volume_threshold?: number;
  news_avoidance?: boolean;
  session_based_trading?: boolean;
  trading_sessions?: string[];
  timezone?: string;
  trading_days?: string[];
  weekend_restriction?: boolean;
  holiday_restriction?: boolean;
  alert_entry?: boolean;
  alert_exit?: boolean;
  alert_sl_hit?: boolean;
  alert_tp_hit?: boolean;
  alert_drawdown?: boolean;
  alert_strategy_paused?: boolean;
  cycle_enabled?: boolean;
  cycle_target_pnl_pct?: number;
  cycle_max_trades?: number;
  cycle_timeout_hours?: number;
  cycle_stop_loss_pct?: number;
  cycle_cooldown_hours?: number;
  cycle_auto_restart?: boolean;
  cycle_partial_close_allowed?: boolean;
  alert_cycle_complete?: boolean;
  emergency_kill_switch?: boolean;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: StrategyCategory;
  status: StrategyStatus;
  config: StrategyConfig;
  created_at: string;
  updated_at: string;
}

export interface StrategyCreate {
  name: string;
  description?: string;
  category?: StrategyCategory;
  status?: StrategyStatus;
  config?: StrategyConfig;
}

export const apiClient = {
  getHealth: (signal?: AbortSignal) =>
    request<HealthResponse>("/api/v1/health", undefined, signal),

  listAnalyses: (
    params?: {
      page?: number;
      limit?: number;
      ticker?: string;
      status?: string;
      asset_type?: AssetType;
    },
    signal?: AbortSignal,
  ) => {
    const sp = new URLSearchParams();
    if (params?.page != null) sp.set("page", String(params.page));
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.ticker) sp.set("ticker", params.ticker);
    if (params?.status) sp.set("status", params.status);
    if (params?.asset_type) sp.set("asset_type", params.asset_type);
    const qs = sp.toString();
    return request<AnalysisListResponse>(
      `/api/v1/analysis${qs ? `?${qs}` : ""}`,
      undefined,
      signal,
    );
  },

  startAnalysis: (body: StartAnalysisRequest) =>
    mutate<AnalysisCreateResponse>("POST", "/api/v1/analysis", body),

  getAnalysis: (runId: string, signal?: AbortSignal) =>
    request<AnalysisRun>(
      `/api/v1/analysis/${encodeURIComponent(runId)}`,
      undefined,
      signal,
    ),

  cancelAnalysis: (runId: string) =>
    mutate<{ status: string }>(
      "POST",
      `/api/v1/analysis/${encodeURIComponent(runId)}/cancel`,
    ),

  deleteAnalysis: (runId: string) =>
    mutate<void>(
      "DELETE",
      `/api/v1/analysis/${encodeURIComponent(runId)}`,
    ),

  deleteAllAnalyses: () =>
    mutate<{ deleted: number }>(
      "DELETE",
      "/api/v1/analysis",
    ),

  getReport: (runId: string, signal?: AbortSignal) =>
    requestText(
      `/api/v1/analysis/${encodeURIComponent(runId)}/report`,
      signal,
    ),

  getSnapshot: (runId: string, signal?: AbortSignal) =>
    request<AnalysisSnapshot>(
      `/api/v1/analysis/${encodeURIComponent(runId)}/snapshot`,
      undefined,
      signal,
    ),

  getConfig: (signal?: AbortSignal) =>
    request<ConfigResponse>("/api/v1/config", undefined, signal),

  updateConfig: (overrides: Record<string, unknown>) =>
    mutate<ConfigResponse>("PATCH", "/api/v1/config", { overrides }),

  getMemory: (params?: { page?: number; limit?: number }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.page != null) sp.set("page", String(params.page));
    if (params?.limit != null) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request<MemoryListResponse>(`/api/v1/memory${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  getCheckpoint: (ticker: string, date: string, signal?: AbortSignal) =>
    request<CheckpointResponse>(`/api/v1/checkpoints?ticker=${encodeURIComponent(ticker)}&date=${encodeURIComponent(date)}`, undefined, signal),

  deleteAllCheckpoints: () =>
    mutate<void>("DELETE", "/api/v1/checkpoints?confirm=true"),

  deleteTickerCheckpoints: (ticker: string) =>
    mutate<void>("DELETE", `/api/v1/checkpoints/${encodeURIComponent(ticker)}?confirm=true`),

  getSymbols: (assetType: string, signal?: AbortSignal) =>
    request<{ symbols: string[] }>(`/api/v1/symbols?asset_type=${encodeURIComponent(assetType)}`, undefined, signal),

  // Scanner
  startScan: (body: ScanRequest) =>
    mutate<{ scan_id: string; status: string }>("POST", "/api/v1/scanner", body),

  listScans: (signal?: AbortSignal) =>
    request<{ scans: ScanStatus[] }>("/api/v1/scanner", undefined, signal),

  getScan: (scanId: string, signal?: AbortSignal) =>
    request<ScanStatus>(`/api/v1/scanner/${encodeURIComponent(scanId)}`, undefined, signal),

  cancelScan: (scanId: string) =>
    mutate<{ status: string }>("POST", `/api/v1/scanner/${encodeURIComponent(scanId)}/cancel`),

  deleteScanPreview: (scanId: string, signal?: AbortSignal) =>
    request<{ scan_id: string; analysis_count: number }>(
      `/api/v1/scanner/${encodeURIComponent(scanId)}/delete-preview`, undefined, signal,
    ),

  deleteScan: (scanId: string) =>
    mutate<{ deleted_results: number; deleted_analyses: number; deleted_sections: number }>(
      "DELETE", `/api/v1/scanner/${encodeURIComponent(scanId)}`,
    ),

  getProviders: (signal?: AbortSignal) =>
    request<{ providers: string[] }>("/api/v1/providers", undefined, signal),

  getModels: (provider: string, signal?: AbortSignal) =>
    request<{ provider: string; quick: Array<{ label: string; value: string }>; deep: Array<{ label: string; value: string }> }>(
      `/api/v1/models/${encodeURIComponent(provider)}`, undefined, signal,
    ),

  // ── Strategies ──────────────────────────────────────────────────

  listStrategies: (params?: { status?: string; category?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.status) sp.set("status", params.status);
    if (params?.category) sp.set("category", params.category);
    const qs = sp.toString();
    return request<Strategy[]>(`/api/v1/strategies${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  getStrategy: (id: string, signal?: AbortSignal) =>
    request<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}`, undefined, signal),

  createStrategy: (data: StrategyCreate) =>
    mutate<Strategy>("POST", "/api/v1/strategies", data),

  updateStrategy: (id: string, data: Partial<StrategyCreate>) =>
    mutate<Strategy>("PATCH", `/api/v1/strategies/${encodeURIComponent(id)}`, data),

  deleteStrategy: (id: string) =>
    mutate<{ deleted: boolean }>("DELETE", `/api/v1/strategies/${encodeURIComponent(id)}`),

  exportStrategies: (signal?: AbortSignal) =>
    request<{ strategies: Strategy[] }>("/api/v1/strategies/export", undefined, signal),

  importStrategies: (strategies: StrategyCreate[]) =>
    mutate<{ imported: number; strategies: Strategy[] }>("POST", "/api/v1/strategies/import", { strategies }),
};

// ── Trading Accounts API ─────────────────────────────────────────────

export interface TradingAccount {
  id: string;
  label: string;
  account_type: "demo" | "live";
  api_key_masked: string;
  is_active: boolean;
  include_in_analytics: boolean;
  bybit_uid?: string;
  last_connected_at?: string;
  last_error?: string;
  created_at: string;
  updated_at: string;
}

export interface WalletBalance {
  totalEquity: string;
  totalWalletBalance: string;
  totalAvailableBalance: string;
  totalPerpUPL: string;
  accountIMRate?: string;
  accountMMRate?: string;
  coin: Array<Record<string, string>>;
  fetched_at: string;
}

export interface Position {
  symbol: string;
  side: string;
  size: string;
  avgPrice: string;
  markPrice: string;
  unrealisedPnl: string;
  leverage: string;
  liqPrice: string;
  takeProfit?: string;
  stopLoss?: string;
}

export interface OpenOrder {
  orderId: string;
  symbol: string;
  side: string;
  orderType: string;
  qty: string;
  price: string;
  orderStatus: string;
  createdTime: string;
  triggerPrice?: string;
  stopOrderType?: string;
}

export interface ClosedPnlResponse {
  items: Array<Record<string, unknown>>;
  total: number;
  page: number;
  limit: number;
}

export interface PnlSummary {
  total_pnl: string;
  win_count: number;
  loss_count: number;
  win_rate: number;
  avg_win: string;
  avg_loss: string;
}

export interface DashboardCard {
  id: string;
  label: string;
  account_type: "demo" | "live";
  is_active: boolean;
  include_in_analytics: boolean;
  total_equity?: string;
  total_perp_upl?: string;
  total_wallet_balance?: string;
  today_pnl?: string;
  positions_count: number;
  last_connected_at?: string;
  last_error?: string;
  status: "active" | "stale" | "error" | "disabled";
  active_rules_count?: number;
  active_rule_targets?: Array<{
    trigger_type: string;
    threshold_value: string | null;
    reference_value: string | null;
  }>;
}

export interface DailySnapshot {
  id?: number;
  account_id?: string;
  snapshot_date: string;
  equity: number;
  wallet_balance: number;
  available_balance: number;
  unrealised_pnl: number;
  realised_pnl: number;
  positions_count: number;
  margin_used: number;
  cumulative_pnl: number;
  daily_return_pct: number;
  peak_equity: number;
  drawdown_pct: number;
}

export interface PerformanceAnalytics {
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  profit_factor: number;
  win_rate: number;
  win_count: number;
  loss_count: number;
  avg_win: string;
  avg_loss: string;
  expectancy: number;
  avg_daily_return_pct: number;
  best_day_pct: number;
  best_day_date: string;
  worst_day_pct: number;
  worst_day_date: string;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  drawdown_duration_days: number;
  recovery_time_days: number;
  total_trades: number;
  total_pnl: string;
  snapshot_count: number;
}

export interface PlaceTradeRequest {
  symbol: string;
  signal_direction: "buy" | "sell";
  trade_direction: "straight" | "reverse";
  leverage: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  capital_pct: number;
  base_capital: number;
}

export interface PlaceTradeResponse {
  orderId: string;
  symbol: string;
  side: string;
  leverage: number;
  max_leverage: number;
  mark_price: string;
  take_profit_price: string;
  stop_loss_price: string;
  qty: string;
  usdt_amount: string;
}

export const accountsApi = {
  list: (params?: { account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<TradingAccount[]>(`/api/v1/accounts${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  create: (data: { label: string; account_type: string; api_key: string; api_secret: string }) =>
    mutate<TradingAccount>("POST", "/api/v1/accounts", data),

  get: (id: string, signal?: AbortSignal) =>
    request<TradingAccount>(`/api/v1/accounts/${encodeURIComponent(id)}`, undefined, signal),

  update: (id: string, data: { label?: string; is_active?: boolean }) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}`, data),

  rotateCredentials: (id: string, data: { api_key: string; api_secret: string }) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}/credentials`, data),

  delete: (id: string) =>
    mutate<{ status: string }>("DELETE", `/api/v1/accounts/${encodeURIComponent(id)}`),

  testConnection: (id: string) =>
    mutate<{ success: boolean; uid?: string; error?: string }>("POST", `/api/v1/accounts/${encodeURIComponent(id)}/test`),

  getWallet: (id: string, signal?: AbortSignal) =>
    request<WalletBalance>(`/api/v1/accounts/${encodeURIComponent(id)}/wallet`, undefined, signal),

  getPositions: (id: string, signal?: AbortSignal) =>
    request<Position[]>(`/api/v1/accounts/${encodeURIComponent(id)}/positions`, undefined, signal),

  getOrders: (id: string, signal?: AbortSignal) =>
    request<OpenOrder[]>(`/api/v1/accounts/${encodeURIComponent(id)}/orders`, undefined, signal),

  getClosedPnl: (id: string, startDate: string, endDate: string, page = 1, limit = 100, signal?: AbortSignal) =>
    request<ClosedPnlResponse>(
      `/api/v1/accounts/${encodeURIComponent(id)}/closed-pnl?start_date=${startDate}&end_date=${endDate}&page=${page}&limit=${limit}`,
      undefined, signal,
    ),

  getPnlSummary: (id: string, startDate: string, endDate: string, signal?: AbortSignal) =>
    request<PnlSummary>(
      `/api/v1/accounts/${encodeURIComponent(id)}/closed-pnl/summary?start_date=${startDate}&end_date=${endDate}`,
      undefined, signal,
    ),

  getDashboard: (params?: { account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<DashboardCard[]>(`/api/v1/portfolio/dashboard${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  getPortfolioSummary: (signal?: AbortSignal) =>
    request<{ total_equity: string; total_unrealised_pnl: string; active_accounts: number; total_accounts: number }>(
      "/api/v1/portfolio/summary", undefined, signal,
    ),

  // Analytics & Snapshots
  takeSnapshot: (id: string) =>
    mutate<Record<string, unknown>>("POST", `/api/v1/accounts/${encodeURIComponent(id)}/snapshots`),

  takeAllSnapshots: () =>
    mutate<{ snapshots: Record<string, unknown>[]; count: number }>("POST", "/api/v1/snapshots/all"),

  getSnapshots: (id: string, params?: { start_date?: string; end_date?: string; period?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.start_date) sp.set("start_date", params.start_date);
    if (params?.end_date) sp.set("end_date", params.end_date);
    if (params?.period) sp.set("period", params.period);
    const qs = sp.toString();
    return request<DailySnapshot[]>(
      `/api/v1/accounts/${encodeURIComponent(id)}/snapshots${qs ? `?${qs}` : ""}`,
      undefined, signal,
    );
  },

  getAnalytics: (id: string, params?: { start_date?: string; end_date?: string; period?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.start_date) sp.set("start_date", params.start_date);
    if (params?.end_date) sp.set("end_date", params.end_date);
    if (params?.period) sp.set("period", params.period);
    const qs = sp.toString();
    return request<PerformanceAnalytics>(
      `/api/v1/accounts/${encodeURIComponent(id)}/analytics${qs ? `?${qs}` : ""}`,
      undefined, signal,
    );
  },

  getPortfolioSnapshots: (params?: { start_date?: string; end_date?: string; period?: string; account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.start_date) sp.set("start_date", params.start_date);
    if (params?.end_date) sp.set("end_date", params.end_date);
    if (params?.period) sp.set("period", params.period);
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<DailySnapshot[]>(
      `/api/v1/portfolio/snapshots${qs ? `?${qs}` : ""}`,
      undefined, signal,
    );
  },

  getPortfolioAnalytics: (params?: { start_date?: string; end_date?: string; period?: string; account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.start_date) sp.set("start_date", params.start_date);
    if (params?.end_date) sp.set("end_date", params.end_date);
    if (params?.period) sp.set("period", params.period);
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<PerformanceAnalytics>(
      `/api/v1/portfolio/analytics${qs ? `?${qs}` : ""}`,
      undefined, signal,
    );
  },

  setAnalyticsInclusion: (id: string, include: boolean) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}/analytics-inclusion`, { include }),

  countSnapshots: (id: string | null, params?: { preset?: string; before?: string; after?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.preset) sp.set("preset", params.preset);
    if (params?.before) sp.set("before", params.before);
    if (params?.after) sp.set("after", params.after);
    const qs = sp.toString();
    const path = id
      ? `/api/v1/accounts/${encodeURIComponent(id)}/snapshots/count`
      : `/api/v1/portfolio/snapshots/count`;
    return request<{ counts: Record<string, number>; total: number }>(
      `${path}${qs ? `?${qs}` : ""}`, undefined, signal,
    );
  },

  cleanupSnapshots: (id: string | null, params?: { preset?: string; before?: string; after?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.preset) sp.set("preset", params.preset);
    if (params?.before) sp.set("before", params.before);
    if (params?.after) sp.set("after", params.after);
    const qs = sp.toString();
    const path = id
      ? `/api/v1/accounts/${encodeURIComponent(id)}/snapshots/cleanup`
      : `/api/v1/portfolio/snapshots/cleanup`;
    return mutate<{ deleted: Record<string, number>; total: number }>(
      "DELETE", `${path}${qs ? `?${qs}` : ""}`, undefined, signal,
    );
  },

  // ── Close Positions ───────────────────────────────────────────

  closeAllPositions: (accountId: string, signal?: AbortSignal) =>
    mutate<CloseAllResult>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/positions/close-all`, undefined, signal),

  getCloseRules: (accountId: string, signal?: AbortSignal) =>
    request<CloseRule[]>(`/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules`, undefined, signal),

  createCloseRule: (accountId: string, data: CreateCloseRuleData, signal?: AbortSignal) =>
    mutate<CloseRule>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules`, data, signal),

  updateCloseRule: (accountId: string, ruleId: string, data: UpdateCloseRuleData, signal?: AbortSignal) =>
    mutate<CloseRule>("PUT", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules/${encodeURIComponent(ruleId)}`, data, signal),

  deleteCloseRule: (accountId: string, ruleId: string, signal?: AbortSignal) =>
    mutate<{ status: string }>("DELETE", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules/${encodeURIComponent(ruleId)}`, undefined, signal),

  getCloseExecutions: (accountId: string, page = 1, limit = 20, signal?: AbortSignal) =>
    request<CloseExecutionsPage>(`/api/v1/accounts/${encodeURIComponent(accountId)}/close-executions?page=${page}&limit=${limit}`, undefined, signal),

  // ── Place Trade ─────────────────────────────────────────────────

  placeTrade: (accountId: string, data: PlaceTradeRequest, signal?: AbortSignal) =>
    mutate<PlaceTradeResponse>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/trade`, data, signal),
};

// ── Scheduled Scans ──────────────────────────────────────────────

export type ScheduleType = "once" | "interval" | "daily" | "weekly" | "cron";
export type ScheduleStatus = "active" | "paused" | "completed" | "error";

export interface ScheduleConfig {
  run_at?: string;
  interval_minutes?: number;
  time?: string;
  days?: string[];
  day?: string;
  cron_expression?: string;
}

export interface ScheduledScan {
  id: string;
  name: string;
  schedule_type: ScheduleType;
  schedule_config: ScheduleConfig;
  scan_config: Record<string, unknown>;
  status: ScheduleStatus;
  timezone: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_scan_id: string | null;
  consecutive_failures: number;
  created_at: string;
  updated_at: string;
}

export interface ScheduleExecution {
  id: number;
  schedule_id: string;
  scan_id: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface CreateScheduledScanRequest {
  name: string;
  schedule_type: ScheduleType;
  schedule_config: ScheduleConfig;
  scan_config: Record<string, unknown>;
  timezone?: string;
}

export const scheduledScansApi = {
  list: (signal?: AbortSignal) =>
    request<{ schedules: ScheduledScan[] }>("/api/v1/scheduled-scans", undefined, signal),

  get: (id: string, signal?: AbortSignal) =>
    request<ScheduledScan & { recent_executions: ScheduleExecution[] }>(
      `/api/v1/scheduled-scans/${encodeURIComponent(id)}`, undefined, signal,
    ),

  create: (data: CreateScheduledScanRequest, signal?: AbortSignal) =>
    mutate<ScheduledScan>("POST", "/api/v1/scheduled-scans", data, signal),

  update: (id: string, data: Partial<CreateScheduledScanRequest>, signal?: AbortSignal) =>
    mutate<ScheduledScan>("PATCH", `/api/v1/scheduled-scans/${encodeURIComponent(id)}`, data, signal),

  delete: (id: string, signal?: AbortSignal) =>
    mutate<{ deleted: boolean }>("DELETE", `/api/v1/scheduled-scans/${encodeURIComponent(id)}`, undefined, signal),

  pause: (id: string, signal?: AbortSignal) =>
    mutate<ScheduledScan>("POST", `/api/v1/scheduled-scans/${encodeURIComponent(id)}/pause`, undefined, signal),

  resume: (id: string, signal?: AbortSignal) =>
    mutate<ScheduledScan>("POST", `/api/v1/scheduled-scans/${encodeURIComponent(id)}/resume`, undefined, signal),

  trigger: (id: string, signal?: AbortSignal) =>
    mutate<ScheduledScan>("POST", `/api/v1/scheduled-scans/${encodeURIComponent(id)}/trigger`, undefined, signal),

  listExecutions: (id: string, limit = 20, signal?: AbortSignal) =>
    request<{ executions: ScheduleExecution[] }>(
      `/api/v1/scheduled-scans/${encodeURIComponent(id)}/executions?limit=${limit}`, undefined, signal,
    ),
};

// ── Close Positions Types ─────────────────────────────────────

export type TriggerType = "BALANCE_BELOW" | "BALANCE_ABOVE" | "EQUITY_DROP_PCT" | "EQUITY_RISE_PCT" | "PNL_BELOW" | "PNL_ABOVE";

export interface CloseRule {
  id: string;
  account_id: string;
  trigger_type: TriggerType;
  threshold_value: string;
  reference_value: string | null;
  status: "active" | "paused" | "triggered" | "executed" | "expired";
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  triggered_at: string | null;
}

export interface CreateCloseRuleData {
  trigger_type: TriggerType;
  threshold_value: string;
  reference_value?: string;
}

export interface UpdateCloseRuleData {
  trigger_type?: TriggerType;
  threshold_value?: string;
  reference_value?: string;
  status?: "active" | "paused";
}

export interface CloseAllResult {
  total: number;
  closed: number;
  failed: number;
  results: Array<{
    symbol: string;
    status: "closed" | "failed";
    orderId?: string;
    error?: string;
  }>;
  execution_id: string;
}

export interface CloseExecution {
  id: string;
  account_id: string;
  rule_id: string | null;
  trigger_source: "manual" | "rule";
  total_positions: number;
  closed_count: number;
  failed_count: number;
  results: Array<{ symbol: string; status: string; orderId?: string; error?: string }>;
  executed_at: string;
}

export interface CloseExecutionsPage {
  items: CloseExecution[];
  total: number;
  page: number;
  limit: number;
}

// ── Trading Cycles ──────────────────────────────────────────────

export interface CreateCycleRequest {
  account_id: string;
  scan_id: string;
  trade_direction: "straight" | "reverse";
  leverage: number;
  capital_pct: number;
  take_profit_pct?: number;
  stop_loss_pct?: number;
  min_score: number;
  min_confidence: "none" | "low" | "moderate" | "high";
  signal_filter: "buy" | "sell" | "both";
  max_trades: number;
  target_type: "percentage" | "amount";
  target_value: number;
  max_drawdown_pct: number;
}

export interface CycleResponse {
  id: number;
  status: "pending" | "placing_trades" | "running" | "stopping" | "completed" | "stopped" | "failed";
  account_id: string;
  scan_id: string | null;
  trades_placed: number;
  trades_failed: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  stop_reason: string | null;
}

export interface CycleTradeResponse {
  id: number;
  symbol: string;
  side: string;
  qty: number | null;
  entry_price: number | null;
  status: "pending" | "submitted" | "filled" | "failed" | "cancelled";
  error_msg: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface CycleDetail extends CycleResponse {
  trades: CycleTradeResponse[];
  trade_direction: string;
  leverage: number;
  capital_pct: number;
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  min_score: number;
  min_confidence: string;
  signal_filter: string;
  max_trades: number;
  target_type: string;
  target_value: number;
  max_drawdown_pct: number;
  initial_equity: number | null;
  final_pnl: number | null;
}

export interface DryRunResponse {
  qualifying_symbols: string[];
  estimated_trades: number;
  balance_above_threshold: number;
  balance_below_threshold: number;
  estimated_capital_per_trade: number;
  total_capital_pct: number;
  current_equity: number;
  warnings: string[];
}

export interface FilterPreviewResponse {
  qualifying_count: number;
  symbols: string[];
  direction_breakdown: Record<string, number>;
}

export interface PaginatedCycleList {
  items: CycleResponse[];
  total: number;
  offset: number;
  limit: number;
}

export const cyclesApi = {
  create: (data: CreateCycleRequest) =>
    mutate<CycleResponse>("POST", "/api/v1/trading-cycles", data),

  list: (params?: { offset?: number; limit?: number; status?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.offset != null) sp.set("offset", String(params.offset));
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.status) sp.set("status", params.status);
    const qs = sp.toString();
    return request<PaginatedCycleList>(`/api/v1/trading-cycles${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  get: (cycleId: number, signal?: AbortSignal) =>
    request<CycleDetail>(`/api/v1/trading-cycles/${cycleId}`, undefined, signal),

  stop: (cycleId: number) =>
    mutate<CycleResponse>("POST", `/api/v1/trading-cycles/${cycleId}/stop`),

  dryRun: (data: CreateCycleRequest) =>
    mutate<DryRunResponse>("POST", "/api/v1/trading-cycles/dry-run", data),

  filterPreview: (scanId: string, params?: { min_score?: number; min_confidence?: string; signal_filter?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.min_score != null) sp.set("min_score", String(params.min_score));
    if (params?.min_confidence) sp.set("min_confidence", params.min_confidence);
    if (params?.signal_filter) sp.set("signal_filter", params.signal_filter);
    const qs = sp.toString();
    return request<FilterPreviewResponse>(`/api/v1/scans/${encodeURIComponent(scanId)}/filter-preview${qs ? `?${qs}` : ""}`, undefined, signal);
  },
};
