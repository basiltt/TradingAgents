/**
 * API client module — typed fetch wrappers for all backend endpoints.
 *
 * Exports namespace objects (accountsApi, tradesApi, cyclesApi, etc.)
 * that group related endpoints. All methods throw ApiError on non-2xx responses.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

import type {
  Trade,
  TradeListResponse,
  TradeStatsResponse,
  TradeEventsResponse,
} from "@/components/trades/types";

/** Typed error for non-2xx API responses. Contains HTTP status and detail message. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    const safeDetail = detail.length > 200 ? detail.slice(0, 200) + "…" : detail;
    super(`API error ${status}: ${safeDetail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = safeDetail;
  }
}

const DEFAULT_HEADERS: HeadersInit = {
  "X-Requested-With": "XMLHttpRequest",
};

/** Parse error detail from response body and throw ApiError. */
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

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

function isRetriable(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Fetch JSON from a path. Applies 30s default timeout, retries transient errors, and throws ApiError on non-2xx. */
async function request<T>(
  path: string,
  init?: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  const effectiveSignal = signal ?? init?.signal ?? AbortSignal.timeout(DEFAULT_TIMEOUT_MS);
  const method = init?.method?.toUpperCase() ?? "GET";
  const isIdempotent = method === "GET" || method === "HEAD";
  let lastError: unknown;
  const maxAttempts = isIdempotent ? MAX_RETRIES : 0;

  for (let attempt = 0; attempt <= maxAttempts; attempt++) {
    if (attempt > 0) {
      await sleep(RETRY_DELAY_MS * attempt);
    }
    try {
      const res = await fetch(`${BASE_URL}${path}`, {
        ...init,
        signal: effectiveSignal,
        headers: { ...DEFAULT_HEADERS, ...init?.headers },
      });
      if (!res.ok) {
        if (isIdempotent && isRetriable(res.status) && attempt < MAX_RETRIES) {
          lastError = new ApiError(res.status, res.statusText);
          continue;
        }
        return throwApiError(res);
      }
      if (res.status === 204) return undefined as T;
      return res.json() as Promise<T>;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      if (isIdempotent && attempt < MAX_RETRIES) {
        lastError = e;
        continue;
      }
      throw new ApiError(0, `Network error: ${e instanceof Error ? e.message : "unable to reach server"}`);
    }
  }
  if (lastError instanceof ApiError) throw lastError;
  throw new ApiError(0, `Network error: ${lastError instanceof Error ? lastError.message : "unable to reach server"}`);
}

/** Fetch plain text from a path. Throws ApiError on non-2xx. */
async function requestText(
  path: string,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: DEFAULT_HEADERS,
    signal: signal ?? AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
  });
  if (!res.ok) return throwApiError(res);
  return res.text();
}

/** Send a mutating request (POST/PUT/PATCH/DELETE) with optional JSON body. */
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
  error?: string;
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

export interface AutoTradeConfig {
  account_id: string;
  direction: "straight" | "reverse";
  leverage: number;
  capital_pct: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  min_score: number;
  confidence_filter: "any" | "high" | "moderate" | "low";
  signal_sides: "both" | "buy" | "sell";
  max_trades: number;
  max_drawdown_pct: number;
  target_goal_type?: "profit_pct" | "trade_count" | null;
  target_goal_value?: number | null;
  execution_mode: "immediate" | "batch";
  skip_if_positions_open?: boolean;
  fill_to_max_trades?: boolean;
  close_on_profit_pct?: number | null;
  breakeven_timeout_hours?: number | null;
  max_trade_duration_hours?: number | null;
  ai_manager_enabled?: boolean;
  symbol_blacklist?: string[] | null;
  symbol_whitelist?: string[] | null;
  max_signal_age_minutes?: number | null;
  smart_drawdown_close?: boolean;
  trailing_profit_pct?: number | null;
  max_same_direction?: number | null;
  max_price_drift_pct?: number | null;
  max_same_sector?: number | null;
  adaptive_blacklist_enabled?: boolean;
  adaptive_blacklist_min_trades?: number;
  adaptive_blacklist_max_win_rate?: number;
  adaptive_blacklist_lookback_hours?: number;
  ai_pause_cycles?: number | null;
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
  auto_trade_configs?: AutoTradeConfig[];
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

export interface AutoTradeResult {
  symbol: string;
  side: string;
  status: "success" | "failed";
  order_id?: string | null;
  error?: string | null;
  account_id: string;
}

export interface AutoTradeSummary {
  account_id: string;
  trades_executed: number;
  trades_failed: number;
  trades_skipped: number;
  stopped_reason?: string | null;
  close_rule_id?: string | null;
  drawdown_rule_id?: string | null;
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
  auto_trade_results?: AutoTradeResult[];
  auto_trade_summaries?: AutoTradeSummary[];
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

