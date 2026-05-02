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
    detail = body.detail ?? detail;
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

export interface AnalysisListItem {
  run_id: string;
  ticker: string;
  analysis_date: string;
  status: string;
  started_at: string;
  completed_at?: string;
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
}

export interface AnalysisCreateResponse {
  run_id: string;
  status: string;
}

export interface StartAnalysisRequest {
  ticker: string;
  analysis_date: string;
  provider?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  backend_url?: string;
  analysts?: string[];
  research_depth?: number;
  output_language?: string;
  data_vendors?: Record<string, string>;
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

export const apiClient = {
  getHealth: (signal?: AbortSignal) =>
    request<HealthResponse>("/api/v1/health", undefined, signal),

  listAnalyses: (
    params?: {
      page?: number;
      limit?: number;
      ticker?: string;
      status?: string;
    },
    signal?: AbortSignal,
  ) => {
    const sp = new URLSearchParams();
    if (params?.page != null) sp.set("page", String(params.page));
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.ticker) sp.set("ticker", params.ticker);
    if (params?.status) sp.set("status", params.status);
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
};

export { ApiError };
