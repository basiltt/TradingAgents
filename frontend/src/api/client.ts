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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export interface HealthResponse {
  status: string;
  db: string;
}

export interface AnalysisListResponse {
  items: AnalysisRun[];
  total: number;
  page: number;
  limit: number;
}

export interface AnalysisRun {
  run_id: string;
  ticker: string;
  status: string;
  analysis_date?: string;
  provider?: string;
  created_at?: string;
  updated_at?: string;
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
  analysts?: string[];
  research_depth?: number;
}

export interface ConfigResponse {
  resolved: Record<string, unknown>;
  overrides: Record<string, unknown>;
}

export const apiClient = {
  getHealth: () => request<HealthResponse>("/api/v1/health"),

  listAnalyses: (params?: {
    page?: number;
    limit?: number;
    ticker?: string;
    status?: string;
  }) => {
    const sp = new URLSearchParams();
    if (params?.page) sp.set("page", String(params.page));
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.ticker) sp.set("ticker", params.ticker);
    if (params?.status) sp.set("status", params.status);
    const qs = sp.toString();
    return request<AnalysisListResponse>(
      `/api/v1/analysis${qs ? `?${qs}` : ""}`,
    );
  },

  startAnalysis: (body: StartAnalysisRequest) =>
    mutate<AnalysisCreateResponse>("POST", "/api/v1/analysis", body),

  getAnalysis: (runId: string) =>
    request<AnalysisRun>(`/api/v1/analysis/${encodeURIComponent(runId)}`),

  cancelAnalysis: (runId: string) =>
    mutate<{ status: string }>(
      "POST",
      `/api/v1/analysis/${encodeURIComponent(runId)}/cancel`,
    ),

  getReport: (runId: string) =>
    fetch(`/api/v1/analysis/${encodeURIComponent(runId)}/report`).then(
      (res) => {
        if (!res.ok) throw new ApiError(res.status, "Report not available");
        return res.text();
      },
    ),

  getConfig: () => request<ConfigResponse>("/api/v1/config"),

  updateConfig: (overrides: Record<string, unknown>) =>
    mutate<ConfigResponse>("PATCH", "/api/v1/config", overrides),
};

export { ApiError };