  fetchRemoteModels: (url: string, apiKey?: string, signal?: AbortSignal) =>
    mutate<{ models: Array<{ id: string; name?: string }>; error?: string }>(
      "POST", "/api/v1/fetch-models", { url, api_key: apiKey || null }, signal,
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
  ai_manager_state?: string | null;
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

/** Accounts API — CRUD, portfolio, analytics, snapshots, and trade management endpoints. */
export const accountsApi = {
  /** GET /api/v1/accounts — list accounts with optional type filter. */
  list: (params?: { account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<TradingAccount[]>(`/api/v1/accounts${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  /** POST /api/v1/accounts — create a new trading account. */
  create: (data: { label: string; account_type: string; api_key: string; api_secret: string }) =>
    mutate<TradingAccount>("POST", "/api/v1/accounts", data),

  /** GET /api/v1/accounts/:id — fetch a single account. */
  get: (id: string, signal?: AbortSignal) =>
    request<TradingAccount>(`/api/v1/accounts/${encodeURIComponent(id)}`, undefined, signal),

  /** PATCH /api/v1/accounts/:id — update label or active status. */
  update: (id: string, data: { label?: string; is_active?: boolean }) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}`, data),

  /** PATCH /api/v1/accounts/:id/credentials — rotate API key/secret. */
  rotateCredentials: (id: string, data: { api_key: string; api_secret: string }) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}/credentials`, data),

  /** DELETE /api/v1/accounts/:id — delete an account. */
  delete: (id: string) =>
    mutate<{ status: string }>("DELETE", `/api/v1/accounts/${encodeURIComponent(id)}`),

  /** POST /api/v1/accounts/:id/test — test exchange connection. */
  testConnection: (id: string) =>
    mutate<{ success: boolean; uid?: string; error?: string }>("POST", `/api/v1/accounts/${encodeURIComponent(id)}/test`),

  /** GET /api/v1/accounts/:id/wallet — fetch wallet balance. */
  getWallet: (id: string, signal?: AbortSignal) =>
    request<WalletBalance>(`/api/v1/accounts/${encodeURIComponent(id)}/wallet`, undefined, signal),

  /** GET /api/v1/accounts/:id/positions — fetch open positions. */
  getPositions: (id: string, signal?: AbortSignal) =>
    request<Position[]>(`/api/v1/accounts/${encodeURIComponent(id)}/positions`, undefined, signal),

  /** GET /api/v1/accounts/:id/orders — fetch open orders. */
  getOrders: (id: string, signal?: AbortSignal) =>
    request<OpenOrder[]>(`/api/v1/accounts/${encodeURIComponent(id)}/orders`, undefined, signal),

  /** GET /api/v1/accounts/:id/closed-pnl — fetch closed PnL with pagination. */
  getClosedPnl: (id: string, startDate: string, endDate: string, page = 1, limit = 100, signal?: AbortSignal) =>
    request<ClosedPnlResponse>(
      `/api/v1/accounts/${encodeURIComponent(id)}/closed-pnl?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&page=${page}&limit=${limit}`,
      undefined, signal,
    ),

  /** GET /api/v1/accounts/:id/closed-pnl/summary — fetch PnL summary. */
  getPnlSummary: (id: string, startDate: string, endDate: string, signal?: AbortSignal) =>
    request<PnlSummary>(
      `/api/v1/accounts/${encodeURIComponent(id)}/closed-pnl/summary?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`,
      undefined, signal,
    ),

  /** GET /api/v1/portfolio/dashboard — fetch dashboard cards for all accounts. */
  getDashboard: (params?: { account_type?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.account_type) sp.set("account_type", params.account_type);
    const qs = sp.toString();
    return request<DashboardCard[]>(`/api/v1/portfolio/dashboard${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  /** GET /api/v1/portfolio/summary — fetch aggregate portfolio summary. */
  getPortfolioSummary: (signal?: AbortSignal) =>
    request<{ total_equity: string; total_unrealised_pnl: string; active_accounts: number; total_accounts: number }>(
      "/api/v1/portfolio/summary", undefined, signal,
    ),

  // Analytics & Snapshots
  /** POST /api/v1/accounts/:id/snapshots — take a manual snapshot. */
  takeSnapshot: (id: string) =>
    mutate<Record<string, unknown>>("POST", `/api/v1/accounts/${encodeURIComponent(id)}/snapshots`),

  /** POST /api/v1/snapshots/all — take snapshots for all active accounts. */
  takeAllSnapshots: () =>
    mutate<{ snapshots: Record<string, unknown>[]; count: number }>("POST", "/api/v1/snapshots/all"),

  /** GET /api/v1/accounts/:id/snapshots — fetch daily snapshots with date range. */
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

  /** GET /api/v1/accounts/:id/analytics — fetch performance analytics. */
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

  /** GET /api/v1/portfolio/snapshots — fetch portfolio-wide snapshots. */
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

  /** GET /api/v1/portfolio/analytics — fetch portfolio-wide analytics. */
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

  /** PATCH /api/v1/accounts/:id/analytics-inclusion — toggle analytics opt-in. */
  setAnalyticsInclusion: (id: string, include: boolean) =>
    mutate<TradingAccount>("PATCH", `/api/v1/accounts/${encodeURIComponent(id)}/analytics-inclusion`, { include }),

  /** GET /api/v1/accounts/:id/snapshots/count — count snapshots matching filters. */
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

  /** DELETE /api/v1/accounts/:id/snapshots/cleanup — delete snapshots matching filters. */
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
  /** POST /api/v1/accounts/:id/positions/close-all — close all open positions. */
  closeAllPositions: (accountId: string, signal?: AbortSignal) =>
    mutate<CloseAllResult>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/positions/close-all`, undefined, signal),

  /** POST /api/v1/accounts/master-close-all — kill switch: starts background close, progress via WS. */
  masterCloseAll: (accountIds?: string[], signal?: AbortSignal) =>
    mutate<MasterCloseStartResult>("POST", `/api/v1/accounts/master-close-all`, accountIds?.length ? { account_ids: accountIds } : undefined, signal),

  /** POST /api/v1/accounts/demo-reset-balance — starts background balance reset, progress via WS. */
  demoResetBalance: (targetBalance: number, accountIds?: string[], signal?: AbortSignal) =>
    mutate<DemoResetStartResult>("POST", `/api/v1/accounts/demo-reset-balance`, { target_balance: targetBalance, ...(accountIds?.length ? { account_ids: accountIds } : {}) }, signal),

  /** GET /api/v1/accounts/:id/close-rules — list close rules. */
  getCloseRules: (accountId: string, signal?: AbortSignal) =>
    request<CloseRule[]>(`/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules`, undefined, signal),

  /** POST /api/v1/accounts/:id/close-rules — create a close rule. */
  createCloseRule: (accountId: string, data: CreateCloseRuleData, signal?: AbortSignal) =>
    mutate<CloseRule>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules`, data, signal),

  /** PUT /api/v1/accounts/:id/close-rules/:ruleId — update a close rule. */
  updateCloseRule: (accountId: string, ruleId: string, data: UpdateCloseRuleData, signal?: AbortSignal) =>
    mutate<CloseRule>("PUT", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules/${encodeURIComponent(ruleId)}`, data, signal),

  /** DELETE /api/v1/accounts/:id/close-rules/:ruleId — delete a close rule. */
  deleteCloseRule: (accountId: string, ruleId: string, signal?: AbortSignal) =>
    mutate<{ status: string }>("DELETE", `/api/v1/accounts/${encodeURIComponent(accountId)}/close-rules/${encodeURIComponent(ruleId)}`, undefined, signal),

  /** GET /api/v1/accounts/:id/close-executions — list close execution history. */
  getCloseExecutions: (accountId: string, page = 1, limit = 20, signal?: AbortSignal) =>
    request<CloseExecutionsPage>(`/api/v1/accounts/${encodeURIComponent(accountId)}/close-executions?page=${page}&limit=${limit}`, undefined, signal),

  // ── Place Trade ─────────────────────────────────────────────────
  /** POST /api/v1/accounts/:id/trade — place a new trade on the exchange. */
  placeTrade: (accountId: string, data: PlaceTradeRequest, signal?: AbortSignal) =>
    mutate<PlaceTradeResponse>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/trade`, data, signal),
};

// ── Scheduled Scans ──────────────────────────────────────────────

export type ScheduleType = "once" | "interval" | "daily" | "weekly" | "cron";
export type ScheduleStatus = "active" | "paused" | "completed" | "error" | "cancelled";

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
  is_running: boolean;
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

export type TriggerType = "BALANCE_BELOW" | "BALANCE_ABOVE" | "EQUITY_DROP_PCT" | "EQUITY_RISE_PCT" | "PNL_BELOW" | "PNL_ABOVE" | "BREAKEVEN_TIMEOUT" | "MAX_DURATION";

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

export interface MasterCloseStartResult {
  task_id: string | null;
  accounts_total: number;
  message: string;
}

export interface MasterCloseAllResult {
  accounts_processed: number;
  total_positions_closed: number;
  accounts_failed: number;
  results: Array<{
    account_id: string;
    name: string;
    status: "closed" | "skipped" | "error";
    closed?: number;
    failed?: number;
    reason?: string;
  }>;
}

export interface DemoResetStartResult {
  task_id: string | null;
  accounts_total: number;
  message: string;
}

export interface DemoResetBalanceResult {
  target_balance: number;
  accounts_processed: number;
  success: number;
  results: Array<{
    account_id: string;
    name: string;
    status: "added" | "reduced" | "unchanged" | "error";
    amount?: number;
    new_balance?: number;
    balance?: number;
    reason?: string;
  }>;
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
  trade_direction: string;
  leverage: number;
  target_value: number;
  max_drawdown_pct: number;
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
  order_link_id: string | null;
  qty: number | null;
  entry_price: number | null;
  status: "pending" | "submitted" | "filled" | "failed" | "cancelled";
  error_msg: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface CycleDetail extends CycleResponse {
  trades: CycleTradeResponse[];
  capital_pct: number;
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  min_score: number;
  min_confidence: string;
  signal_filter: string;
  max_trades: number;
  target_type: string;
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

/** Trading cycles API — create, list, stop cycles and preview filters. */
export const cyclesApi = {
  /** POST /api/v1/trading-cycles — create a new trading cycle. */
  create: (data: CreateCycleRequest) =>
    mutate<CycleResponse>("POST", "/api/v1/trading-cycles", data),

  /** GET /api/v1/trading-cycles — list cycles with pagination and status filter. */
  list: (params?: { offset?: number; limit?: number; status?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.offset != null) sp.set("offset", String(params.offset));
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.status) sp.set("status", params.status);
    const qs = sp.toString();
    return request<PaginatedCycleList>(`/api/v1/trading-cycles${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  /** GET /api/v1/trading-cycles/:id — fetch cycle details. */
  get: (cycleId: number, signal?: AbortSignal) =>
    request<CycleDetail>(`/api/v1/trading-cycles/${cycleId}`, undefined, signal),

  /** POST /api/v1/trading-cycles/:id/stop — stop a running cycle. */
  stop: (cycleId: number) =>
    mutate<CycleResponse>("POST", `/api/v1/trading-cycles/${cycleId}/stop`),

  /** POST /api/v1/trading-cycles/dry-run — simulate cycle without executing. */
  dryRun: (data: CreateCycleRequest) =>
    mutate<DryRunResponse>("POST", "/api/v1/trading-cycles/dry-run", data),

  /** GET /api/v1/scans/:scanId/filter-preview — preview cycle filter results. */
  filterPreview: (scanId: string, params?: { min_score?: number; min_confidence?: string; signal_filter?: string }, signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (params?.min_score != null) sp.set("min_score", String(params.min_score));
    if (params?.min_confidence) sp.set("min_confidence", params.min_confidence);
    if (params?.signal_filter) sp.set("signal_filter", params.signal_filter);
    const qs = sp.toString();
    return request<FilterPreviewResponse>(`/api/v1/scans/${encodeURIComponent(scanId)}/filter-preview${qs ? `?${qs}` : ""}`, undefined, signal);
  },
};

/** Cross-account trades API — list, stats, events, close, and cancel. */
export const tradesApi = {
  /** GET /api/v1/trades — list trades across all accounts with filters and pagination. */
  list: (
    params?: {
      account_id?: string[];
      status?: string[];
      symbol?: string;
      side?: string;
      from_date?: string;
      to_date?: string;
      sort_by?: string;
      sort_dir?: string;
      cursor?: string;
      limit?: number;
    },
    signal?: AbortSignal,
  ) => {
    const sp = new URLSearchParams();
    if (params?.account_id?.length) sp.set("account_id", params.account_id.join(","));
    if (params?.status?.length) sp.set("status", params.status.join(","));
    if (params?.symbol) sp.set("symbol", params.symbol);
    if (params?.side) sp.set("side", params.side);
    if (params?.from_date) sp.set("from_date", params.from_date);
    if (params?.to_date) sp.set("to_date", params.to_date);
    if (params?.sort_by) sp.set("sort_by", params.sort_by);
    if (params?.sort_dir) sp.set("sort_dir", params.sort_dir);
    if (params?.cursor) sp.set("cursor", params.cursor);
    if (params?.limit) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request<TradeListResponse>(`/api/v1/trades${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  /** GET /api/v1/trades/stats — aggregate trade statistics across accounts. */
  getStats: (accountIds?: string[], signal?: AbortSignal) => {
    const sp = new URLSearchParams();
    if (accountIds?.length) sp.set("account_id", accountIds.join(","));
    const qs = sp.toString();
    return request<TradeStatsResponse>(`/api/v1/trades/stats${qs ? `?${qs}` : ""}`, undefined, signal);
  },

  /** GET /api/v1/accounts/:id/trades/:tradeId/events — fetch trade audit events. */
  getEvents: (accountId: string, tradeId: string, signal?: AbortSignal) =>
    request<TradeEventsResponse>(
      `/api/v1/accounts/${encodeURIComponent(accountId)}/trades/${encodeURIComponent(tradeId)}/events`,
      undefined,
      signal,
    ),

  /** POST /api/v1/accounts/:id/trades/:tradeId/close — close a trade (full or partial). */
  close: (accountId: string, tradeId: string, data?: { qty?: number; close_reason?: string }, signal?: AbortSignal) =>
    mutate<Trade>(
      "POST",
      `/api/v1/accounts/${encodeURIComponent(accountId)}/trades/${encodeURIComponent(tradeId)}/close`,
      data ?? {},
      signal,
    ),

  /** POST /api/v1/accounts/:id/trades/:tradeId/cancel — cancel a pending trade. */
  cancel: (accountId: string, tradeId: string, signal?: AbortSignal) =>
    mutate<void>(
      "POST",
      `/api/v1/accounts/${encodeURIComponent(accountId)}/trades/${encodeURIComponent(tradeId)}/cancel`,
      {},
      signal,
    ),
};

/** API methods for the AI autonomous trading manager (per-account lifecycle + global kill). */
export const aiManagerApi = {
  /** Enables autonomous trading for the given account. */
  enable: (accountId: string) =>
    mutate<{ status: string; account_id: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/enable`),

  /** Disables autonomous trading, preserving config for later re-enable. */
  disable: (accountId: string) =>
    mutate<{ status: string; account_id: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/disable`),

  /** Fetches current runtime status (state machine, budget, circuit breaker, positions). */
  getStatus: (accountId: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/status`, undefined, signal),

  /** Fetches the full configuration (risk params, schedule, symbol filters). */
  getConfig: (accountId: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/config`, undefined, signal),

  /** Partially updates configuration — only provided keys are changed. */
  patchConfig: (accountId: string, updates: Record<string, unknown>) =>
    mutate<{ status: string }>("PATCH", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/config`, updates),

  /** Pauses the AI manager without disabling — retains state for fast resume. */
  pause: (accountId: string) =>
    mutate<{ status: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/pause`),

  /** Resumes a paused AI manager back to monitoring. */
  resume: (accountId: string) =>
    mutate<{ status: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/resume`),

  /** Activates the kill switch — immediately halts all trading for this account. */
  kill: (accountId: string) =>
    mutate<{ status: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/kill`),

  /** Resets the kill switch, allowing the AI manager to trade again. */
  resetKill: (accountId: string) =>
    mutate<{ status: string }>("POST", `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/kill/reset`),

  /** Fetches paginated trading decisions with cursor-based pagination. */
  getDecisions: (accountId: string, params?: { limit?: number; cursor?: string }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.cursor) sp.set("cursor", params.cursor);
    const qs = sp.toString();
    return request<{ decisions: unknown[]; next_cursor: string | null }>(
      `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/decisions${qs ? `?${qs}` : ""}`,
    );
  },

  /** Fetches aggregated performance metrics for a given time period. */
  getPerformance: (accountId: string, period = "7d") =>
    request<Record<string, unknown>>(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/performance?period=${encodeURIComponent(period)}`),

  /** Fetches paginated structured logs with optional level/category filters. */
  getLogs: (accountId: string, params?: { limit?: number; level?: string; category?: string; cursor?: number }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.level) sp.set("level", params.level);
    if (params?.category) sp.set("category", params.category);
    if (params?.cursor) sp.set("cursor", String(params.cursor));
    const qs = sp.toString();
    return request<{ logs: Array<{ id: number; timestamp: string; level: string; category: string; message: string; details: Record<string, unknown> | null }>; next_cursor: number | null }>(
      `/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/logs${qs ? `?${qs}` : ""}`,
    );
  },

  /** Activates the global kill switch across ALL accounts — emergency stop. */
  globalKill: () =>
    mutate<{ status: string }>("POST", "/api/v1/ai-manager/global-kill"),

  // --- Dashboard Enhancement ---

  getLLMCalls: (accountId: string, params?: { limit?: number; cursor?: string }): Promise<{ calls: unknown[]; next_cursor: string | null }> => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set("limit", String(params.limit));
    if (params?.cursor) searchParams.set("cursor", params.cursor);
    const qs = searchParams.toString();
    return request(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/llm-calls${qs ? `?${qs}` : ""}`);
  },

  getCapabilities: (accountId: string): Promise<Record<string, unknown>> =>
    request(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/capabilities-status`),

  getInsights: (accountId: string): Promise<Record<string, unknown>> =>
    request(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/market-insights`),

  getAnalysisContext: (accountId: string): Promise<Record<string, unknown>> =>
    request(`/api/v1/accounts/${encodeURIComponent(accountId)}/ai-manager/analysis-context`),
};
