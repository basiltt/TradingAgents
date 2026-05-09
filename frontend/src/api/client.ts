const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

class ApiError extends Error {
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

function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { ...DEFAULT_HEADERS, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
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
  started_at: string;
  completed_at: string | null;
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
};

export { ApiError };

// ── Trading Accounts API ─────────────────────────────────────────────

export interface TradingAccount {
  id: string;
  label: string;
  account_type: "demo" | "live";
  api_key_masked: string;
  is_active: boolean;
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
  total_equity?: string;
  total_perp_upl?: string;
  today_pnl?: string;
  positions_count: number;
  last_connected_at?: string;
  last_error?: string;
  status: "active" | "stale" | "error" | "disabled";
}

export const accountsApi = {
  list: (signal?: AbortSignal) =>
    request<TradingAccount[]>("/api/v1/accounts", undefined, signal),

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

  getDashboard: (signal?: AbortSignal) =>
    request<DashboardCard[]>("/api/v1/portfolio/dashboard", undefined, signal),

  getPortfolioSummary: (signal?: AbortSignal) =>
    request<{ total_equity: string; total_unrealised_pnl: string; active_accounts: number; total_accounts: number }>(
      "/api/v1/portfolio/summary", undefined, signal,
    ),
};
